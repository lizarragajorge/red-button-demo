import json
import ssl
import stat
import subprocess
import urllib.error
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import release

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
RELEASE_ID = "22222222-2222-4222-8222-222222222222"
OPERATION_ID = "33333333-3333-4333-8333-333333333333"
SECRET = "must-never-appear-in-output"


@pytest.fixture
def workspace():
    # Keep test artifacts inside this project, not OS temporary directories.
    path = Path(".pytest_cache/release-tests") / str(uuid.uuid4())
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        release.shutil.rmtree(path)


@pytest.fixture
def package(workspace):
    inputs = {"server/app.py": b"# fixture\n", "server/__main__.py": b"# entry\n",
              "requirements.txt": b"example==1.0\n", "function_app.py": b"# function\n", "host.json": b"{}"}
    fingerprint = release.source_fingerprint(inputs)
    common = {"server/app.py": inputs["server/app.py"], "server/__main__.py": inputs["server/__main__.py"],
              "requirements.txt": inputs["requirements.txt"],
              ".python_packages/lib/site-packages/example.py": b"# dependency\n",
              ".python_packages/lib/site-packages/certifi/cacert.pem": b"public trust roots",
              "release.json": release.json_bytes({"releaseId": RELEASE_ID, "sourceSha256": fingerprint})}
    archives = {}
    for kind, extras in (("web", {"dist/index.html": b"<html></html>"}),
                         ("functions", {"function_app.py": inputs["function_app.py"], "host.json": b"{}"})):
        archives[kind] = release.create_archive(workspace / f"{kind}.zip", {**common, **extras})
    manifest = {"schema": 1, "platform": release.TARGET_PLATFORM, "releaseId": RELEASE_ID,
                "sourceSha256": fingerprint, "sourceFiles": {name: release.sha(data) for name, data in inputs.items()},
                "artifacts": archives}
    path = workspace / "manifest.json"
    path.write_bytes(release.json_bytes(manifest))
    return path


def arguments(package, workspace, command="verify"):
    return SimpleNamespace(command=command, manifest=str(package), subscription=SUBSCRIPTION,
                           resource_group="demo-rg", web_app="demo-web", worker_app=None, ca_file=None,
                           timeout=1, receipt=str(workspace / "receipt.json"), confirm_deploy=True,
                           rollback_receipt=None)


def response(value, status=200, headers=None):
    return status, headers or {}, release.json_bytes(value)


def azure(monkeypatch, http):
    monkeypatch.setattr(release, "azure_token", lambda _: SECRET)
    monkeypatch.setattr(release.uuid, "uuid4", lambda: uuid.UUID(OPERATION_ID))
    args = SimpleNamespace(subscription=SUBSCRIPTION, resource_group="demo-rg", web_app="demo-web", ca_file=None)
    client = release.Azure(args, http)
    client.scm = "https://demo-web.scm.azurewebsites.net"
    client.web = "https://demo-web.azurewebsites.net"
    client.execution = "sync"
    client.identity = {"tenantId": SUBSCRIPTION, "clientId": SUBSCRIPTION, "scope": f"api://{SUBSCRIPTION}/access_as_user"}
    return client


def correlation(package, kind="web"):
    return {"deployer": "release-op-" + OPERATION_ID,
            "message": "release-op-" + OPERATION_ID + ";sha256=" + release.sha((package.parent / f"{kind}.zip").read_bytes())}


def preflight_responses(client, settings=None, site=None, config=None):
    properties = {"reserved": True, "httpsOnly": True, "defaultHostName": "demo-web.azurewebsites.net",
                  "enabledHostNames": ["demo-web.azurewebsites.net", "demo-web.scm.azurewebsites.net"]}
    values = {"COMMVAULT_MODE": "stub", "ENABLE_LIVE_OPERATIONS": "false", "APP_ENV": "production",
              "WEB_CONCURRENCY": "1", "PYTHONPATH": "/home/site/wwwroot/.python_packages/lib/site-packages",
              "SCM_DO_BUILD_DURING_DEPLOYMENT": "false", "ENABLE_ORYX_BUILD": "false",
              "ENTRA_TENANT_ID": SUBSCRIPTION, "ENTRA_API_CLIENT_ID": SUBSCRIPTION, "ENTRA_SPA_CLIENT_ID": SUBSCRIPTION}
    return [response({"id": client.resource_id, "kind": "app,linux", "properties": properties, **(site or {})}),
            response({"properties": {"linuxFxVersion": "PYTHON|3.12", "appCommandLine": "python -m server", **(config or {})}}),
            response({"properties": {**values, **(settings or {})}})]


def clock(monkeypatch):
    current = [0.0]
    monkeypatch.setattr(release.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(release.time, "sleep", lambda seconds: current.__setitem__(0, current[0] + max(seconds, .01)))


def test_fixture_archives_and_traceability(package):
    manifest = release.validate_manifest(package)
    assert manifest["releaseId"] == RELEASE_ID
    with zipfile.ZipFile(package.parent / "web.zip") as archive:
        assert "dist/index.html" in archive.namelist()
        assert "function_app.py" not in archive.namelist()
        assert ".python_packages/lib/site-packages/certifi/cacert.pem" in archive.namelist()


@pytest.mark.parametrize("name", [".env", ".env.production", "infra/terraform.tfstate", "server/test_secret.py",
                                      ".npmrc", "local.settings.json", "tests/test_app.py",
                                      "server/__pycache__/app.pyc", "keys/private.pem", "state/prod.tfvars"])
def test_exclusions(name):
    assert release.excluded(name)


def test_source_only_selection_and_symlink_rejection(workspace):
    for name in release.SOURCE_FILES:
        (workspace / name).write_text("fixture")
    (workspace / "server").mkdir()
    (workspace / "web").mkdir()
    for name in ("app.py", "__main__.py", ".env", "test_example.py"):
        (workspace / "server" / name).write_text("data")
    (workspace / ".env").write_text(SECRET)
    (workspace / "web/main.js").write_text("// fixture")
    selected = release.source_inputs(workspace)
    assert "server/.env" not in selected and ".env" not in selected
    assert "server/test_example.py" not in selected
    (workspace / "server/link.py").symlink_to("app.py")
    with pytest.raises(release.ReleaseError, match="Symlinks"):
        release.source_inputs(workspace)


def test_wrong_platform_rejected_before_build(monkeypatch, workspace):
    monkeypatch.setattr(release.sys, "platform", "darwin")
    invoked = Mock()
    monkeypatch.setattr(release, "run", invoked)
    with pytest.raises(release.ReleaseError, match="Linux"):
        release.build(SimpleNamespace(source=str(workspace), output=str(workspace / "out")))
    invoked.assert_not_called()


def test_build_pipeline_with_offline_fixture_dependencies(monkeypatch, workspace):
    root = workspace / "source"
    root.mkdir()
    for name in release.SOURCE_FILES:
        (root / name).write_text("{}")
    (root / ".npmrc").write_text("registry=https://approved.example/npm/\nstrict-ssl=true\naudit=false\n")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3, "packages": {"": {}}}')
    (root / "requirements.txt").write_text("example==1.0\n")
    (root / "server").mkdir()
    (root / "server/app.py").write_text("# fixture\n")
    (root / "server/__main__.py").write_text("# fixture\n")
    (root / "web").mkdir()
    (root / "web/main.js").write_text("// fixture\n")
    (root / ".env").write_text(SECRET)
    output = workspace / "output"
    calls = []

    def fake_run(command, cwd, env=None):
        calls.append(command)
        assert env["PIP_CONFIG_FILE"] == release.os.devnull
        assert env["PIP_INDEX_URL"] == "https://approved.example/python/simple/"
        assert env["PIP_EXTRA_INDEX_URL"] == env["PIP_TRUSTED_HOST"] == env["PIP_FIND_LINKS"] == ""
        if command[:2] == ["npm", "--ignore-scripts"]:
            (cwd / "dist").mkdir()
            (cwd / "dist/index.html").write_text("<html></html>")
        if "--target" in command:
            packages = Path(command[command.index("--target") + 1])
            packages.mkdir(parents=True)
            (packages / "example.py").write_text("# dependency\n")
        return ""

    monkeypatch.setattr(release, "build_preflight", lambda: None)
    monkeypatch.setattr(release, "run", fake_run)
    monkeypatch.delenv("NPM_CONFIG_USERCONFIG", raising=False)
    monkeypatch.setenv("PACKAGE_FEED_NPM_REGISTRY", "https://approved.example/npm/")
    monkeypatch.setenv("PACKAGE_FEED_NPM_TARBALL_BASE", "https://approved.example/npm/")
    monkeypatch.setenv("PACKAGE_FEED_PYTHON_INDEX", "https://approved.example/python/simple/")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://unapproved.example/simple/")
    monkeypatch.setenv("PIP_FIND_LINKS", "https://unapproved.example/wheels/")
    result = release.build(SimpleNamespace(source=str(root), output=str(output)))
    manifest = release.validate_manifest(output / "manifest.json")
    assert result["built"] is True and result["workerRuntimeVerified"] is False
    assert not (output / "_work").exists()
    assert not any(name.startswith(".env") for name in manifest["sourceFiles"])
    assert any("--no-deps" in call and "--only-binary=:all:" in call for call in calls)
    assert calls[0][:3] == ["npm", "ci", "--include=dev"]


@pytest.mark.parametrize("variable,value", [("NODE_TLS_REJECT_UNAUTHORIZED", "0"),
                                            ("PIP_TRUSTED_HOST", "example.invalid"),
                                            ("PIP_INDEX_URL", "http://example.invalid/simple"),
                                            ("VITE_SECRET", "secret")])
def test_build_rejects_unsafe_environment(monkeypatch, variable, value):
    monkeypatch.setattr(release.sys, "platform", "linux")
    monkeypatch.setattr(release.sys, "version_info", (3, 12))
    monkeypatch.setattr(release.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(release.platform, "libc_ver", lambda: ("glibc", "2.36"))
    for name in ("NODE_TLS_REJECT_UNAUTHORIZED", "PIP_TRUSTED_HOST", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, value)
    with pytest.raises(release.ReleaseError):
        release.build_preflight()


def test_build_reuses_feed_validator_before_staging_or_install(workspace, monkeypatch):
    monkeypatch.setattr(release, "build_preflight", lambda: None)
    monkeypatch.setattr(release, "source_inputs", lambda _: {})
    validator = Mock(side_effect=ValueError("unsafe feed"))
    install = Mock()
    monkeypatch.setattr(release, "check_feeds", validator)
    monkeypatch.setattr(release, "run", install)
    output = workspace / "output"
    with pytest.raises(release.ReleaseError, match="Package feed approval failed"):
        release.build(SimpleNamespace(source=str(workspace), output=str(output)))
    validator.assert_called_once_with(workspace.resolve())
    install.assert_not_called()
    assert not output.exists()


def test_archive_tamper_detected(package):
    with (package.parent / "web.zip").open("ab") as destination:
        destination.write(b"tamper")
    with pytest.raises(release.ReleaseError, match="hash/size"):
        release.validate_manifest(package)


def test_dependency_reuse_requires_exact_hash_and_requirements(package, workspace):
    archive = package.parent / "web.zip"
    digest = release.sha(archive.read_bytes())
    destination = workspace / "reused"
    with pytest.raises(release.ReleaseError, match="SHA-256 mismatch"):
        release.reuse_dependencies(archive, "0" * 64, b"example==1.0\n", destination)
    with pytest.raises(release.ReleaseError, match="byte-for-byte"):
        release.reuse_dependencies(archive, digest, b"example==2.0\n", destination)
    release.reuse_dependencies(archive, digest, b"example==1.0\n", destination)
    assert (destination / ".python_packages/lib/site-packages/example.py").is_file()
    assert not (destination / "server").exists()
    assert not (destination / "release.json").exists()


@pytest.mark.parametrize("entry", ["../escape", "/absolute", "server/.env", "server/link.py"])
def test_archive_unsafe_members_even_after_hash_update(package, entry):
    archive_path = package.parent / "web.zip"
    with zipfile.ZipFile(archive_path, "a") as archive:
        info = zipfile.ZipInfo(entry)
        if entry.endswith("link.py"):
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "secret")
    manifest = release.read_json(package)
    manifest["artifacts"]["web"].update(sha256=release.sha(archive_path.read_bytes()), bytes=archive_path.stat().st_size)
    package.write_bytes(release.json_bytes(manifest))
    with pytest.raises(release.ReleaseError):
        release.validate_manifest(package)


def test_source_hash_tamper(package):
    manifest = release.read_json(package)
    manifest["sourceSha256"] = "f" * 64
    package.write_bytes(release.json_bytes(manifest))
    with pytest.raises(release.ReleaseError, match="fingerprint"):
        release.validate_manifest(package)


@pytest.mark.parametrize("setting", [{"COMMVAULT_MODE": "live"}, {"ENABLE_LIVE_OPERATIONS": "true"},
                                     {"COMMVAULT_MODE": None}, {"ENABLE_ORYX_BUILD": "true"},
                                     {"WEB_CONCURRENCY": "2"}, {"ENTRA_TENANT_ID": ""}])
def test_preflight_fails_closed_for_unsafe_configuration(monkeypatch, setting):
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.side_effect = preflight_responses(client, settings=setting)
    with pytest.raises(release.ReleaseError):
        client.preflight()
    assert not any("zipdeploy" in call.args[1] or "/restart" in call.args[1] for call in http.request.call_args_list)


@pytest.mark.parametrize("site", [{"id": "/subscriptions/wrong/resource"},
                                  {"kind": "functionapp,linux"}, {"properties": {"reserved": False}}])
def test_wrong_target_rejected(monkeypatch, site):
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.side_effect = preflight_responses(client, site=site)
    with pytest.raises(release.ReleaseError):
        client.preflight()
    assert http.request.call_count == 1


def test_preflight_read_only(monkeypatch):
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.side_effect = preflight_responses(client)
    client.preflight()
    assert [call.args[0] for call in http.request.call_args_list] == ["GET", "GET", "POST"]
    assert http.request.call_args_list[-1].args[1].endswith("/config/appsettings/list?api-version=" + release.API)


def test_exact_deployment_poll_then_restart(monkeypatch, package):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.side_effect = [
        response({}, 202, {"Location": client.scm + "/api/deployments/exact-123"}),
        response({"id": "exact-123", "status": 1, "complete": False, **correlation(package)}),
        response({"id": "exact-123", "status": 4, "complete": True, **correlation(package)}), response({}, 200),
    ]
    archive = package.parent / "web.zip"
    assert client.deploy(archive, 10, release.sha(archive.read_bytes())) == "exact-123"
    calls = http.request.call_args_list
    assert all("/api/deployments/exact-123" in call.args[1] for call in calls[1:3])
    assert "/restart?" in calls[-1].args[1]
    assert sum(call.args[0] == "POST" and "zipdeploy" in call.args[1] for call in calls) == 1


@pytest.mark.parametrize("location", ["", "https://evil.example/api/deployments/id",
                                       "https://demo-web.scm.azurewebsites.net:444/api/deployments/id",
                                       "https://user@demo-web.scm.azurewebsites.net/api/deployments/id",
                                       "https://demo-web.scm.azurewebsites.net:bad/api/deployments/id",
                                       "/api/deployments/latest?token=secret", "/api/deployments/id?token=secret"])
def test_untrusted_deployment_location_not_followed(monkeypatch, package, location):
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.return_value = response({}, 202, {"Location": location})
    with pytest.raises(release.ReleaseError, match="uncertain"):
        archive = package.parent / "web.zip"
        client.deploy(archive, 1, release.sha(archive.read_bytes()))
    assert http.request.call_count == 1


@pytest.mark.parametrize("status", [{"id": "wrong", "status": 4, "complete": True},
                                    {"id": "id", "status": 3, "complete": True},
                                    {"id": "id", "status": 1, "complete": False}])
def test_poll_errors_bounded_and_never_restart_or_resubmit(monkeypatch, package, status):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.side_effect = [response({}, 202, {"Location": "/api/deployments/id"}),
                                response({**status, **correlation(package)})]
    with pytest.raises(release.ReleaseError):
        archive = package.parent / "web.zip"
        client.deploy(archive, 1, release.sha(archive.read_bytes()))
    assert http.request.call_count == 2


@pytest.mark.parametrize("prefix", ["", "https://demo-web.scm.azurewebsites.net:443"])
def test_latest_location_discovers_only_correlated_operation(monkeypatch, package, prefix):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    exact = {"id": "ours", "status": 4, "complete": True, **correlation(package)}
    competitors = [
        {"id": "newest-other", "status": 4, "complete": True, "deployer": "another-operation", "message": exact["message"]},
        {"id": "same-deployer-wrong-message", "deployer": exact["deployer"], "message": "different-artifact"},
    ]
    http.request.side_effect = [
        response({}, 202, {"Location": prefix + "/api/deployments/latest?deployer=Push-Deployer&time=2026-09-28_19-44-16Z"}),
        response(competitors), response([*competitors, exact]), response(exact), response({}, 200),
    ]
    archive = package.parent / "web.zip"
    assert client.deploy(archive, 10, release.sha(archive.read_bytes())) == "ours"
    calls = http.request.call_args_list
    query = release.urllib.parse.parse_qs(release.urllib.parse.urlsplit(calls[0].args[1]).query)
    assert query["deployer"] == [exact["deployer"]] and query["message"] == [exact["message"]]
    assert all("latest" not in call.args[1] for call in calls)
    assert [call.args[1].split(client.scm)[-1] for call in calls[1:4]] == [
        "/api/deployments", "/api/deployments", "/api/deployments/ours"]
    assert sum(call.args[0] == "POST" and "zipdeploy" in call.args[1] for call in calls) == 1
    assert "/restart?" in calls[-1].args[1]


@pytest.mark.parametrize("case", ["ambiguous", "unmatched", "changed-correlation", "unsafe-id"])
def test_deployment_discovery_never_guesses_or_reuploads(monkeypatch, package, case):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    matching = {"id": "ours", "status": 4, "complete": True, **correlation(package)}
    if case == "ambiguous":
        discovered = [matching, {**matching, "id": "another-match"}]
    elif case == "unmatched":
        discovered = [{**matching, "deployer": "previous-operation"}]
    elif case == "unsafe-id":
        discovered = [{**matching, "id": "../escape"}]
    else:
        discovered = [matching]
    http.request.side_effect = [
        response({}, 202, {"Location": "/api/deployments/latest"}),
        response(discovered),
        response({**matching, "message": "changed-metadata"}),
    ]
    archive = package.parent / "web.zip"
    with pytest.raises(release.ReleaseError):
        client.deploy(archive, 1, release.sha(archive.read_bytes()))
    calls = http.request.call_args_list
    assert sum(call.args[0] == "POST" for call in calls) == 1
    assert all("latest" not in call.args[1] and "/restart?" not in call.args[1] for call in calls)


def test_stale_runtime_200_never_counts_as_ready(monkeypatch):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    http.request.return_value = response({"releaseId": "old", "mode": "stub"})
    with pytest.raises(release.ReleaseError, match="readiness deadline"):
        client.verify(RELEASE_ID, 1, {"/": b"<html></html>"})
    assert http.request.call_count == 1


def test_mutated_archive_never_submitted(monkeypatch, package):
    http = Mock()
    client = azure(monkeypatch, http)
    with pytest.raises(release.ReleaseError, match="changed after validation"):
        client.deploy(package.parent / "web.zip", 1, "0" * 64)
    http.request.assert_not_called()


def test_current_release_demo_identity_and_anonymous_denial(monkeypatch):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    config = {"releaseId": RELEASE_ID, "mode": "stub", "liveOperationsEnabled": False,
              "identityConfigured": True, "executionMode": "sync", **client.identity}
    assets = {"/": b"<html></html>", "/assets/app.js": b"console.log('demo')"}
    http.request.side_effect = [
        response(config), response({"status": "ok"}), response({}, 401),
        (200, {}, assets["/"]), (200, {}, assets["/assets/app.js"]),
    ]
    client.verify(RELEASE_ID, 1, assets)
    assert http.request.call_count == 5


@pytest.mark.parametrize("status,body", [(200, b"stale"), (404, b"")])
def test_stale_or_missing_frontend_cannot_emit_readiness(monkeypatch, status, body):
    clock(monkeypatch)
    http = Mock()
    client = azure(monkeypatch, http)
    config = {"releaseId": RELEASE_ID, "mode": "stub", "liveOperationsEnabled": False,
              "identityConfigured": True, "executionMode": "sync", **client.identity}
    http.request.side_effect = [
        response(config), response({"status": "ok"}), response({}, 401), (status, {}, body),
    ]
    with pytest.raises(release.ReleaseError, match="HTML/assets differ"):
        client.verify(RELEASE_ID, 1, {"/": b"<html></html>"})
    assert http.request.call_count == 4


def test_packaged_assets_are_the_verification_source(package):
    manifest = release.validate_manifest(package)
    assert release.web_assets(package, manifest) == {"/": b"<html></html>"}


@pytest.mark.parametrize("extra", [0, 1])
def test_asset_size_limit_is_enforced_before_network(package, extra):
    manifest = release.read_json(package)
    with zipfile.ZipFile(package.parent / "web.zip", "a") as archive:
        archive.writestr("dist/assets/large.js", b"x" * (release.MAX_RESPONSE_BYTES + extra))
    if extra:
        with pytest.raises(release.ReleaseError, match="4 MiB"):
            release.web_assets(package, manifest)
    else:
        assert len(release.web_assets(package, manifest)["/assets/large.js"]) == release.MAX_RESPONSE_BYTES


def test_http_never_accepts_a_truncated_response():
    http = release.Http()
    http.opener = Mock()
    read = Mock(return_value=b"x" * (release.MAX_RESPONSE_BYTES + 1))
    http.opener.open.return_value = nullcontext(SimpleNamespace(status=200, headers={}, read=read))
    with pytest.raises(release.ReleaseError, match="response exceeds"):
        http.request("GET", "https://example.invalid")
    read.assert_called_once_with(release.MAX_RESPONSE_BYTES + 1)


def test_worker_rejected_without_token_or_network(package, workspace, monkeypatch):
    token = Mock()
    monkeypatch.setattr(release, "azure_token", token)
    args = arguments(package, workspace, "deploy")
    args.worker_app = "demo-worker"
    with pytest.raises(release.ReleaseError, match="unsupported"):
        release.operate(args)
    token.assert_not_called()


def test_confirmation_required_without_token(package, workspace, monkeypatch):
    token = Mock()
    monkeypatch.setattr(release, "azure_token", token)
    args = arguments(package, workspace, "deploy")
    args.confirm_deploy = False
    with pytest.raises(release.ReleaseError, match="confirm"):
        release.operate(args)
    token.assert_not_called()


def test_verified_receipt_and_rollback_target_binding(package, workspace, monkeypatch):
    client = Mock(execution="sync")
    client.deploy.return_value = "exact-id"
    factory = Mock(return_value=client)
    monkeypatch.setattr(release, "Azure", factory)
    args = arguments(package, workspace)
    receipt = release.operate(args)
    assert receipt["webRuntimeVerified"] is True and receipt["workerRuntimeVerified"] is False
    client.deploy.assert_not_called()
    previous = args.receipt
    args.command, args.rollback_receipt = "deploy", previous
    args.receipt = str(workspace / "rollback.json")
    release.operate(args)
    client.deploy.assert_called_once()
    args.web_app = "other-target"
    args.receipt = str(workspace / "wrong.json")
    with pytest.raises(release.ReleaseError, match="Rollback"):
        release.operate(args)
    assert factory.call_count == 2


def test_failed_runtime_does_not_emit_receipt(package, workspace, monkeypatch):
    client = Mock()
    client.verify.side_effect = release.ReleaseError("not ready")
    monkeypatch.setattr(release, "Azure", Mock(return_value=client))
    args = arguments(package, workspace)
    with pytest.raises(release.ReleaseError):
        release.operate(args)
    assert not Path(args.receipt).exists()


def test_http_tls_no_redirect_and_secret_safe_errors(monkeypatch):
    context = ssl.create_default_context()
    create = Mock(return_value=context)
    monkeypatch.setattr(release.ssl, "create_default_context", create)
    http = release.Http("trusted-ca.pem")
    create.assert_called_once_with(cafile="trusted-ca.pem")
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    http.opener = Mock()
    http.opener.open.side_effect = urllib.error.HTTPError("https://example.invalid", 403, SECRET, {}, None)
    assert http.request("GET", "https://example.invalid") == (403, {}, b"")
    assert release.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid") is None
    with pytest.raises(release.ReleaseError, match="HTTPS"):
        http.request("GET", "http://example.invalid")
    http.opener.open.side_effect = urllib.error.URLError(SECRET)
    with pytest.raises(release.ReleaseError) as error:
        http.request("GET", "https://example.invalid")
    assert SECRET not in str(error.value)


def test_subprocess_failure_and_cli_never_print_secrets(monkeypatch, capsys):
    monkeypatch.setattr(release.subprocess, "run",
                        Mock(side_effect=subprocess.CalledProcessError(1, ["az"], output=SECRET, stderr=SECRET)))
    with pytest.raises(release.ReleaseError) as error:
        release.run(["az"], release.ROOT)
    assert SECRET not in str(error.value)
    monkeypatch.setattr(release, "build", Mock(side_effect=ValueError(SECRET)))
    assert release.main(["build", "--output", "ignored"]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def test_token_subscription_checked(monkeypatch):
    monkeypatch.setattr(release, "run", Mock(return_value=json.dumps({"id": "other-subscription", "accessToken": SECRET})))
    with pytest.raises(release.ReleaseError, match="subscription mismatch"):
        release.azure_token(SUBSCRIPTION)


def test_output_paths_cannot_escape_or_follow_symlink(workspace):
    with pytest.raises(release.ReleaseError):
        release.output_path("../outside")
    with pytest.raises(release.ReleaseError):
        release.output_path("/absolute")
    (workspace / "link").symlink_to(workspace.resolve(), target_is_directory=True)
    with pytest.raises(release.ReleaseError):
        release.output_path(str(workspace / "link/receipt.json"))


@pytest.mark.parametrize("scenario", ["success", "stale", "file-mismatch", "wrong-target"])
def test_worker_helper_offline(package, workspace, monkeypatch, capsys, scenario):
    from scripts import release_worker
    receipt = workspace / "worker-receipt.json"
    for name, value in {
        "SUBSCRIPTION_ID": SUBSCRIPTION, "RESOURCE_GROUP": "demo-rg", "WORKER_APP": "demo-worker",
        "RELEASE_MANIFEST": str(package), "WORKER_RECEIPT": str(receipt),
        "WORKER_CONFIRM_TARGET": f"{SUBSCRIPTION}/demo-rg/demo-worker",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("RELEASE_CA_FILE", raising=False)
    monkeypatch.setattr(release, "azure_token", lambda _: SECRET)
    monkeypatch.setattr(release.uuid, "uuid4", lambda: uuid.UUID(OPERATION_ID))
    current_time = [0.0]
    monkeypatch.setattr(release.time, "monotonic", lambda: current_time[0])
    monkeypatch.setattr(release.time, "sleep", lambda _: current_time.__setitem__(0, current_time[0] + 600))
    resource_id = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/demo-rg/providers/Microsoft.Web/sites/demo-worker"
    baseline = {"id": "host-id", "instanceId": "old-instance", "state": "Running", "processUptime": 100000}
    current = {"id": "host-id", "instanceId": "new-instance", "state": "Running", "processUptime": 0}
    if scenario == "stale":
        current = baseline
    responses = [
        response({"id": resource_id if scenario != "wrong-target" else "/wrong/target", "kind": "functionapp,linux",
                  "properties": {"reserved": True, "httpsOnly": True, "defaultHostName": "demo-worker.azurewebsites.net",
                                 "enabledHostNames": ["demo-worker.scm.azurewebsites.net"]}}),
        response({"properties": {"linuxFxVersion": "PYTHON|3.12"}}),
        response({"properties": {
            "APP_ENV": "production", "COMMVAULT_MODE": "stub", "ENABLE_LIVE_OPERATIONS": "false",
            "EXECUTION_MODE": "queued", "FUNCTIONS_WORKER_RUNTIME": "python", "FUNCTIONS_EXTENSION_VERSION": "~4",
            "SCM_DO_BUILD_DURING_DEPLOYMENT": "false", "ENABLE_ORYX_BUILD": "false",
        }}),
        response({"masterKey": SECRET}),
        response(baseline),
        response({}, 202, {"Location": "/api/deployments/worker-exact"}),
        response({"id": "worker-exact", "status": 4, "complete": True, **correlation(package, "functions")}),
        response({}, 200),
        response(current),
        response([{"name": name} for name in ("inventory_refresh", "request_worker", "request_poison")]),
        response(current),
    ]
    requests = Mock(side_effect=responses)
    monkeypatch.setattr(release.Http, "request", requests)
    downloaded = (package.parent / ("web.zip" if scenario == "file-mismatch" else "functions.zip")).read_bytes()
    opener = Mock()
    opener.open.return_value = nullcontext(SimpleNamespace(status=200, read=lambda _: downloaded))
    monkeypatch.setattr(release.Http, "__init__", lambda self, ca_file=None: setattr(self, "opener", opener))
    if scenario == "success":
        assert release_worker.main(["--confirm-deploy"]) == 0
        proof = release.read_json(receipt)
        assert proof["workerFilesAndFreshHostVerified"] is True
        assert proof["queueCompletionVerified"] is proof["apiUserSignInVerified"] is False
        assert proof["workerRuntimeReleaseMarkerVerified"] is False
        assert proof["deploymentId"] == "worker-exact"
        assert requests.call_count == 11 and opener.open.call_count == 1
    else:
        assert release_worker.main(["--confirm-deploy"]) == 1
        assert not receipt.exists()
    if scenario == "wrong-target":
        assert requests.call_count == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


@pytest.mark.parametrize("arguments,exit_code", [([], 2), (["--help"], 0)])
def test_worker_cli_requires_explicit_mutation_and_help_is_read_only(monkeypatch, arguments, exit_code):
    from scripts import release_worker
    deploy = Mock()
    monkeypatch.setattr(release_worker, "worker_release", deploy)
    with pytest.raises(SystemExit) as error:
        release_worker.main(arguments)
    assert error.value.code == exit_code
    deploy.assert_not_called()

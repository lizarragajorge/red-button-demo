#!/usr/bin/env python3
"""Source-only release tools. No Azure operation occurs unless a subcommand requests it."""

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

if __package__:
    from .configure_feeds import check as check_feeds
else:
    from configure_feeds import check as check_feeds

ARM = "https://management.azure.com"
API = "2024-11-01"
TARGET_PLATFORM = "linux-x86_64-cpython-3.12"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
SKIP = {"__pycache__", "tests", "test", ".git", "node_modules", ".venv", "infra",
        ".azure", ".ssh", ".terraform", ".kube"}
SOURCE_FILES = ("requirements.txt", "package.json", "package-lock.json", ".npmrc",
                "index.html", "vite.config.js", "function_app.py", "host.json")
HEX = re.compile(r"[0-9a-f]{64}")


class ReleaseError(Exception):
    """An operator-safe error: never include service bodies or credentials."""


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def read_json(path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise ReleaseError("Cannot read a required JSON file.") from None


def canonical_uuid(value):
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def excluded(name):
    if name == ".python_packages/lib/site-packages/certifi/cacert.pem":
        return False  # Public trust roots are runtime data, not deployment credentials.
    parts = PurePosixPath(name).parts
    return (
        any(p in SKIP or p.startswith(".env") for p in parts)
        or any(p.startswith(("test_", "terraform.tfstate")) or p.endswith(
            (".tf", ".tfvars", ".tfvars.json", ".tfstate", ".tfstate.backup", ".pem", ".key", ".pfx", ".p12", ".pyc"))
               for p in parts)
        or parts[-1] in {"local.settings.json", ".npmrc", ".netrc", "id_rsa", "id_ed25519", "credentials"}
    )


def tree_files(directory):
    require(directory.is_dir() and not directory.is_symlink(), "Expected a real source directory.")
    files = []
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Symlinks are forbidden in release inputs.")
        require(path.is_file() or path.is_dir(), "Special files are forbidden in release inputs.")
        if path.is_file():
            files.append(path)
    return files


def source_inputs(root):
    result = {}
    for name in SOURCE_FILES:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "Missing or symlinked source input.")
        result[name] = path.read_bytes()
    for directory in ("server", "web"):
        for path in tree_files(root / directory):
            name = path.relative_to(root).as_posix()
            if not excluded(name) and (directory != "server" or path.suffix == ".py"):
                result[name] = path.read_bytes()
    require("server/app.py" in result and "server/__main__.py" in result, "Missing server entry point.")
    return result


def source_fingerprint(inputs):
    return sha(json_bytes({name: sha(data) for name, data in sorted(inputs.items())}))


def run(command, cwd, env=None):
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True,
                              text=True, timeout=1800).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise ReleaseError("Local command failed; output suppressed to protect credentials.") from None


def build_preflight():
    require(sys.platform == "linux" and platform.machine() == "x86_64"
            and sys.version_info[:2] == (3, 12) and platform.libc_ver()[0] == "glibc",
            "Build requires glibc Linux x86_64 CPython 3.12; cross-host native packaging is forbidden.")
    require(os.environ.get("NODE_TLS_REJECT_UNAUTHORIZED") != "0", "TLS verification must remain enabled.")
    require(not os.environ.get("PIP_TRUSTED_HOST"), "PIP_TRUSTED_HOST disables TLS verification and is forbidden.")
    for name in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
        for value in os.environ.get(name, "").split():
            require(urllib.parse.urlsplit(value).scheme == "https", "Python indexes must use HTTPS.")
    require(not any(k.startswith("VITE_") for k in os.environ), "Unset VITE_* environment inputs before building.")


def create_archive(path, entries):
    require(not path.exists(), "Refusing to overwrite an existing archive.")
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            require(not excluded(name), "Forbidden file in release archive.")
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    return {"file": path.name, "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}


def output_path(value):
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts, "Output paths must be relative to the working directory.")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Output paths cannot traverse symlinks.")
    return path


def reuse_dependencies(archive_path, expected_hash, requirements, destination):
    require(isinstance(expected_hash, str) and HEX.fullmatch(expected_hash), "Dependency reuse requires a trusted SHA-256.")
    require(archive_path.is_file() and not archive_path.is_symlink(), "Dependency archive must be a regular file.")
    data = archive_path.read_bytes()
    require(sha(data) == expected_hash, "Dependency archive SHA-256 mismatch.")
    prefix = ".python_packages/lib/site-packages/"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(archive.read("requirements.txt") == requirements, "Reused dependency requirements must match byte-for-byte.")
        require(len(archive.namelist()) == len(set(archive.namelist())), "Duplicate dependency archive entries.")
        count = 0
        for info in archive.infolist():
            name = info.filename
            require(not name.startswith("/") and "\\" not in name and ".." not in PurePosixPath(name).parts
                    and not stat.S_ISLNK(info.external_attr >> 16), "Unsafe dependency archive entry.")
            if name.startswith(prefix) and not info.is_dir() and not excluded(name):
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(info))
                count += 1
        require(count > 0, "Dependency archive contains no runtime packages.")


def build(args):
    build_preflight()
    root = Path(args.source).resolve()
    inputs = source_inputs(root)
    try:
        registry, python_index = check_feeds(root)
    except (ValueError, OSError):
        raise ReleaseError("Package feed approval failed; run scripts/configure_feeds.py check.") from None
    prebuilt_dist = getattr(args, "prebuilt_dist", None)
    dependency_archive = getattr(args, "dependency_archive", None)
    dependency_hash = getattr(args, "dependency_sha256", None)
    require(bool(dependency_archive) == bool(dependency_hash),
            "Supply both --dependency-archive and --dependency-sha256, or neither.")
    requirements = inputs["requirements.txt"].decode().splitlines()
    require(requirements and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line)
                                 for line in requirements if line.strip()),
            "Production requirements must contain only exact package==version pins.")
    output = output_path(args.output)
    require(not output.exists(), "Choose a new release output directory.")
    output.mkdir(parents=True)
    work = output / "_work"
    work.mkdir()
    frontend, bundle = work / "frontend", work / "bundle"
    frontend.mkdir()
    bundle.mkdir()
    try:
        for name, data in inputs.items():
            if name.startswith("web/") or name in {"package.json", "package-lock.json", ".npmrc", "index.html", "vite.config.js"}:
                path = frontend / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            elif name.startswith("server/") or name in {"requirements.txt", "function_app.py", "host.json"}:
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        env = {**os.environ, "TMPDIR": str(work.resolve()), "PYTHONDONTWRITEBYTECODE": "1",
               "PIP_CONFIG_FILE": os.devnull, "PIP_NO_INPUT": "1",
               "PIP_INDEX_URL": python_index, "PIP_EXTRA_INDEX_URL": "", "PIP_TRUSTED_HOST": "",
               "PIP_FIND_LINKS": "", "PIP_NO_INDEX": "",
               "NPM_CONFIG_REGISTRY": registry, "NPM_CONFIG_STRICT_SSL": "true",
               "NPM_CONFIG_AUDIT": "false", "NPM_CONFIG_FUND": "false", "NPM_CONFIG_IGNORE_SCRIPTS": "true"}
        userconfig = env.get("NPM_CONFIG_USERCONFIG")
        if userconfig:
            config = Path(userconfig).resolve()
            require(not config.is_relative_to(root) and not config.is_relative_to(output.resolve()),
                    "Authenticated npm user configuration must remain outside source and staging.")
        if prebuilt_dist:
            (frontend / "dist").mkdir()
            for path in tree_files(Path(prebuilt_dist)):
                name = path.relative_to(prebuilt_dist).as_posix()
                if not excluded(name):
                    target = frontend / "dist" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
        else:
            run(["npm", "ci", "--include=dev", "--registry", registry, "--strict-ssl=true",
                 "--ignore-scripts", "--audit=false", "--fund=false"], frontend, env)
            run(["npm", "--ignore-scripts", "run", "build"], frontend, env)
        require((frontend / "dist/index.html").is_file(), "Frontend build did not produce index.html.")
        packages = bundle / ".python_packages/lib/site-packages"
        tools = work / "python-tools"
        run([sys.executable, "-m", "venv", "--without-pip", str(tools.resolve())], root, env)
        python = str((tools / "bin/python").absolute())
        if dependency_archive:
            reuse_dependencies(Path(dependency_archive), dependency_hash, inputs["requirements.txt"], bundle)
        else:
            run([python, "-m", "ensurepip"], root, env)
            run([python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                 "--no-compile", "--no-deps", "--index-url", python_index, "--target", str(packages.resolve()),
                 "-r", str((bundle / "requirements.txt").resolve())], root, env)
        check_env = {**env, "PYTHONPATH": str(packages.resolve()), "APP_ENV": "test",
                     "COMMVAULT_MODE": "stub", "ENABLE_LIVE_OPERATIONS": "false"}
        if dependency_archive:
            # Use the builder's pip to inspect the isolated venv, without installing pip into it.
            run([sys.executable, "-m", "pip", "--python", python, "check"], bundle, check_env)
        else:
            run([python, "-m", "pip", "check"], bundle, check_env)
        run([python, "-c",
             "import importlib.metadata as m, pathlib, re; "
             "normalize=lambda n: re.sub(r'[-_.]+','-',n).lower(); "
             "expected={normalize(n):v for line in pathlib.Path('requirements.txt').read_text().splitlines() "
             "if line.strip() for n,v in [line.split('==')]}; "
             "actual={normalize(d.metadata['Name']):d.version for d in m.distributions(path=["
             "'.python_packages/lib/site-packages'])}; "
             "assert expected == actual, 'Installed distributions differ from exact requirements'"], bundle, check_env)
        run([python, "-c", "import fastapi, uvicorn, httpx, jwt, dotenv, pydantic_core, aiohttp; "
             "from cryptography.hazmat.bindings import _rust; "
             "import azure.functions, azure.identity.aio, azure.storage.blob.aio, azure.storage.queue.aio; "
             "import server.app, function_app; "
             "assert {f.get_function_name() for f in function_app.app.get_functions()} == "
             "{'inventory_refresh', 'request_worker', 'request_poison'}"], bundle, check_env)
        release_id = str(uuid.uuid4())
        fingerprint = source_fingerprint(inputs)
        marker = json_bytes({"releaseId": release_id, "sourceSha256": fingerprint})
        common = {"release.json": marker}
        for path in tree_files(bundle):
            name = path.relative_to(bundle).as_posix()
            if not excluded(name):
                common[name] = path.read_bytes()
        web = {name: data for name, data in common.items() if name not in {"function_app.py", "host.json"}}
        for path in tree_files(frontend / "dist"):
            name = "dist/" + path.relative_to(frontend / "dist").as_posix()
            if not excluded(name):
                web[name] = path.read_bytes()
        artifacts = {kind: create_archive(output / f"{kind}.zip", entries)
                     for kind, entries in (("web", web), ("functions", common))}
        require(source_fingerprint(source_inputs(root)) == fingerprint, "Source changed during the build; discard this output.")
        manifest = {"schema": 1, "releaseId": release_id, "sourceSha256": fingerprint,
                    "sourceFiles": {name: sha(data) for name, data in sorted(inputs.items())},
                    "createdUtc": datetime.now(UTC).isoformat(), "platform": TARGET_PLATFORM,
                    "artifacts": artifacts,
                    "buildInputs": {
                        "frontend": {"mode": "prebuilt-dist" if prebuilt_dist else "npm-ci",
                                     "files": {name: sha(data) for name, data in web.items() if name.startswith("dist/")}},
                        "pythonDependencies": {"mode": "verified-archive" if dependency_archive else "pinned-wheels",
                                               **({"archiveSha256": dependency_hash} if dependency_archive else {})},
                    }}
        (output / "manifest.json").write_bytes(json_bytes(manifest))
        validate_manifest(output / "manifest.json")
        return {"built": True, "releaseId": release_id, "manifest": str(output / "manifest.json"),
                "workerRuntimeVerified": False}
    finally:
        shutil.rmtree(work)


def validate_manifest(path):
    require(path.is_file() and not path.is_symlink(), "Manifest must be a regular file.")
    manifest = read_json(path)
    try:
        require(manifest["schema"] == 1 and manifest["platform"] == TARGET_PLATFORM,
                "Unsupported release schema or platform.")
        require(canonical_uuid(manifest["releaseId"]) and HEX.fullmatch(manifest["sourceSha256"]),
                "Invalid release identity.")
        files = manifest["sourceFiles"]
        require(isinstance(files, dict) and files and all(isinstance(k, str) and isinstance(v, str)
                and HEX.fullmatch(v) for k, v in files.items()), "Invalid source traceability.")
        require(sha(json_bytes(files)) == manifest["sourceSha256"], "Source fingerprint mismatch.")
        require(set(manifest["artifacts"]) == {"web", "functions"}, "Both release archives are required.")
        marker = {"releaseId": manifest["releaseId"], "sourceSha256": manifest["sourceSha256"]}
        for kind, item in manifest["artifacts"].items():
            require(item["file"] == f"{kind}.zip", "Archive name must be local and match its role.")
            archive_path = path.parent / item["file"]
            require(archive_path.is_file() and not archive_path.is_symlink(), "Missing or symlinked archive.")
            data = archive_path.read_bytes()
            require(sha(data) == item["sha256"] and len(data) == item["bytes"], "Archive hash/size mismatch.")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                require(len(names) == len(set(names)), "Duplicate archive entries.")
                expected = {"server", ".python_packages", "requirements.txt", "release.json"}
                expected |= {"dist"} if kind == "web" else {"function_app.py", "host.json"}
                require({PurePosixPath(n).parts[0] for n in names} == expected, "Wrong archive layout.")
                for info in archive.infolist():
                    name = info.filename
                    parts = PurePosixPath(name).parts
                    require(parts and not name.startswith("/") and "\\" not in name
                            and ".." not in parts and not excluded(name)
                            and not stat.S_ISLNK(info.external_attr >> 16), "Unsafe archive entry.")
                require(archive.testzip() is None, "Archive integrity failure.")
                require(json.loads(archive.read("release.json")) == marker, "Packaged release marker mismatch.")
                for name, digest in files.items():
                    if name.startswith("server/") or name == "requirements.txt" or (kind == "functions" and name in {"function_app.py", "host.json"}):
                        require(sha(archive.read(name)) == digest, "Packaged source differs from the manifest.")
                if kind == "web":
                    require("dist/index.html" in names, "Missing packaged frontend.")
                    frontend = manifest.get("buildInputs", {}).get("frontend")
                    if frontend is not None:
                        require(frontend["files"] == {name: sha(archive.read(name)) for name in names if name.startswith("dist/")},
                                "Packaged frontend differs from recorded build inputs.")
        return manifest
    except (KeyError, TypeError, ValueError, zipfile.BadZipFile, IndexError):
        raise ReleaseError("Malformed release manifest or archive.") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Http:
    def __init__(self, ca_file=None):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)), NoRedirect())

    def request(self, method, url, headers=None, body=None, timeout=30):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password,
                "Only verified HTTPS endpoints are permitted.")
        request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                require(len(data) <= MAX_RESPONSE_BYTES, "HTTPS response exceeds the supported verification limit.")
                return response.status, dict(response.headers), data
        except urllib.error.HTTPError as error:
            # Never read or format remote bodies, reason strings, URLs, or request headers.
            return error.code, {}, b""
        except (OSError, urllib.error.URLError, ValueError):
            raise ReleaseError("HTTPS request failed; credentials and response details suppressed.") from None


def decode_response(response, expected=(200,)):
    status, _, body = response
    require(status in expected, f"Service request failed (HTTP {status}); body suppressed.")
    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        raise ReleaseError("Service returned invalid JSON; body suppressed.") from None


def azure_token(subscription):
    account = json.loads(run(["az", "account", "show", "--subscription", subscription, "-o", "json"], ROOT))
    require(account.get("id", "").lower() == subscription, "Azure CLI subscription mismatch.")
    value = json.loads(run(["az", "account", "get-access-token", "--subscription", subscription,
                           "--resource", ARM + "/", "-o", "json"], ROOT))
    require(value.get("subscription", "").lower() == subscription and value.get("accessToken"),
            "Azure CLI token subscription mismatch.")
    return value["accessToken"]


def target_id(args):
    require(canonical_uuid(args.subscription), "Supply a canonical subscription UUID.")
    require(re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", args.resource_group) and not args.resource_group.endswith("."),
            "Invalid resource group name.")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,58}[A-Za-z0-9]", args.web_app), "Invalid web app name.")
    return f"/subscriptions/{args.subscription}/resourceGroups/{args.resource_group}/providers/Microsoft.Web/sites/{args.web_app}"


class Azure:
    def __init__(self, args, http=None):
        self.resource_id = target_id(args)
        self.http = http or Http(args.ca_file)
        self.token = azure_token(args.subscription)
        self.headers = {"Authorization": "Bearer " + self.token}

    def arm(self, suffix="", method="GET"):
        return self.http.request(method, ARM + self.resource_id + suffix + "?api-version=" + API,
                                 self.headers, b"" if method == "POST" else None)

    def preflight(self):
        site = decode_response(self.arm())
        require(site.get("id", "").lower() == self.resource_id.lower(), "ARM returned the wrong full resource identity.")
        properties = site.get("properties", {})
        require(properties.get("reserved") is True and properties.get("httpsOnly") is True
                and "functionapp" not in site.get("kind", "").lower(), "Target must be an HTTPS Linux web app, not Functions.")
        host = properties.get("defaultHostName", "")
        require(re.fullmatch(r"[a-zA-Z0-9-]+\.azurewebsites\.net", host), "Unsupported App Service hostname/cloud.")
        scm = host.replace(".azurewebsites.net", ".scm.azurewebsites.net")
        require(scm in properties.get("enabledHostNames", []), "SCM hostname is not bound to the requested resource.")
        self.web, self.scm = "https://" + host, "https://" + scm
        config = decode_response(self.arm("/config/web")).get("properties", {})
        require(config.get("linuxFxVersion", "").upper() == "PYTHON|3.12"
                and config.get("appCommandLine") == "python -m server", "Target runtime/startup does not match this package.")
        settings = decode_response(self.arm("/config/appsettings/list", "POST")).get("properties", {})
        require(settings.get("COMMVAULT_MODE") == "stub" and settings.get("ENABLE_LIVE_OPERATIONS") == "false",
                "Demo-only deployment requires explicit stub mode and disabled live operations.")
        require(settings.get("APP_ENV") == "production" and settings.get("WEB_CONCURRENCY") == "1"
                and settings.get("PYTHONPATH") == "/home/site/wwwroot/.python_packages/lib/site-packages",
                "Production single-worker/PYTHONPATH settings do not match this package.")
        require(all(settings.get(key, "").lower() == "false" for key in
                    ("SCM_DO_BUILD_DURING_DEPLOYMENT", "ENABLE_ORYX_BUILD")),
                "Remote builds must be explicitly disabled.")
        require(not settings.get("WEBSITE_RUN_FROM_PACKAGE"), "Run-from-package targets require a different release procedure.")
        require(all(canonical_uuid(settings.get(key)) for key in
                    ("ENTRA_TENANT_ID", "ENTRA_API_CLIENT_ID", "ENTRA_SPA_CLIENT_ID")), "Entra identity must be configured.")
        self.execution = settings.get("EXECUTION_MODE", "sync")
        require(self.execution in {"sync", "queued"}, "Unsupported execution mode.")
        self.identity = {key: settings[name] for key, name in
                         (("tenantId", "ENTRA_TENANT_ID"), ("clientId", "ENTRA_SPA_CLIENT_ID"))}
        self.identity["scope"] = "api://" + settings["ENTRA_API_CLIENT_ID"] + "/access_as_user"

    def deploy(self, archive, timeout, expected_hash):
        data = archive.read_bytes()
        require(sha(data) == expected_hash, "Archive changed after validation; no upload performed.")
        operation_id = str(uuid.uuid4())
        deployer = "release-op-" + operation_id
        message = deployer + ";sha256=" + expected_hash
        query = urllib.parse.urlencode({"isAsync": "true", "deployer": deployer, "message": message,
                                        "trackDeploymentProgress": "true"})
        print(f"Submitting deployment operation: {operation_id}", file=sys.stderr)
        response = self.http.request("POST", self.scm + "/api/zipdeploy?" + query,
                                     {**self.headers, "Content-Type": "application/zip"},
                                     data, timeout=min(timeout, 120))
        require(response[0] == 202, "ZIP submission not acknowledged; outcome uncertain. Do not automatically retry.")
        location = next((value for key, value in response[1].items() if key.lower() == "location"), "")
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(self.scm, location))
        try:
            same_origin = (parsed.scheme == "https"
                           and parsed.hostname == urllib.parse.urlsplit(self.scm).hostname
                           and parsed.port in (None, 443)
                           and parsed.username is None and parsed.password is None)
        except ValueError:
            same_origin = False
        require(same_origin and not parsed.fragment
                and re.fullmatch(r"/api/deployments/[A-Za-z0-9-]{1,128}", parsed.path),
                "Untrusted deployment Location; outcome uncertain. Inspect Azure; do not retry.")
        candidate_id = parsed.path.rsplit("/", 1)[-1]
        require((candidate_id == "latest"
                 and set(urllib.parse.parse_qs(parsed.query)) <= {"deployer", "time"})
                or (candidate_id != "latest" and not parsed.query),
                "Untrusted deployment Location query; outcome uncertain. Do not retry.")
        deadline = time.monotonic() + timeout

        def correlated(item):
            return isinstance(item, dict) and item.get("deployer") == deployer and item.get("message") == message

        deployment_id = None if candidate_id == "latest" else candidate_id
        while deployment_id is None:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Deployment discovery deadline exceeded; outcome uncertain. Do not retry.")
            deployments = decode_response(self.http.request(
                "GET", self.scm + "/api/deployments", self.headers, timeout=min(30, remaining)))
            require(isinstance(deployments, list), "Invalid deployment discovery response; do not retry.")
            matches = [item for item in deployments if correlated(item)]
            require(len(matches) <= 1, "Ambiguous deployment operation metadata; do not retry.")
            if matches:
                deployment_id = matches[0].get("id")
                require(isinstance(deployment_id, str)
                        and re.fullmatch(r"[A-Za-z0-9-]{1,128}", deployment_id) and deployment_id != "latest",
                        "Correlated deployment has no trustworthy exact ID; do not retry.")
            else:
                time.sleep(min(3, max(0, deadline - time.monotonic())))
        print(f"Accepted exact deployment ID: {deployment_id}", file=sys.stderr)
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Deployment polling deadline exceeded; outcome uncertain. Do not retry.")
            status = decode_response(self.http.request("GET", self.scm + "/api/deployments/" + deployment_id, self.headers,
                                                        timeout=min(30, remaining)))
            require(status.get("id") == deployment_id and correlated(status),
                    "Deployment identity/operation metadata mismatch; do not retry.")
            require(status.get("status") != 3, "Exact deployment failed; inspect Azure before any further mutation.")
            if status.get("status") == 4 and status.get("complete") is True:
                break
            require(status.get("status") in {0, 1, 2, 4}, "Unknown deployment status; do not retry.")
            time.sleep(min(3, max(0, deadline - time.monotonic())))
        restart = self.arm("/restart", "POST")
        require(restart[0] in {200, 202, 204}, "Restart acknowledgement failed; outcome uncertain. Do not retry.")
        return deployment_id

    def verify(self, release_id, timeout, assets):
        deadline = time.monotonic() + timeout
        last_error = "Expected release has not been observed."
        while time.monotonic() < deadline:
            try:
                response = self.http.request("GET", self.web + "/api/config",
                                             {"Cache-Control": "no-cache"},
                                             timeout=min(30, max(.1, deadline - time.monotonic())))
                config = decode_response(response)
                ready = (config.get("releaseId") == release_id and config.get("mode") == "stub"
                         and config.get("liveOperationsEnabled") is False and config.get("identityConfigured") is True
                         and config.get("executionMode") == self.execution
                         and all(config.get(key) == value for key, value in self.identity.items()))
                require(ready, "Loaded release, identity, or demo configuration differs.")
                health = decode_response(self.http.request("GET", self.web + "/api/health",
                                         timeout=min(30, max(.1, deadline - time.monotonic()))))
                anonymous = self.http.request("GET", self.web + "/api/me",
                                         timeout=min(30, max(.1, deadline - time.monotonic())))
                require(health == {"status": "ok"} and anonymous[0] == 401,
                        "Health or anonymous-denial check failed.")
                for path, expected in assets.items():
                    require(time.monotonic() < deadline, "Asset verification deadline exceeded.")
                    status, _, body = self.http.request(
                        "GET", self.web + urllib.parse.quote(path, safe="/"),
                        {"Cache-Control": "no-cache"},
                        timeout=min(30, max(.1, deadline - time.monotonic())))
                    require(status == 200 and body == expected, "Served HTML/assets differ from the package.")
                if time.monotonic() < deadline:
                    return
            except ReleaseError as error:
                last_error = str(error)
            time.sleep(min(3, max(0, deadline - time.monotonic())))
        raise ReleaseError("Web readiness deadline exceeded: " + last_error + " Worker not verified.")


def web_assets(manifest_path, manifest):
    with zipfile.ZipFile(manifest_path.parent / manifest["artifacts"]["web"]["file"]) as archive:
        result = {}
        for item in archive.infolist():
            if item.filename == "dist/index.html" or item.filename.startswith("dist/assets/"):
                require(item.file_size <= MAX_RESPONSE_BYTES, "Web asset exceeds the supported 4 MiB verification limit.")
                path = "/" if item.filename == "dist/index.html" else item.filename.removeprefix("dist")
                result[path] = archive.read(item)
    require("/" in result, "Missing web HTML for verification.")
    return result


def operate(args):
    require(args.timeout > 0 and args.timeout <= 3600, "Timeout must be between 1 and 3600 seconds.")
    require(not args.worker_app, "Worker deployment/verification is intentionally unsupported; no Azure operation performed.")
    manifest_path = Path(args.manifest)
    manifest = validate_manifest(manifest_path)
    assets = web_assets(manifest_path, manifest)
    resource = target_id(args)
    receipt_path = output_path(args.receipt)
    require(not receipt_path.exists(), "Use a new verification receipt path.")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "deploy":
        require(args.confirm_deploy, "Mutation requires --confirm-deploy.")
        if args.rollback_receipt:
            previous = read_json(Path(args.rollback_receipt))
            require(previous.get("webRuntimeVerified") is True and previous.get("resourceId", "").lower() == resource.lower()
                    and previous.get("releaseId") == manifest["releaseId"]
                    and previous.get("manifestSha256") == sha(manifest_path.read_bytes()),
                    "Rollback requires a prior verified receipt for this exact target and manifest.")
    azure = Azure(args)
    azure.preflight()
    deployment_id = None
    if args.command == "deploy":
        deployment_id = azure.deploy(manifest_path.parent / manifest["artifacts"]["web"]["file"], args.timeout,
                                     manifest["artifacts"]["web"]["sha256"])
    azure.verify(manifest["releaseId"], args.timeout, assets)
    receipt = {"schema": 1, "resourceId": resource, "releaseId": manifest["releaseId"],
               "manifestSha256": sha(manifest_path.read_bytes()), "deploymentId": deployment_id,
               "verifiedUtc": datetime.now(UTC).isoformat(), "webRuntimeVerified": True,
               "workerRuntimeVerified": False, "executionMode": azure.execution}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("xb") as destination:
        destination.write(json_bytes(receipt))
    return receipt


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    package = sub.add_parser("build", help="Build web and Functions ZIPs on matching Linux; never contacts Azure")
    package.add_argument("--source", default=str(ROOT))
    package.add_argument("--output", required=True)
    package.add_argument("--prebuilt-dist", help="Explicit trusted frontend output; hashes recorded, never silently reused")
    package.add_argument("--dependency-archive", help="Prior trusted Linux ZIP; only runtime dependencies are reused")
    package.add_argument("--dependency-sha256", help="Expected dependency archive hash from a retained trusted manifest")
    for command in ("deploy", "verify"):
        child = sub.add_parser(command, help="Demo-only web deployment/readiness; worker is not verified")
        child.add_argument("--manifest", required=True)
        child.add_argument("--subscription", required=True)
        child.add_argument("--resource-group", required=True)
        child.add_argument("--web-app", required=True)
        child.add_argument("--worker-app", help="Reserved; explicitly rejected without contacting Azure")
        child.add_argument("--timeout", type=int, default=600)
        child.add_argument("--ca-file", help="Trusted CA bundle; TLS verification always enabled")
        child.add_argument("--receipt", required=True, help="New relative output JSON path")
        if command == "deploy":
            child.add_argument("--confirm-deploy", action="store_true")
            child.add_argument("--rollback-receipt", help="Prior verified receipt for the exact package and target")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        value = build(args) if args.command == "build" else operate(args)
        print(json.dumps(value, sort_keys=True))
        return 0
    except (ReleaseError, OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as error:
        # Exception strings from filesystem, subprocess, HTTP and Azure are not safe to print.
        print(str(error) if isinstance(error, ReleaseError) else
              f"Release operation failed ({type(error).__name__}); sensitive details suppressed.",
              file=sys.stderr)
        if args.command == "deploy":
            print("If submission began, its outcome may be uncertain. Inspect the exact deployment before further mutation.",
                  file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

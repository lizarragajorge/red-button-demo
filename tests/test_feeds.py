import copy
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from scripts import configure_feeds as feeds

REGISTRY = "https://packages.example.invalid/npm/"
TARBALLS = "https://cdn.example.invalid/npm/"
PYTHON_INDEX = "https://packages.example.invalid/python/simple/"


@pytest.fixture
def workspace():
    # Keep fixture files inside the project, not the system temporary directory.
    path = feeds.ROOT / f".feed-test-{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.fixture
def source(workspace):
    root = workspace / "source"
    root.mkdir()
    (root / ".npmrc").write_text(feeds.npmrc_text(feeds.INTERNAL_NPM))
    packages = {"": {"name": "fixture", "version": "1.0.0"}}
    for name, base in zip(("plain", "@scope/scoped"), feeds.INTERNAL_TARBALLS):
        packages[f"node_modules/{name}"] = {
            "version": "1.2.3", "integrity": "sha512-YWJjZA==",
            "resolved": f"{base}{name}/-/{name.rsplit('/', 1)[-1]}-1.2.3.tgz",
            "optional": True, "dependencies": {"child": "^2.0.0"},
        }
    (root / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": packages}))
    return root


def approved_env():
    return {
        "PACKAGE_FEED_NPM_REGISTRY": REGISTRY,
        "PACKAGE_FEED_NPM_TARBALL_BASE": TARBALLS,
        "PACKAGE_FEED_PYTHON_INDEX": PYTHON_INDEX,
    }


def export(source, output, **overrides):
    args = {
        "registry": REGISTRY, "tarball_base": TARBALLS,
        "approved": True, "confirm_mirror_layout": True,
        **overrides,
    }
    feeds.prepare(source, output, **args)


def test_actual_checkout_matches_explicit_selected_feeds():
    feeds.check()


def test_internal_default_accepts_both_known_layouts(source):
    assert feeds.check(source, {}) == (feeds.INTERNAL_NPM, feeds.INTERNAL_PYTHON)


def test_export_preserves_everything_except_verified_resolved_urls(source, workspace):
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    output = workspace / "export"
    export(source, output)
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    original = json.loads(before["package-lock.json"])
    rewritten = feeds.read_lock(output / "package-lock.json")
    for path, package in rewritten["packages"].items():
        if path:
            assert package["resolved"] == TARBALLS + feeds.tarball_suffix(path, package)
            package["resolved"] = original["packages"][path]["resolved"]
    assert rewritten == original
    assert feeds.check(output, approved_env()) == (REGISTRY, PYTHON_INDEX)
    second = workspace / "second"
    export(source, second)
    assert (output / "package-lock.json").read_bytes() == (second / "package-lock.json").read_bytes()
    assert set(p.name for p in output.iterdir()) == {".npmrc", "package-lock.json"}


@pytest.mark.parametrize("bad", [
    "http://packages.example.invalid/npm/", "https://user:secret@packages.example.invalid/npm/",
    "https://user@packages.example.invalid/npm/", "https://packages.example.invalid/npm/?token=secret",
    "https://packages.example.invalid/npm/#secret", "https://packages.example.invalid/npm",
    "https://packages.example.invalid:bad/npm/", "https://packages.example.invalid:0/npm/",
    "https://packages.example.invalid/npm/\nEVIL=1", "https://packages.example.invalid/npm/\r",
    "https://packages.example.invalid\\@evil.invalid/", "https://packages.example.invalid/npm/%2e%2e/",
    "https://packages.example.invalid/npm/../", "https://packages.example.invalid/npm//",
    "https://PACKAGES.example.invalid/npm/", "file:///feed/", "https://packages.example.invalid/npm/$HOME/",
])
@pytest.mark.parametrize("option", ["registry", "tarball_base"])
def test_bad_urls_fail_without_writes(source, workspace, option, bad):
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    output = workspace / "export"
    with pytest.raises(ValueError):
        export(source, output, **{option: bad})
    assert not output.exists()
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("option", ["approved", "confirm_mirror_layout"])
def test_export_requires_both_explicit_confirmations(source, workspace, option):
    with pytest.raises(ValueError):
        export(source, workspace / "export", **{option: False})
    assert not (workspace / "export").exists()


def test_does_not_overwrite_output_or_source(source):
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    with pytest.raises(FileExistsError):
        export(source, source)
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


def test_failed_second_write_rolls_back_export(source, workspace, monkeypatch):
    output = workspace / "export"
    original_open = Path.open

    def fail_lock_write(path, *args, **kwargs):
        if path == output / "package-lock.json":
            raise OSError("simulated disk failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_lock_write)
    with pytest.raises(OSError):
        export(source, output)
    assert not output.exists()
    feeds.check(source, {})


@pytest.mark.parametrize("resolved", [
    "https://unapproved.example.invalid/plain/-/plain-1.2.3.tgz",
    feeds.INTERNAL_NPM + "wrong/plain/-/plain-1.2.3.tgz",
    feeds.INTERNAL_NPM + "plain/-/plain-9.9.9.tgz",
    feeds.INTERNAL_NPM + "plain/-/plain-1.2.3.tgz?token=secret",
    "http://packagefeedproxy.microsoft.io/npm/plain/-/plain-1.2.3.tgz",
    "https://packagefeedproxy.microsoft.io.evil.invalid/npm/plain/-/plain-1.2.3.tgz",
])
def test_unknown_or_noncanonical_source_tarballs_fail_closed(source, workspace, resolved):
    lock = feeds.read_lock(source / "package-lock.json")
    lock["packages"]["node_modules/plain"]["resolved"] = resolved
    (source / "package-lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        export(source, workspace / "export")
    assert not (workspace / "export").exists()


@pytest.mark.parametrize("update", [
    {"integrity": ""}, {"version": "^1.2.3"}, {"link": True}, {"name": "aliased"},
    {"resolved": "git+https://git.example.invalid/repo"}, {"resolved": None},
])
def test_missing_integrity_unpinned_and_nonregistry_entries_rejected(source, update):
    lock = feeds.read_lock(source / "package-lock.json")
    lock["packages"]["node_modules/plain"].update(update)
    with pytest.raises(ValueError):
        feeds.validate_lock(lock, feeds.INTERNAL_TARBALLS)


def test_legacy_lock_and_duplicate_keys_rejected(source):
    lock = feeds.read_lock(source / "package-lock.json")
    old = copy.deepcopy(lock)
    old["lockfileVersion"] = 2
    with pytest.raises(ValueError):
        feeds.validate_lock(old, feeds.INTERNAL_TARBALLS)
    lock["dependencies"] = {"hidden": {"resolved": "https://unapproved.example.invalid/hidden.tgz"}}
    with pytest.raises(ValueError):
        feeds.validate_lock(lock, feeds.INTERNAL_TARBALLS)
    (source / "package-lock.json").write_text('{"lockfileVersion": 3, "lockfileVersion": 2}')
    with pytest.raises(ValueError):
        feeds.read_lock(source / "package-lock.json")


@pytest.mark.parametrize("extra", [
    "strict-ssl=false\n", "@scope:registry=https://other.example.invalid/\n",
    "//packages.example.invalid/:_authToken=secret\n", "registry=https://other.example.invalid/\n",
])
def test_npmrc_disallows_tls_overrides_scoped_feeds_and_credentials(source, extra):
    with (source / ".npmrc").open("a") as stream:
        stream.write(extra)
    with pytest.raises(ValueError):
        feeds.check(source, {})


def test_mismatched_selection_fails_instead_of_silently_using_internal(source, workspace):
    with pytest.raises(ValueError):
        feeds.check(source, approved_env())
    output = workspace / "export"
    export(source, output)
    with pytest.raises(ValueError):
        feeds.check(output, {})
    lock = feeds.read_lock(output / "package-lock.json")
    lock["packages"]["node_modules/plain"]["resolved"] = feeds.INTERNAL_NPM + "plain/-/plain-1.2.3.tgz"
    (output / "package-lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        feeds.check(output, approved_env())


def test_alternative_registry_requires_explicit_noninternal_mirror():
    with pytest.raises(ValueError):
        feeds.selected_feeds({"PACKAGE_FEED_NPM_REGISTRY": REGISTRY})
    for base in feeds.INTERNAL_TARBALLS:
        with pytest.raises(ValueError):
            feeds.selected_feeds({**approved_env(), "PACKAGE_FEED_NPM_TARBALL_BASE": base})


@pytest.mark.parametrize("index", ["http://python.example.invalid/", "https://user:secret@python.example.invalid/", "https://python.example.invalid/?token=secret"])
def test_python_index_requires_tls_without_credentials(index):
    with pytest.raises(ValueError):
        feeds.selected_feeds({"PACKAGE_FEED_PYTHON_INDEX": index})


def test_ci_environment_is_written_only_after_full_validation(source, workspace, monkeypatch):
    monkeypatch.setattr(feeds, "ROOT", source)
    monkeypatch.setattr(feeds, "check", lambda: (REGISTRY, PYTHON_INDEX))
    target = workspace / "github-env"
    feeds.main(["check", "--github-env", str(target)])
    assert target.read_text() == (
        f"PIP_INDEX_URL={PYTHON_INDEX}\nNPM_CONFIG_REGISTRY={REGISTRY}\n"
        "PIP_CONFIG_FILE=/dev/null\nPIP_EXTRA_INDEX_URL=\nPIP_TRUSTED_HOST=\n"
        "NPM_CONFIG_STRICT_SSL=true\n"
    )

    def reject():
        raise ValueError("secret input must not be printed")

    monkeypatch.setattr(feeds, "check", reject)
    before = target.read_bytes()
    with pytest.raises(SystemExit) as error:
        feeds.main(["check", "--github-env", str(target)])
    assert error.value.code == 2
    assert target.read_bytes() == before


def test_cli_invalid_input_has_no_writes_or_credential_echo(workspace, capsys):
    output = workspace / "export"
    with pytest.raises(SystemExit) as error:
        feeds.main([
            "prepare", "--registry", "https://user:supersecret@packages.example.invalid/",
            "--tarball-base", TARBALLS, "--output", str(output), "--approved", "--confirm-mirror-layout",
        ])
    assert error.value.code == 2
    assert "supersecret" not in capsys.readouterr().err
    assert not output.exists()

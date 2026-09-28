"""Offline, opt-in package mirror handoff; never install or edit the source pair."""

import argparse
import copy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
INTERNAL_NPM = "https://packagefeedproxy.microsoft.io/npm/"
INTERNAL_TARBALLS = (
    INTERNAL_NPM,
    "https://ms-feed-25.pkgs.visualstudio.com/1es-public/_packaging/npm-public/npm/registry/",
)
INTERNAL_PYTHON = "https://packagefeedproxy.microsoft.io/pypi/simple/"
PACKAGE_NAME = re.compile(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
INTEGRITY = re.compile(r"(?:sha(?:1|256|384|512)-[A-Za-z0-9+/]+={0,2})(?: sha(?:1|256|384|512)-[A-Za-z0-9+/]+={0,2})*")


def https_url(value):
    """Use a deliberately narrow URL grammar, shared by CLI and CI checks."""
    if not isinstance(value, str) or not value or re.search(r"[^A-Za-z0-9:/@._~+-]", value):
        raise ValueError("Feed URLs must be plain HTTPS URLs without credentials or escapes.")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError("Invalid feed URL.") from None
    if (
        url.scheme != "https" or not url.hostname or url.username is not None
        or url.password is not None or url.query or url.fragment
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", url.hostname)
        or url.netloc != url.hostname + (f":{port}" if port is not None else "")
        or (port is not None and not 1 <= port <= 65535)
        or any(segment in (".", "..") for segment in url.path.split("/"))
        or "//" in url.path
    ):
        raise ValueError("Feed URLs require canonical HTTPS, with no credentials, query or fragment.")
    return value


def feed_base(value):
    https_url(value)
    if not value.endswith("/"):
        raise ValueError("Feed base URLs must end with '/'.")
    return value


def selected_feeds(env=None):
    env = os.environ if env is None else env
    registry = feed_base(env.get("PACKAGE_FEED_NPM_REGISTRY") or INTERNAL_NPM)
    python_index = feed_base(env.get("PACKAGE_FEED_PYTHON_INDEX") or INTERNAL_PYTHON)
    mirror = env.get("PACKAGE_FEED_NPM_TARBALL_BASE", "")
    if mirror:
        bases = (feed_base(mirror),)
    elif registry == INTERNAL_NPM:
        bases = INTERNAL_TARBALLS
    else:
        raise ValueError("An alternative npm registry requires PACKAGE_FEED_NPM_TARBALL_BASE.")
    if registry != INTERNAL_NPM and any(base in INTERNAL_TARBALLS for base in bases):
        raise ValueError("An alternative registry cannot retain the internal tarball feed.")
    return registry, bases, python_index


def npmrc_text(registry):
    return f"registry={feed_base(registry)}\nstrict-ssl=true\naudit=false\n"


def validate_npmrc(text, registry):
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in settings:
            raise ValueError("Invalid or duplicate .npmrc setting.")
        settings[key] = value
    if settings != {"registry": registry, "strict-ssl": "true", "audit": "false"}:
        raise ValueError(".npmrc must match the approved registry, require TLS and disable audit; no overrides.")


def tarball_suffix(package_path, dependency):
    if not isinstance(package_path, str) or not package_path.startswith("node_modules/"):
        raise ValueError("Only npm registry package entries are supported.")
    name = package_path.rsplit("node_modules/", 1)[-1]
    version = dependency.get("version")
    if (
        not PACKAGE_NAME.fullmatch(name) or not isinstance(version, str)
        or not VERSION.fullmatch(version)
        or not isinstance(dependency.get("integrity"), str)
        or not INTEGRITY.fullmatch(dependency["integrity"])
        or dependency.get("link") or dependency.get("name", name) != name
    ):
        raise ValueError("Every package needs a supported name, pinned version and integrity (no aliases or links).")
    return f"{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz"


def validate_lock(lock, bases):
    bases = tuple(feed_base(base) for base in bases)
    if (
        not isinstance(lock, dict) or lock.get("lockfileVersion") != 3
        or not isinstance(lock.get("packages"), dict) or "" not in lock["packages"]
        or "dependencies" in lock
    ):
        raise ValueError("Expected a v3 npm lockfile with a packages table and no legacy resolution table.")
    for package_path, dependency in lock["packages"].items():
        if not isinstance(dependency, dict):
            raise ValueError("Invalid lockfile package.")
        if not package_path:
            if "resolved" in dependency:
                raise ValueError("The root package must not have a download URL.")
            continue
        suffix = tarball_suffix(package_path, dependency)
        resolved = https_url(dependency.get("resolved"))
        if resolved not in {base + suffix for base in bases}:
            raise ValueError("Lockfile tarball does not match the approved feed and exact package/version layout.")


def read_lock(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in lockfile.")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique_keys)


def check(root=ROOT, env=None):
    registry, bases, python_index = selected_feeds(env)
    validate_npmrc((root / ".npmrc").read_text(), registry)
    validate_lock(read_lock(root / "package-lock.json"), bases)
    return registry, python_index


def prepare(root, output, registry, tarball_base, approved=False, confirm_mirror_layout=False):
    registry, tarball_base = feed_base(registry), feed_base(tarball_base)
    if not approved or not confirm_mirror_layout:
        raise ValueError("Both organization approval and exact mirror layout confirmation are required.")
    selected_feeds({
        "PACKAGE_FEED_NPM_REGISTRY": registry,
        "PACKAGE_FEED_NPM_TARBALL_BASE": tarball_base,
    })
    # Only the known internal source pair is eligible for this one-way handoff.
    check(root, {})
    original = read_lock(root / "package-lock.json")
    rewritten = copy.deepcopy(original)
    for package_path, dependency in rewritten["packages"].items():
        if package_path:
            dependency["resolved"] = tarball_base + tarball_suffix(package_path, dependency)
    validate_lock(rewritten, (tarball_base,))
    contents = {
        ".npmrc": npmrc_text(registry),
        "package-lock.json": json.dumps(rewritten, indent=2, ensure_ascii=False) + "\n",
    }
    # Complete validation/serialization before creating anything; never overwrite.
    output.mkdir()
    created = []
    try:
        for filename, text in contents.items():
            path = output / filename
            with path.open("x", encoding="utf-8") as stream:
                created.append(path)
                stream.write(text)
    except BaseException:
        for path in reversed(created):
            path.unlink()
        output.rmdir()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("check", help="Offline check against explicitly selected feeds.")
    verify.add_argument("--github-env", type=Path, help="Write verified installer settings for later CI steps.")
    export = commands.add_parser("prepare", help="Export a new pair; never modify existing source files.")
    export.add_argument("--registry", required=True)
    export.add_argument("--tarball-base", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--approved", action="store_true")
    export.add_argument("--confirm-mirror-layout", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            registry, python_index = check()
            if args.github_env:
                # URL grammar excludes newlines and workflow-command delimiters.
                with args.github_env.open("a", encoding="utf-8") as stream:
                    stream.write(
                        f"PIP_INDEX_URL={python_index}\nNPM_CONFIG_REGISTRY={registry}\n"
                        "PIP_CONFIG_FILE=/dev/null\nPIP_EXTRA_INDEX_URL=\nPIP_TRUSTED_HOST=\n"
                        "NPM_CONFIG_STRICT_SSL=true\n"
                    )
            print("Approved feed configuration and all locked tarball URLs verified (offline).")
        else:
            prepare(ROOT, args.output, args.registry, args.tarball_base, args.approved, args.confirm_mirror_layout)
            print("Exported approved mirror pair; original files unchanged. No packages downloaded.")
    except (OSError, ValueError):
        # Do not echo untrusted URLs or OS errors containing credential-bearing inputs.
        parser.exit(2, "Feed validation/export failed. Check approval, HTTPS URLs, exact lock layout and output path.\n")


if __name__ == "__main__":
    main()

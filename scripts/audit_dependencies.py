"""Query public advisory metadata without uploading source or private configuration."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dependency_queries(requirements, lock):
    packages = set()
    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise ValueError("Audit requires exact, plain runtime requirement pins.")
        name, version = match.groups()
        packages.add(("PyPI", re.sub(r"[-_.]+", "-", name).lower(), version))
    for path, entry in lock["packages"].items():
        if path:
            if "node_modules/" not in path or not entry.get("version"):
                raise ValueError("Audit requires versioned registry packages in the npm lockfile.")
            packages.add(("npm", path.rsplit("node_modules/", 1)[1], entry["version"]))
    return [{"package": {"ecosystem": ecosystem, "name": name}, "version": version}
            for ecosystem, name, version in sorted(packages)]


def lookup(queries):
    request = urllib.request.Request(
        "https://api.osv.dev/v1/querybatch",
        data=json.dumps({"queries": queries}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    results = payload["results"]
    if not isinstance(results, list) or len(results) != len(queries) or any(not isinstance(result, dict) for result in results):
        raise ValueError("Advisory service returned an incomplete or invalid result set.")
    return results


def main():
    try:
        queries = dependency_queries(
            (ROOT / "requirements.txt").read_text(),
            json.loads((ROOT / "package-lock.json").read_text()),
        )
        findings = []
        for offset in range(0, len(queries), 100):
            batch = queries[offset:offset + 100]
            for query, result in zip(batch, lookup(batch), strict=True):
                for advisory in result.get("vulns", []):
                    advisory_id = advisory["id"]
                    findings.append(
                        f"{query['package']['ecosystem']} {query['package']['name']} "
                        f"{query['version']}: https://osv.dev/vulnerability/{urllib.parse.quote(advisory_id, safe='')}"
                    )
        if findings:
            raise SystemExit("Dependency advisories found:\n" + "\n".join(findings))
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"Dependency audit could not complete: {type(error).__name__}: {error}") from error
    print(f"No known OSV advisories returned for {len(queries)} pinned runtime/locked npm package versions.")


if __name__ == "__main__":
    main()

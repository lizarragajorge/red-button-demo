import io
import json
import urllib.error
import urllib.request

import pytest

from scripts import audit_dependencies
from scripts.audit_dependencies import dependency_queries, lookup
from scripts.check_publication import publication_issues


@pytest.mark.parametrize("path", [
    ".env", ".env.local", "infra/terraform.tfstate", "infra/terraform.tfstate.backup",
    "infra/private.tfvars", "infra/private.tfvars.json", "infra/deploy.tfplan",
    "certificate.pem", "secret.key", "bundle.zip", "node_modules/tool/index.js",
    ".venv/bin/python", "dist/index.html", "nested/.npmrc", ".pypirc",
    ".azure/profile.json", ".aws/config", ".ssh/id_ed25519", "state.tfbackend", ".terraformrc",
    "release.json", "releases/manifest.json",
])
def test_prohibited_publication_paths(path):
    assert publication_issues([("100644", "0", path)])


def test_source_examples_and_lockfiles_are_publishable():
    paths = [
        ".env.example", "infra/terraform.tfvars.example", "infra/.terraform.lock.hcl",
        "infra/backend.tf.example", "infra/backend.azurerm.tfbackend.example",
        ".npmrc", "package-lock.json", "server/app.py", "docs/architecture.drawio",
    ]
    assert publication_issues([("100644", "0", path) for path in paths]) == []


def test_symlinks_and_conflict_stages_are_rejected():
    assert publication_issues([("120000", "0", "innocent.txt")])
    assert publication_issues([("100644", "2", "server/app.py")])


def test_audit_queries_contain_only_package_metadata_and_deduplicate():
    queries = dependency_queries("PyJWT==2.14.0\n# comment\n", {"packages": {
        "": {"name": "private-project"},
        "node_modules/@azure/msal-browser": {"version": "4.30.0"},
        "node_modules/tool/node_modules/@azure/msal-browser": {"version": "4.30.0"},
    }})
    assert queries == [
        {"package": {"ecosystem": "PyPI", "name": "pyjwt"}, "version": "2.14.0"},
        {"package": {"ecosystem": "npm", "name": "@azure/msal-browser"}, "version": "4.30.0"},
    ]


@pytest.mark.parametrize("requirement", ["fastapi>=0.1", "-r local.txt", "https://private.invalid/package.whl"])
def test_audit_rejects_non_exact_runtime_pins(requirement):
    with pytest.raises(ValueError):
        dependency_queries(requirement, {"packages": {}})


@pytest.mark.parametrize("results", [[], [{}, {}], ["invalid"]])
def test_incomplete_advisory_responses_fail_closed(monkeypatch, results):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(
        json.dumps({"results": results}).encode(),
    ))
    with pytest.raises(ValueError):
        lookup([{"package": {"ecosystem": "PyPI", "name": "example"}, "version": "1"}])


def test_advisory_network_failure_is_not_reported_as_clean(monkeypatch):
    def unavailable(queries):
        raise urllib.error.URLError("Offline")
    monkeypatch.setattr(audit_dependencies, "lookup", unavailable)
    with pytest.raises(SystemExit, match="could not complete"):
        audit_dependencies.main()


def test_advisory_findings_fail_with_package_and_advisory_id(monkeypatch):
    monkeypatch.setattr(audit_dependencies, "lookup", lambda queries: [
        {"vulns": [{"id": "TEST-ADVISORY"}]} for query in queries
    ])
    with pytest.raises(SystemExit, match="Dependency advisories found"):
        audit_dependencies.main()

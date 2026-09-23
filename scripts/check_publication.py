"""Check the actual Git index for files that must not be published."""

import fnmatch
import subprocess
from pathlib import PurePosixPath


def publication_issues(entries):
    forbidden_parts = {
        ".venv", "node_modules", ".terraform", ".python_packages", "__pycache__",
        ".pytest_cache", "dist", "test-results", "playwright-report", "htmlcov",
        ".azure", ".aws", ".ssh",
    }
    forbidden_names = {"credentials", ".pypirc", "pip.conf", ".coverage", ".DS_Store", ".terraformrc", "terraform.rc"}
    forbidden_patterns = ("*.tfstate*", "*.tfplan", "*.tfvars", "*.tfvars.json", "*.tfbackend", "*.zip", "*.log", "*.pem", "*.key", "*.pfx", "*.p12", "*.pyc")
    issues = []
    for mode, stage, name in entries:
        path = PurePosixPath(name)
        if mode == "120000" or stage != "0":
            issues.append(f"{name}: symlink or unresolved merge stage")
        if (
            any(part in forbidden_parts for part in path.parts)
            or path.name in forbidden_names
            or (path.name.startswith(".env") and path.name != ".env.example")
            or any(fnmatch.fnmatch(path.name, pattern) for pattern in forbidden_patterns)
            or (path.name == ".npmrc" and name != ".npmrc")
        ):
            issues.append(f"{name}: prohibited publication path")
    return issues


def main():
    output = subprocess.run(
        ["git", "ls-files", "--stage", "-z"], check=True, capture_output=True, text=True,
    ).stdout
    entries = []
    for entry in output.split("\0"):
        if entry:
            metadata, name = entry.split("\t", 1)
            mode, _, stage = metadata.split()
            entries.append((mode, stage, name))
    if not entries:
        raise SystemExit("No indexed files to check. Stage the intended publication snapshot first.")
    issues = publication_issues(entries)
    if issues:
        raise SystemExit("\n".join(issues))
    print(f"Publication path check passed for {len(entries)} indexed files.")


if __name__ == "__main__":
    main()

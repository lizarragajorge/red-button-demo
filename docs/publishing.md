# Publishing and sharing the demo

## Audience and release scope

This repository is a reference demo for authorized users with access to the
required package feeds and an Entra tenant. It is not an anonymous public
playground, a production incident-response system, or a complete Commvault
emulator. Keep the simulated environment and operational safeguards explicit.

Public source access does not grant access to a hosted deployment. Each operator
needs approved tenant membership or guest onboarding and the required app
assignments. Do not publish invitations, credentials, tokens, server inventories,
or screenshots containing real client information.

## Approval and licensing

The project uses the [MIT License](../LICENSE), with a copyright notice for
the Red Button demo contributors. Before making a repository public, confirm
the appropriate rights holder and approval to disclose the source and
internal-feed references. Review third-party dependency license/notice
obligations separately; the project license does not relicense its dependencies.
Retain the MIT copyright and permission notices when redistributing the source.
The npm manifest's `private` flag prevents npm publication; it does not control
GitHub visibility.

## Review the exact Git snapshot

Never upload the working directory as an archive. It can contain local `.env`,
Terraform state and backups, account-specific tfvars, package-manager settings,
and build outputs that must not be published.

1. Initialize a local Git repository on `main` if one does not already exist.
2. Stage only source, tests, documentation, examples, lockfiles, and CI files.
3. Run `python scripts/check_publication.py` to reject prohibited indexed paths,
   symlinks and merge-conflict stages. The check reads index metadata, not local
   credentials.
4. Inspect `git diff --cached --stat` and `git diff --cached --check`, then review
   the staged diff. Run a current Gitleaks scan with redaction on the staged
   snapshot and, after committing, on all history.
5. Verify that `.env`, `infra/terraform.tfvars`, `infra/terraform.tfstate` and
   its backups remain ignored and untracked. Preserve them locally; do not
   delete state needed to manage deployed resources.
6. Review dependency advisories with `python scripts/audit_dependencies.py`.
   It sends only public package names and versions to the OSV API, not source,
   configuration, tokens, or tenant information. Lookup failures fail the check.
7. Select an approved GitHub owner and repository name. Start **private**, review
   the first commit, and get approval before changing visibility.

An ignore file cannot remove a secret already committed. If a secret is exposed,
revoke or rotate it and follow incident procedures; deleting it in a later
commit is not sufficient. See [security reporting](../SECURITY.md).

## Continuous integration

[The workflow](../.github/workflows/validate.yml) uses ephemeral GitHub-hosted
Ubuntu runners, immutable action revisions, read-only repository permissions,
and no Azure credentials or automatic deployment. It does not use
`pull_request_target` or run untrusted pull requests on a corporate self-hosted
runner. Git checkout credentials are not persisted.

The validation job requires access to:

- Microsoft's npm feed configured in [`.npmrc`](../.npmrc), with no public npm
  fallback. Dependency lifecycle scripts are disabled.
- The approved Python feed at `https://packagefeedproxy.microsoft.io/pypi/simple/`.
- Official Playwright browser downloads and signed Terraform provider downloads.
- The OSV API for advisory metadata.

The workflow contains no feed credentials. If your feed requires authentication
or private networking, configure an approved isolated CI environment before
enabling it. Do not expose organizational tokens or network access to forked
pull requests. Inaccessible feeds must fail visibly, not fall back to another
registry or skip validation. No passing remote CI run is implied by committing
the workflow; verify its first run after the private push.

Checks cover source publication boundaries, Gitleaks, pinned runtime and locked
npm advisories, Python tests, JavaScript syntax, frontend build, browser tests,
and Terraform format/validation/mock tests. Advisory absence is not a security
guarantee, and mock tests are not cloud integration tests.

## Before sharing a deployment

Complete a hosted sign-in as an assigned operator, exercise a simulated request,
and verify an unassigned user is rejected. Keep `COMMVAULT_MODE=stub` and
`ENABLE_LIVE_OPERATIONS=false`. Decide who may access logs and copy support
details. Review cost and cleanup instructions in the
[infrastructure guide](infrastructure.md#costs-checks-and-cleanup).

The B1 plan is billable even when the web app is stopped. Keep Terraform state
protected and retained until authorized teardown is complete.

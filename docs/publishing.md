# Publishing and handoff

The [README](../README.md) is the starting point. Share a verified reference demo,
not a claim of production readiness or untested Commvault compatibility.

## Keep source changes separate from deployment

Template improvements do not require deploying to the maintained demo, applying
Terraform, changing tenant access, or migrating state. Work on a review branch;
preserve the environment's local variables, state, backend, and feed selection.
Any later rollout is a separate authorized change.

Receiving teams use fresh clones and their own resources, registrations, and
state. They do not inherit the originating team's local configuration or access
allowlist. Public source does not grant access to the hosted app.

## Before publishing source

- Confirm the rights holder, disclosure approval, and permission to disclose
  internal-feed references. The [MIT License](../LICENSE) does not itself
  establish organizational approval; retain its notices and review dependency
  license/notice obligations separately.
- Review the exact source snapshot and publishable history. Never upload the
  whole working directory: it can contain credentials, state, actual variables,
  build artifacts, and private package-manager configuration.
- Run `python scripts/check_publication.py` against the intended Git index,
  inspect the staged diff, and run a redacted Gitleaks scan on candidate files
  and history. `.gitignore` does not remove anything already committed.
- Run tests, dependency-advisory checks, and the matching Linux package smoke
  checks. `python scripts/audit_dependencies.py` sends public package names and
  versions to OSV, not source or tenant data; a failed lookup is not a clean scan.
- Do not publish real inventories, client screenshots, invitations, operational
  logs, receipts containing environment details, credentials, or state.
- Start private and get approval before changing visibility. If a secret was
  exposed, rotate/revoke it and follow incident procedures; deleting the latest
  copy is insufficient. See [security reporting](../SECURITY.md).

## CI and versioned releases

[The validation workflow](../.github/workflows/validate.yml) uses pinned actions,
read-only permissions, and no Azure credentials or deployment. It requires the
selected approved feeds, Playwright downloads, Terraform provider downloads,
and advisory endpoints. See [feed setup](package-feeds.md).

Use an approved isolated runner. Never expose organizational credentials or
network access to untrusted forks. Inaccessible feeds and disabled hosted
runners must fail visibly; do not bypass policy or claim a local test as a
successful remote CI run.

After approval and successful checks, tag the verified source and retain the
release manifest, package hashes, tested toolchain, limitations, and rollback
instructions in the approved artifact store. The package manifest's version
alone is not a verified release. No tag, GitHub release, visibility change, or
deployment is automatically created by these instructions.

## Handoff checklist

Complete this in the receiving organization's environment:

- [ ] Confirm subscription/tenant, Azure and Graph permissions, own state and
      names, region capacity, package feeds, and the selected networking recipe.
- [ ] Review the Terraform plan. Keep stub mode, live writes off, and
      single-tenant access unless external organizations are deliberately enabled.
- [ ] Build the matching Linux packages and retain provenance/hashes. Deploy
      explicitly; verify the intended running release and assets, not only ZIP
      upload success or an old healthy process.
- [ ] Complete real MSAL sign-in with an admitted user **without**
      `BackupOperator`; confirm full simulator access. Test silent renewal and
      the registered `/auth/silent` callback.
- [ ] Verify anonymous denial. If multi-tenant access is enabled, verify actual
      external consent/sign-in and denial for an unapproved tenant.
- [ ] Cancel the review dialog, then submit a typed-confirmed synthetic request.
      Check outcomes and requested schedule; acceptance is not recovery proof.
- [ ] If restricting simulator access, verify read-only behavior without the
      operator role and successful operation with the role.
- [ ] For queued mode, verify both packages, the fresh worker host and three
      functions, managed-identity storage access, inventory freshness, request
      completion/recovery, and rejection of another user's lookup. A web receipt
      does not prove worker or queue success.
- [ ] Confirm private DNS/networking where selected, disabled shared storage
      keys/anonymous access, and no secrets in packages or frontend assets.
- [ ] Assign owners for access, updates, costs, retention, alerts, unknown-outcome
      reconciliation, rollback, support, and teardown.

Record results, source revision, and exceptions in the organization's approved
system, not as customer data in the public template. Local/mock tests do not
replace these hosted checks.

## Before real backup operations

Require separate compatibility and operational approval: exact API version,
paths/envelopes, auth, network routing, read-only inventory, target limits,
change windows, monitoring, incident response, and verified re-enable behavior.
APIM configuration is not evidence that the in-process simulator traverses it.

Live writes require `BackupOperator` plus the explicit enablement gate. The
simulator's default access never grants these privileges. Establish a procedure
for ambiguous outcomes; do not blindly replay writes or delete coordination
records. Code rollback does not undo upstream actions or stored requests.

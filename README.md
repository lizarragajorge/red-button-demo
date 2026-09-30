# Red Button demo

An authenticated backup-control demo: **Python/FastAPI**, **MSAL + Microsoft
Entra ID**, and **Terraform**. It simulates two Commvault operations so a team
can demonstrate the workflow without changing real backups.

**Defaults:** queued execution with durable request tracking, single-tenant
sign-in, simulated servers, live writes disabled. Storage and a running
Functions worker are required; use `EXECUTION_MODE=sync` explicitly for a
storage-free local run.
Any admitted signed-in user can operate the simulator. Real operations always
require `BackupOperator` and an explicit live-write gate.

This is a reference template, not a production incident-response system or an
officially supported Commvault client.

## Try an existing deployment

1. Sign in and confirm the **DEMO** badge.
2. Select a synthetic server, then open the red button's review dialog.
3. Review the targets and the default 60-minute re-enable request. Try **Cancel**
   first to show that opening the dialog does not submit anything.
4. Reopen, review the selected servers and duration, and click **Disable backups**.
5. Inspect the per-server outcome and **Support details**. In queued mode, wait
   for completion; queue acceptance is not operation success.

The inventory includes both infrastructure and workload servers, 10 per page.
**Select all** adds all servers matching the search across every page.
**Select page** selects or clears only the current page; selections persist
across pages and searches. The adjacent count includes every selected server,
including off-page selections. There is no fixed server-count cap and selections
are never silently truncated. **Clear selection** or refreshing inventory clears
all selections.
Expand **Duration: 60 minutes** on the main screen to change the timing or
choose **Until manually re-enabled**. These settings persist until changed or
the page is reloaded. The confirmation asks **Disable backups for 60 minutes?**
and lists selected server names. Expand **Server details** for hostnames and IDs.
The DEMO/LIVE badge identifies the environment; no typing is required.
Cancel and Escape submit nothing. Duration is measured from confirmation and
sent as a requested re-enable deadline, not a guarantee of current backup state.

**Last request** describes a command outcome, not verified current backup state.
**Request completed** means processing finished and the disable command was
accepted for every selected server. Backup state and re-enable are not monitored.
Queued requests update automatically and resume after reload. **Retry status**
appears only if an update fails; it never resubmits the operation. Request ID
lookup is available under **Support details**.
A re-enable schedule is a request, not proof
that recovery occurred. Unknown outcomes require reconciliation, not blind retry.

The existing 16 KiB JSON request-body protection still applies; oversized
requests are explicitly rejected with HTTP 413 before execution. Hosting
timeouts and upstream throughput also still apply. Use queued execution for
large or slow operations that need durable tracking, and validate capacity in
the target environment. Removing the count cap is not an unlimited-throughput
guarantee.

## Deploy your organization's copy

Use a **fresh clone**, your own Entra registrations/resources, and your own
Terraform state. Never copy another deployment's `.env`, tfvars, state, or
tenant allowlist. Editing or publishing source does not deploy it.

### 1. Choose the smallest recipe you need

| Recipe | When to use it | Terraform settings |
|---|---|---|
| **Queued demo (default)** | Durable requests, progress tracking, and restart recovery | `enable_three_tier=true`, `activate_queued_execution=true` |
| **Simple synchronous demo** | Demonstrate sign-in and simulated actions without durable tracking | `enable_three_tier=false` |
| **Private-storage queued demo** | Queued behavior where policy requires private storage | Queued settings plus `enable_private_storage_networking=true` |

Public storage endpoints in queued mode still require Entra tokens and scoped
RBAC; shared keys and anonymous Blob access remain disabled. Choose private mode
when required by policy. Do not change an existing environment to another
recipe without reviewing the resource and data impact.

The [diagram](docs/architecture.drawio) has one page for the synchronous option
and one for the queued default. APIM, gateway ingress, and live Commvault connectivity
are optional integrations, not prerequisites.

### 2. Configure and provision

Follow [Azure setup](docs/infrastructure.md). It covers permissions, the example
variables, sign-in, networking, and optional team-owned remote state.

The default package feeds are Microsoft's internal feeds. Receiving teams must
explicitly select their own approved feeds through
[package-feed setup](docs/package-feeds.md); there is no automatic public fallback.

### 3. Build, deploy, and accept

Use [Build and deploy](docs/deployment-tools.md) for the tested commands, then
complete the [handoff checklist](docs/publishing.md#handoff-checklist) in your own
environment. Terraform provisions resources; application deployment is separate.
No workflow in this repository automatically deploys to Azure.

Existing environments are not automatically migrated. An explicit
`EXECUTION_MODE=sync` or `enable_three_tier=false` still opts out. Before
upgrading an environment without an explicit execution mode, either provision
and deploy the queued stack or pin `EXECUTION_MODE=sync`. Review Terraform plans:
the new defaults can add billable storage and a worker. Do not activate queued
execution before the worker and storage are ready.

## Run locally instead

Use Python 3.12+, Node >=22.12, and your approved feeds. The Azure package builder
specifically requires glibc Linux x86_64 / Python 3.12; a macOS virtualenv cannot
be uploaded to Azure.

Follow [local development](docs/infrastructure.md#local-development) to configure
real Entra sign-in, restore dependencies, and run the Python/Vite servers.
There is no local authentication bypass.

## Commvault contract

The same HTTP adapter builds requests for the private simulator or a configured
upstream API. The simulator uses in-process ASGI transport: no public stub
endpoint, network listener, or real server is contacted.

| Operation | Upstream path | Result |
|---|---|---|
| [Get servers](https://api.commvault.com/docs/latest/api/cv/OpenAPI3/get-servers/) | `GET /V4/Servers` | `totalServers` and `servers` |
| [Disable backups](https://api.commvault.com/docs/latest/api/cv/OpenAPI3/disable-backup-server/) | `PUT /V4/Server/{serverId}/Backup/Action/Disable` | `errorCode` and `errorMessage` |

- The app sends `showOnlyInfrastructureMachines=0` for all servers; the stub's
  query default is `1`. Inventory includes IDs, names, hostnames, OS, and
  infrastructure classification; additional real response fields are preserved.
- `enableAfterADelay` is an absolute UTC Unix timestamp in **seconds**, not a
  duration. `enableAfterDelayTimeZone` is an optional integer.
- Nonzero `errorCode` is failure even with HTTP 200. The client preserves API
  base-path prefixes, uses a 15-second timeout, and does not redirect or retry
  writes automatically.
- Live auth is a server-side `Authorization` or `Authtoken` header; the browser's
  Entra token is never forwarded upstream.

The stub is not a full emulator or a verified drop-in for an untested customer
version. It does not emulate login/token renewal, paging extensions, batch APIs,
restore control, or running-job cancellation. Its schema/error behavior must be
checked against an approved target before live integration. Disabling backup
activity is not the same as cancelling jobs or isolating hosts.

Simple-mode state resets on restart. Queued mode persists simulated state and
owner-scoped request status; see [queued behavior](docs/queued-architecture.md)
for idempotency, freshness, and failure/recovery limits.

## Development checks

After restoring approved dependencies:

```sh
python -m pytest -p no:cacheprovider
npm run check
npm run build
npm run test:e2e
terraform -chdir=infra validate
terraform -chdir=infra test
```

Install the Playwright test browser once with `npm run test:install-browser`.
Initialize Terraform as described in the setup guide before its checks.
Cloud integrations are opt-in; passing local tests does not prove hosted sign-in
or client API compatibility.

## Sharing and support

Read [publishing and handoff](docs/publishing.md) before sharing a deployment or
making source public. The project uses the [MIT License](LICENSE); dependencies
retain their own licenses. Confirm ownership and disclosure approval.
See [security reporting](SECURITY.md) for responsible disclosure.

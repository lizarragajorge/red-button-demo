# Red Button demo

An Azure-ready **Python / FastAPI** backup-control demo using **MSAL**, Microsoft Entra ID, **Terraform**, and a stateful HTTP stub for two Commvault V4 operations. The same Python HTTP client calls either the stub or a customer-managed/SaaS API, selected by configuration.

MSAL runs in the browser; Python validates the resulting API access tokens. JavaScript is used only for the UI and its build/browser tests. There is no Node backend or Node requirement on the deployed server.

The UI uses a compact operations-workspace layout: light inventory/results surfaces and a distinct charcoal panel centered on the circular red backup control. Results sit beneath inventory on desktop, while controls stack on smaller screens. Deployment and identity setup instructions live in this documentation, not the operator UI. The design uses system fonts and locally defined graphics, with no third-party brand assets or external font/image requests. The red button opens a review dialog; it never bypasses the typed confirmation.

Inventory can be searched by name, hostname, or ID. Search preserves selections and explicitly counts selected servers hidden by the search; the review dialog always lists every target. Refreshing inventory or changing the infrastructure filter clears selection. The 50-server limit is enforced while selecting, not after submission. Each review starts with the safe 60-minute re-enable default. Results distinguish accepted, partial, failed, and unknown outcomes; an unknown outcome requires checking Commvault before reselecting targets and retrying.

The Demo badge explicitly identifies a simulated environment; live mode always warns that actions change real backup settings. **Last request** refers only to this browser session, not current backup state or a persistent audit history. Results lead with outcomes and next steps. Expand **Support details** for request IDs, target IDs/names, requested schedules, and error diagnostics; **Copy details** copies only that diagnostic payload, not authentication tokens. Server names may be sensitive: share details only with trusted support. Re-enable scheduling is a request, not a verified promise of recovery.

**Safe defaults:** simulated API only, no authentication bypass, no live changes without an explicit server-side gate, an operator role, and a typed confirmation. Azure CLI authentication is for infrastructure management; users still sign in to the app with MSAL.

**Release scope:** this is a reference demo, not a production backup-control
system or an officially supported Commvault client. Building the frontend requires
access to Microsoft's internal npm feed. No open-source license has been selected;
public distribution and reuse permissions require the owner's approval. See the
[publication guide](docs/publishing.md) before pushing or sharing source.

## Five-minute demo

1. Configure identity using the instructions below, or open your authorized
   deployment. Sign in with Microsoft and confirm the **DEMO** badge and
   **No real backups will change** notice.
2. Confirm that the three synthetic servers appear. Search for **Finance files**,
   select it, and open the red button's review dialog.
3. Review the target and the default 60-minute re-enable request. First choose
   **Cancel** to demonstrate that reviewing alone does not submit anything.
4. Reopen the dialog, type `DISABLE BACKUPS`, and confirm. The request changes
   only the private in-memory stub.
5. Explain **Request accepted** versus verified backup state. Expand **Support
   details** to see the request correlation information. Browser results are
   session-local; restarting the backend resets simulated state.

An operator needs the `BackupOperator` role on the API enterprise application.
When SPA assignment is required, assign access to that application too. The app
is single-tenant: external participants need approved guest onboarding and
assignments. A public URL does not grant anonymous access. Do not bypass Entra
or enable live operations just to make a demonstration easier to share.

## Architecture

Open the editable [architecture diagram](docs/architecture.drawio) with the VS Code Draw.io Integration extension or the draw.io desktop app. It shows the default simulated path and the optional live integration.

```text
Browser -- MSAL / authorization code + PKCE --> Microsoft Entra ID
   |
   | API access token (not an ID token)
   v
Python / FastAPI backend on Azure App Service
   | validate signature, issuer, audience, tenant, caller, expiry, scope
   | require BackupOperator role for mutations; record per-server audit events
   v
Shared Commvault HTTP client
   |-- stub mode --> private in-process HTTP stub, random per-process credential
   '-- live mode --> client's Commvault API, credential from Key Vault

Terraform: Azure resources + Entra registrations/scopes/roles
Managed identity: access to Key Vault; browser never receives upstream credentials
```

## Run locally

Prerequisites: **Python 3.12+**, plus Node 22.12+ and npm for the frontend build only. Access to Microsoft's internal npm feed is required. Azure CLI and Terraform are required for Azure setup.

Create an isolated Python environment using your supported interpreter (`python3.12`, `python3.13`, or `python3.14`; the macOS system Python 3.9 is too old):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Runtime dependencies are pinned in [requirements.txt](requirements.txt); pytest tooling is in [requirements-dev.txt](requirements-dev.txt). Use your organization's approved Python package index and CA trust configuration where required. The internal npm setting below applies to JavaScript dependencies, not pip.

### Internal npm repository is required

The project [`.npmrc`](.npmrc) pins:

```ini
registry=https://packagefeedproxy.microsoft.io/npm/
strict-ssl=true
audit=false
```

All npm package installation must use this internal registry, **not npmjs.org**. The lockfile's tarballs resolve to Microsoft's backing Azure Artifacts feed, `ms-feed-25.pkgs.visualstudio.com`. Do not replace these with public registry URLs. Automatic npm audit requests are disabled for feed compatibility; no dependency security audit is implied.

```bash
npm config get registry
npm ci
```

If the corporate TLS chain is not recognized by Node on macOS, use your organization's approved CA bundle. If your organization maintains trusted certificates in the system keychain, export those **public CA certificates**:

```bash
mkdir -p "$HOME/.config/red-button-demo"
security find-certificate -a -p /Library/Keychains/System.keychain \
  > "$HOME/.config/red-button-demo/system-ca.pem"
export NODE_EXTRA_CA_CERTS="$HOME/.config/red-button-demo/system-ca.pem"
npm ci
```

Do not turn off TLS verification, download an untrusted CA, or put registry credentials in the project. If feed authentication is required, use your approved organizational login process and a user-scoped npm configuration. The feed may not implement `npm ping`; a 404 on that endpoint alone does not establish that package downloads are unavailable.

### Configure identity

Follow [the infrastructure guide](docs/infrastructure.md) to provision the registrations and assign operators. Alternatively, use existing single-tenant registrations with equivalent API scope, v2 tokens, API app role, SPA authorization, and redirect URI.

For real sign-in with a locally hosted app only, use the guide's
[identity-only bootstrap](docs/infrastructure.md#identity-only-bootstrap-for-local-development).
It provisions Entra registrations and operator assignments without Azure hosting.
The Terraform SPA registration includes both `http://localhost:5173/` (Vite) and
`http://localhost:8080/` (Python serving the built UI). Use `localhost`, not
`127.0.0.1`, in the browser so the configured sign-in origin matches.

Copy `.env.example` to `.env` and set:

| Setting | Meaning |
|---|---|
| `ENTRA_TENANT_ID` | Client's Entra tenant GUID |
| `ENTRA_API_CLIENT_ID` | API app registration client GUID; v2 token audience |
| `ENTRA_SPA_CLIENT_ID` | SPA app registration client GUID |
| `PUBLIC_ORIGIN` | `http://localhost:5173` for Vite; exact origin, no trailing slash |
| `APP_ENV` | `development` locally; `production` requires configured Entra IDs |
| `PORT` | Python server port; `8080` by default |
| `COMMVAULT_MODE` | `stub` by default; `live` only for an approved integration |
| `ENABLE_LIVE_OPERATIONS` | `false` by default; independently blocks live writes |
| `APP_DISPLAY_NAME` | Public app name, default `Red Button`; 1-60 printable characters, not blank |
| `SUPPORT_URL` | Optional public HTTPS support destination; no credentials, whitespace, or backslashes; empty hides the link |

The cosmetic settings above are exposed by `/api/config` and require a server restart after changes. Never put secrets in them, including support URL query parameters. The display name changes the header, page title, heading, and footer, but cannot change safety labels, authentication, operator permissions, or live-operation gates. Terraform exposes the same options as `display_name` and `support_url`; infrastructure resource names still use `app_name`.

If Python cannot verify Entra's signing-key endpoint because of corporate TLS
inspection, set `SSL_CERT_FILE` in your local `.env` to your approved CA bundle.
The system-keychain export described above can supply the trusted corporate CA
certificates for Python as well as Node. Keep TLS verification enabled; do not commit a
workstation-specific certificate path or certificate bundle.

The SPA redirect URI must include the trailing slash, e.g. `http://localhost:5173/`. The API exposes delegated `api://<API-client-ID>/access_as_user`; mutations additionally require the API app role `BackupOperator`. Sign out and in after a role change.

```bash
# Terminal 1, with the Python virtual environment activated
python -m server --reload

# Terminal 2
npm run dev
```

Open <http://localhost:5173>. Without Entra IDs, the app shows a brief sign-in-unavailable message and all protected APIs return 503. Deployment details stay in this guide and the infrastructure documentation. This is intentional: there is no anonymous/local auth bypass.

To serve the production build locally, configure `PUBLIC_ORIGIN=http://localhost:8080` **and register** `http://localhost:8080/` as a SPA redirect URI first, then:

```bash
npm run build
python -m server
```

The UI lists all servers by default. Select up to 50, review names and IDs, choose a re-enable delay (60 minutes by default), and type `DISABLE BACKUPS`. The indefinite option must be selected explicitly. The UI reports each server's outcome, including partial failures.

## Commvault compatibility

Source documentation inspected September 22, 2026, labeled Latest/SP46:

* [Get Servers](https://api.commvault.com/docs/latest/api/cv/OpenAPI3/get-servers/): `GET /V4/Servers`
* [Disable Backups](https://api.commvault.com/docs/latest/api/cv/OpenAPI3/disable-backup-server/): `PUT /V4/Server/{serverId}/Backup/Action/Disable`

| Behavior | Implementation |
|---|---|
| List query | `showOnlyInfrastructureMachines=1` by default in the stub; `0` explicitly sent by the app for all servers |
| List envelope | `{ "totalServers": 3, "servers": [...] }` |
| Server fields | `id`, `name`, `displayName`, `hostName`, `OS`, `isInfrastructure`, plus documented optional fields |
| Disable success | `{ "errorCode": 0, "errorMessage": "" }` |
| Application errors | Nonzero `errorCode` fails even when HTTP status is 200 |
| Scheduling | Optional `enableAfterADelay` is an absolute UTC Unix timestamp in seconds, **not a duration**; optional `enableAfterDelayTimeZone` is an integer |
| Auth | Server-side configurable `Authorization` or `Authtoken` header; no Entra token forwarded upstream |
| Base URL | Preserves client API prefixes, e.g. `https://host/commandcenter/api` |
| Transport | HTTPS required in live configuration, 15-second request timeout, no redirects and no automatic retries |

The Python stub is a separate FastAPI application reached through HTTPX's **in-process ASGI transport**. The same HTTP client builds requests and validates responses in both modes, but stub requests do not open a network connection. Its endpoints are never mounted on the public application routes, and synthetic hosts are not contacted.

### Honest limits of the stub

This is a **two-operation compatible demo**, not a full Commvault emulator or a verified drop-in for an untested client version.

* The list API does not document a backup-enabled field. We do not invent one. “Request accepted” means the last command succeeded, not that current backup state has been queried.
* Fixture fields are a subset of the optional server schema. Extra real response fields are preserved by the adapter.
* Stub state and scheduled re-enables are in memory and reset on restart. Its clock-based schedule is evaluated when state is inspected in tests; it does not schedule real background jobs.
* Stub validation/error status codes are explicit demo choices: the linked pages do not specify a comprehensive error contract. Validate these against client responses before asserting exact compatibility.
* No login/token-refresh endpoint, paging extension, account-routing headers, batch endpoint, restore control, or running-job cancellation is emulated.
* Disabling backup activity is not a substitute for cancelling jobs, isolating hosts, or validating incident-response policy.

See [server/stub.py](server/stub.py), [server/commvault.py](server/commvault.py), and the [contract tests](tests/test_app.py).

## Switching to the client's service

1. Confirm the installed Commvault version, **exact API base prefix**, network access, auth header/value format, token lifetime, and required tenant/account headers. Capture sanitized fixtures from an authorized nonproduction environment. Do not send client data to external diagram or analysis services.
2. Run read-only contract checks against that approved environment first. Current automated tests use only the local stub and synthetic servers; no real backup changes are made.
3. Configure `COMMVAULT_MODE=live`, `COMMVAULT_BASE_URL`, `COMMVAULT_AUTH_HEADER`, and the secret `COMMVAULT_AUTH_VALUE`. Azure uses a Key Vault reference resolved by App Service's managed identity. Set the complete expected header value, including `Bearer ` only if required.
4. Keep `ENABLE_LIVE_OPERATIONS=false` while verifying discovery and permissions. There is no UI toggle that can bypass this gate.
5. Enable live mutations only after approval and confirmation of a rollback/re-enable procedure. A role-assigned operator must still type the confirmation.

No frontend changes are needed **if the client's two endpoints match this contract and supported auth settings**. Additional headers, different schemas or automated upstream credential renewal require an adapter extension.

## Verification

The [CI workflow](.github/workflows/validate.yml) runs publication guards, a
redacted secret scan, dependency advisory checks, Python/browser tests, the
frontend build, and Terraform mock tests. It never logs into Azure or deploys.
Runner feed access is required; see [CI setup](docs/publishing.md#continuous-integration).

```bash
npm run check
python -m compileall -q server
python -m pytest --cov=server
npm run build

# One-time browser install, not an npm registry fallback:
npm run test:install-browser
npm run test:e2e
```

Browser tests use synthetic MSAL/API responses at the test browser's network boundary; they exercise the real UI without weakening application authentication. Python tests validate real signed JWTs, rejection cases, HTTP adapter/stub behavior, partial results, role/live gates, confirmation, timeout handling, query defaults, exact re-enable timing, and overlapping requests. Actual tenant login, consent, Azure deployment and client compatibility need tenant/environment-specific verification.

For an approved existing Chrome executable, set `PLAYWRIGHT_CHROME_PATH` rather than downloading a browser.

## Deployment and operational scope

See [docs/infrastructure.md](docs/infrastructure.md) for the Python App Service runtime, Terraform, deployment packaging, permissions, and costs. Provisioning creates billable resources; inspect a plan before applying it. Never package `.env`, user `.npmrc`, state files or private keys. Build production Python dependencies on Linux for Azure; do not ship the macOS virtual environment or macOS native wheels.

Audit events are structured JSON on stdout: actor object ID, request ID, mode, target IDs and per-server result. Credentials and raw upstream error bodies are not logged. Audit retention/access controls need a production policy. Browser results are session-local, not a durable audit store.

This is a small, single-instance demo. It runs selected requests sequentially, limits batches to 50, and rejects concurrent overlapping server IDs within one process. A lost connection or timeout can have an unknown outcome: check Commvault/audit logs before retrying. For production or scale-out, add a durable work queue, cross-instance operation coordination, approval workflow, rate limits and operational reconciliation. Large sequential batches can exceed hosting request limits; use a background worker before expanding the demo's scope.

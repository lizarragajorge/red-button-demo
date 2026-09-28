# Azure infrastructure

This configuration supports full Azure deployment or an identity-only bootstrap
for local development. The commands below are instructions for an authorized
operator; inspect your local Terraform state to see which resources have actually
been provisioned.

## Architecture and defaults

- One Linux App Service runs Python 3.12 with `python -m server`.
  The canonical `server/__main__.py` entry point reads `PORT=8080` and binds
  `0.0.0.0` when `APP_ENV=production`; development binds `127.0.0.1`.
  `WEB_CONCURRENCY=1` explicitly keeps Uvicorn on a single worker.
  FastAPI serves the API and built Vite frontend. Python dependencies load from
  `.python_packages/lib/site-packages` through the configured
  `PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages`.
  Node is only a frontend build tool, not the deployed backend runtime.
- A dedicated B1 service plan is configurable with `service_plan_sku`. Always On,
  HTTPS, TLS 1.2 for both application and SCM, and HTTP/2 are enabled. FTP and
  publishing-profile basic authentication are disabled.
- `location` defaults to `eastus2`. If App Service quota is unavailable there,
  `app_service_location` can place only the plan and web app in another region.
  The resource group, monitoring and Key Vault stay in the primary region; review
  any cross-region data-residency and networking requirements before doing this
  for a client environment. App Service quota is separate from Azure VM vCPU
  quota and must be checked for the specific hosting SKU.
- A system-assigned managed identity receives **Key Vault Secrets User** on this
  demo's vault. The vault uses RBAC, seven-day soft deletion, and purge protection.
  Terraform does not create/read any vault secret or create application passwords.
- A workspace-based Application Insights web resource exposes its connection
  string to the app. App Service console, HTTP, application, and platform
  logs plus metrics go to Log Analytics; vault audit events and metrics do too.
  Python request/dependency traces
  require separately configured Python instrumentation; the connection string
  alone does not instrument FastAPI. No unverified agent or restore is enabled.
- Workspace retention is 30 days with a 1 GB/day ingestion cap. The cap is not a
  hard spending guarantee and can interrupt diagnostics when reached.
- Two Entra registrations represent the API and the public SPA; they remain
  single-tenant by default (see opt-in organizational multi-tenant access below).
  The API requests v2 access tokens, exposes `api://<api-client-id>/access_as_user`,
  and defines the user app role `BackupOperator`. Its v2 audience is the API
  **client GUID**, not the `api://` scope prefix. The SPA uses authorization code
  with PKCE through MSAL, without a client secret or implicit grant.
- Redirect URIs are exactly `https://<app-name>.azurewebsites.net/`,
  `http://localhost:5173/`, and `http://localhost:8080/`. The SPA is preauthorized
  for the API's delegated scope.
- `COMMVAULT_MODE=stub` and `ENABLE_LIVE_OPERATIONS=false` are defaults. The
  shared Commvault client sends HTTP requests through a private in-process
  `httpx.ASGITransport` to the stub, preserving the HTTP request/envelope semantics.
  The stub opens no external or loopback socket. No authentication bypass is
  enabled.

For client branding, set `display_name` (default `Red Button`) and optionally
`support_url` in your local tfvars. Terraform passes these as `APP_DISPLAY_NAME`
and `SUPPORT_URL`. Both are public UI configuration, never secrets; the support
URL must use HTTPS without credentials or whitespace. An empty URL hides the
support link. These settings do not alter resource names, identity, the Demo/Live
warnings, or operational safety gates.

The app uses a public HTTPS endpoint. Vault public networking is configurable
with `key_vault_public_network_access_enabled` (default true); restricted stub
deployments can set it to false to match subscription policy because the stub
does not use a vault secret. Vault access still requires RBAC. Before enabling
live mode, establish an approved network path from App Service to the vault:
disabling public access alone does not create private endpoints or VNet routing.
Network-private production deployments require a separate design
for VNet integration, private endpoints, DNS, and deployment ingress. Do not simply
disable vault networking: App Service must be able to resolve its references.

## Opt-in queued three-tier mode

`enable_three_tier = false` and `enable_gateway_ingress = false` preserve the
existing synchronous hosted demo. Neither storage, Functions, a gateway, nor
queued-mode settings are introduced until explicitly enabled. The defaults are
for a fresh receiving-team deployment, not a statement about the resources
already running in a particular subscription.

### Storage networking switch

The receiving team chooses **one Terraform boolean** in its own tfvars file.
Copy `infra/terraform.tfvars.example`, not another team's local tfvars or state.

**Simpler setup, where public storage endpoints are permitted:**

```hcl
enable_three_tier                  = true
enable_private_storage_networking = false
```

**Private-only storage, where required by the receiving environment:**

```hcl
enable_three_tier                  = true
enable_private_storage_networking = true
```

| Behavior | `false` (default) | `true` |
|---|---|---|
| Storage network access | Public HTTPS endpoints | Private Blob/Queue endpoints; public access disabled |
| Extra networking | None for storage | Four private endpoints, two private DNS zones/links, dedicated VNet/subnets, both apps integrated |
| Authentication | Managed identity + Entra tokens | Same |
| Authorization | Scoped RBAC | Same |
| Anonymous blob / shared-key access | Disabled | Disabled |

The toggle covers **both work and Functions host storage**. It does not change
the API/UI code, storage data model, queue processing, app roles, or live-write
gate. Application Gateway, APIM, and Key Vault networking remain independent.
No NSP is provisioned.

This is a **deployment-time switch**, not an in-app switch or automatic policy
detection. Review `terraform plan` before applying it. A receiving subscription
that enforces private-only access must use `true` unless an approved alternative
is available. On an existing deployment, switching to `false` removes networking
resources and can interrupt connectivity; follow the
[migration precautions](#changing-storage-networking-on-an-existing-deployment)
before applying. Preserve `activate_queued_execution` separately; changing the
storage network choice must not accidentally activate or pause processing.

### Queued resources and permissions

With `enable_three_tier = true`:

- When `activate_queued_execution=true`, the existing web app gets
  `EXECUTION_MODE=queued` and `STORAGE_ACCOUNT_NAME`.
  Its system-assigned identity can read/write request blobs, read inventory, and
  send messages to the `requests` queue; it cannot consume that queue.
- One Standard LRS StorageV2 **work** account contains private Blob containers
  `requests`, `inventory`, `coordination`, `stub-state` and queues `requests`,
  `requests-poison`. Public blob access and shared-key authentication are disabled;
  HTTPS/TLS 1.2 and OAuth defaults are enabled. AzureRM 5.6 resources use ARM
  container/queue IDs, so initial creation does not wait for the application's
  data-plane RBAC propagation. The networking switch above determines whether
  endpoints are public or private; private containers alone do not mean private
  networking.
- A separate **host** storage account isolates Functions host leases/receipts.
  Host account-level `Storage Blob Data Owner` and `Storage Queue Data Contributor`
  do not grant access to application data. No account-management role is assigned
  to the worker. Work permissions are scoped to each container and queue:
  `Storage Blob Data Contributor` on the four containers and `Storage Queue Data
  Contributor` on both queues. The latter supports triggers, retries and poison
  enqueue/dequeue. Built-in Blob Contributor includes read/delete as well as
  inventory write; custom write-only role definitions are not managed here.
- A Python 3.12 Linux Function App, Functions runtime `~4`, shares the existing
  dedicated B1 Linux plan with Always On. There is **no additional Premium or
  Consumption plan**. Web and worker share the B1 CPU/memory budget; capacity,
  execution throughput and failure isolation must be load-tested before production.
  Queue, timer and poison handlers come from root `function_app.py` and `host.json`;
  Terraform configures infrastructure, not their deployment.
- Host storage uses `storage_uses_managed_identity=true`,
  `AzureWebJobsStorage__accountName` and `AzureWebJobsStorage__credential`.
  Queue bindings use `WORK_STORAGE__queueServiceUri` plus managed identity.
  `APP_ENV=production`, `PUBLIC_ORIGIN` and all three `ENTRA_*` IDs satisfy the
  shared application Settings validation; they are public identifiers, not
  credentials. Inventory refresh runs at `0 */5 * * * *` (UTC), with maximum
  age `900` seconds. Runtime queue bindings require the extension bundle declared
  in `host.json`; allow its documented outbound download endpoints.
- Worker and web share `COMMVAULT_MODE`, the effective HTTPS base URL, auth
  header and `ENABLE_LIVE_OPERATIONS`. Stub mode injects no Commvault credential.
  Only live mode adds the worker's Key Vault Secrets User grant and a versionless
  `@Microsoft.KeyVault(...)` reference. Existing default web-vault RBAC is retained.
  No secret value or storage connection string is passed to either application.

AzureRM storage accounts expose sensitive computed key/connection-string
attributes. Even with shared-key authentication disabled and no key references
in app configuration, **do not claim Terraform state is secret-free**: provider
refresh may persist computed credentials. Protect state/backups with encryption
and restricted access; never publish or package them. This configuration does
not read certificate or Commvault secret values. No local tfvars/state is edited
as part of this feature.

RBAC assignments can exist before Azure data-plane authorization propagates.
After an authorized apply, wait for effective identity access, deploy the worker,
confirm queue and timer indexing, and wait for a successful inventory refresh
before allowing operators to use queued mode. Verify poison handling, duplicate
delivery/idempotency, restart recovery and stale-inventory behavior in a separate
test environment. Mock Terraform tests do not prove those Azure behaviors.
`Microsoft.Storage` must be registered by an authorized administrator.

### Existing APIM integration, not a new APIM deployment

`existing_apim_base_url` accepts an existing HTTPS DNS URL and optional API path.
It requires three-tier **live** mode and an empty `commvault_base_url`, avoiding
ambiguous routing. It becomes `COMMVAULT_BASE_URL` for web and worker. It does not
enable live operations automatically; the separate live gate still applies.

No paid APIM instance, API definition, policy, backend, subscription key or stub
host is created. An operator must supply and verify the existing APIM routes,
authentication/authorization policy, network reachability, TLS trust, credential
forwarding and backend contract. The application's demonstrated paths/envelopes
are **not verified Commvault product API names**. Do not point at production until
the actual Commvault version/API contract is verified. The built-in stub remains
private in-process code; routing APIM to a separately hosted stub requires a
separate secured deployment and integration. A configured URL or a passing plan
is not evidence of a working APIM route.

### Optional HTTPS-only gateway ingress

`enable_gateway_ingress=true` additionally requires three-tier mode,
`gateway_hostname`, a versionless existing `gateway_certificate_secret_id`, and
its matching `gateway_certificate_vault_id`. The vault must use RBAC and contain
an enabled, unexpired, exportable PFX certificate with the hostname in its SAN.
The secret URI is referenced directly, never read into Terraform. The
gateway's user-assigned identity receives Key Vault Secrets User on that existing
vault. Approve its network path (including vault firewall/trusted-service rules)
and allow RBAC propagation before expecting TLS readiness.

The actual gated resources are a dedicated RFC1918 VNet, validated contained /24
subnet, NSG, Standard static public IP and **WAF_v2 Application Gateway**. The only
public listener is HTTPS 443 with SNI and a TLS 1.2+ policy; there is no public
HTTP listener. WAF runs in Prevention mode. Backend TLS uses the existing
`<app-name>.azurewebsites.net` hostname and `/api/health` probe. Microsoft.Web
service endpoints identify the gateway subnet to App Service access restrictions;
direct web ingress is denied. These are not private endpoints.

Gateway creation is a dependency of the web app update, so a failed gateway
provisioning operation does not deliberately open an insecure fallback or apply
new restrictions first. Successful provisioning is still **not** proof of correct
DNS, healthy probes or TLS, and a partial apply can interrupt availability.
Schedule a maintenance window and stage tested artifacts first. Set the public
DNS A record to `gateway_public_ip`; Terraform does not manage DNS records.
`PUBLIC_ORIGIN` and the SPA redirect URI change to the gateway hostname.
Entra validation and BackupOperator authorization remain enabled; existing scope
and role UUIDs stay stable when switching origins.

SCM/deployment ingress is separately denied by default in gateway mode. Supply
only approved fixed deployment egress addresses in `gateway_scm_allowed_cidrs`
(`/24`–`/32`, preferably `/32`) before needing web zip updates. No gateway route
exposes SCM; Entra deployment authorization and disabled publishing passwords
remain in force. The worker has no HTTP business trigger; its public HTTPS/SCM
management surface remains protected by Azure authorization, not by this gateway.
Private worker/deployment ingress is a separate network design.

CIDR syntax, canonical ranges, containment, required inputs and matching vault
names are checked locally. Existing VNet overlap, certificate validity, vault
network/RBAC readiness, DNS, quotas, WAF compatibility and real backend access
restrictions cannot be proved by mocks. Validate public gateway success and
direct App Service rejection before declaring ingress complete.
`Microsoft.Network` must be registered separately.

Costs: the worker shares B1 rather than adding a compute SKU, but adds two LRS
accounts, transactions/capacity, Function telemetry and potentially egress.
The opt-in WAF_v2 gateway and Standard public IP add substantial ongoing charges
even when idle. Reusing existing APIM does not create a new instance, but its
existing tier/capacity and request costs still apply. Nothing is cost-free.

## Tools, credentials, and permissions

Use Terraform >=1.9 and <2.0 and a recent Azure CLI. Provider patch versions are
constrained in [versions.tf](../infra/versions.tf); commit the generated
[dependency lock file](../infra/.terraform.lock.hcl). The current lock selects
AzureRM 5.6.0 and AzureAD 3.9.0; this AzureRM version accepts Python `3.12`.
The backend runtime is fixed to Python 3.12.

The commands in this guide assume `terraform` is on your shell's `PATH`. Install
an approved version using your organization's software distribution or the
[official HashiCorp installation instructions](https://developer.hashicorp.com/terraform/install).
For a portable installation without administrator access, download the official
archive for your operating system/architecture, verify its published checksum,
and extract the executable into a user-owned directory. Then select that directory
in each shell where you run this guide:

```sh
export PATH="/absolute/path/to/terraform-bin:$PATH"
command -v terraform
terraform version
```

Replace the example directory with your actual portable installation directory.
A portable binary is not installed globally and does not automatically become
available on `PATH`. Do not commit
the binary or workstation-specific paths to the project.

For local development, `az login` authenticates the **Terraform operator** to ARM
and Microsoft Graph. Set the desired subscription before running Terraform.
The AzureAD provider derives its tenant from `azurerm_client_config`, so no
tenant ID needs to be checked into configuration. Use a CLI account in that
tenant, and avoid conflicting `ARM_*` authentication variables.

Azure CLI login does **not** authenticate browser users to the app. MSAL uses the
new SPA registration, requests an API token for the signed-in user, and the
backend validates that token and the operator role. Azure subscription Owner
does not automatically confer Entra directory administration or BackupOperator.

The provisioning identity needs:

1. ARM rights to create the resource group and resources, plus
   `Microsoft.Authorization/roleAssignments/write` to grant the managed identity
   vault access (for example Contributor plus Role Based Access Control
   Administrator, appropriately scoped; or Owner).
2. Entra application/service-principal management and user app-role assignment
   privileges. An interactive **Application Administrator** is a common choice;
   tenant policy may require an administrator's participation.
3. For later unattended provisioning, appropriately admin-consented Microsoft
   Graph **application** permissions. `Application.ReadWrite.OwnedBy` can manage
   owned registrations/service principals (the configuration records the caller
   as owner). User role assignments additionally require
   `AppRoleAssignment.ReadWrite.All` with `Application.Read.All` (or the broader
   alternatives documented by the AzureAD provider). User-owner resolution may
   also require `User.Read.All`. Prefer an approved federated provisioning
   identity; do not create a client secret in Terraform.

Resource-provider auto-registration is disabled to avoid writes during a normal
plan. Before a real apply, an authorized subscription administrator must ensure
`Microsoft.Web`, `Microsoft.Insights`, `Microsoft.OperationalInsights`, and
`Microsoft.KeyVault` are registered. Registration is a separate remote operation.
Subscription policy, quotas, runtime availability and name availability cannot
be verified by local validation.

## Local validation (no cloud operations)

From the repository root:

```sh
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
terraform -chdir=infra test
```

Initialization downloads signed provider packages and writes the lock file; it
does not provision anything. All tests use mock providers and `command = plan`;
they do not contact Azure or Graph. Tests cover the environment contract, safe
defaults, Python 3.12/module-startup/PYTHONPATH configuration, disabled remote builds,
v2 audience configuration, role/redirect/preauthorization wiring,
optional assignments, live Key Vault references and rejected unsafe inputs.

## Identity-only bootstrap for local development

To use real MSAL sign-in without deploying Azure hosting, populate local
`infra/terraform.tfvars` with `subscription_id`, a unique `app_name`, and your
tenant user object ID in `operator_object_ids`. Set `spa_assignment_required=true`
to restrict both applications to assigned operators.

For this one-time partial bootstrap, explicitly target only the identity graph:

```sh
terraform -chdir=infra init -input=false
terraform -chdir=infra plan -out=identity.tfplan \
  -target=azuread_application_identifier_uri.api \
  -target=azuread_application_pre_authorized.spa \
  -target=azuread_service_principal.api \
  -target=azuread_service_principal.spa \
  -target=azuread_app_role_assignment.operator \
  -target=azuread_app_role_assignment.spa_access
# Inspect the plan: only Entra applications, service principals and assignments.
terraform -chdir=infra apply identity.tfplan
terraform -chdir=infra output -raw tenant_id
terraform -chdir=infra output -raw api_client_id
terraform -chdir=infra output -raw spa_client_id
```

Targeting is intentional here, not the normal deployment workflow. Terraform
warns that unrelated configuration and outputs are incomplete; a later untargeted
apply would create the hosting stack. Preserve the local state and tfvars so
these same registrations can be managed rather than recreated. Delete the saved
plan after applying it.

Copy `.env.example` to `.env`, set the three `ENTRA_*` IDs from the outputs, and
set `PUBLIC_ORIGIN=http://localhost:8080`. Keep `COMMVAULT_MODE=stub` and
`ENABLE_LIVE_OPERATIONS=false`. Build with `npm run build`, start with
`python -m server`, and visit **http://localhost:8080/** (not `127.0.0.1`,
which is a different redirect origin). Click **Sign in with Microsoft**.
The Azure CLI session cannot replace this browser sign-in; complete any
Microsoft authentication or MFA prompts yourself.

## Operator-run provisioning

These commands **do** access Azure; `apply` creates billable resources and Entra
objects. Do not run an untargeted apply when you only want local identity setup.

```sh
az login
az account set --subscription "<subscription-id>"
export TF_VAR_subscription_id="$(az account show --query id -o tsv)"
export TF_VAR_app_name="<globally-unique-lowercase-app-name>"

terraform -chdir=infra init
terraform -chdir=infra plan -out=demo.tfplan
# Review resources, cost, tenant, role assignments and settings before approval.
terraform -chdir=infra apply demo.tfplan
terraform -chdir=infra output
```

Alternatively copy [terraform.tfvars.example](../infra/terraform.tfvars.example)
to `infra/terraform.tfvars` and fill it locally. Never commit real tenant,
subscription or operator IDs. The repository ignore file already excludes local
tfvars, plans, state and `.terraform/`; retain the lock file. State still contains
resource/account metadata and the Application Insights ingestion connection
string. Protect state and plan files even though no Commvault credential or
application password is placed in state. For shared use, configure an encrypted,
access-controlled remote backend with locking before the first apply; the demo
intentionally defaults to local state and does not create a backend.

### Operator roles and consent

Set `operator_object_ids` to tenant **user object IDs**, not app/client IDs.
Terraform grants each user BackupOperator on the **API enterprise application**.
The default is an empty list and `api_assignment_required=true`, so no ordinary
user can obtain useful operator access until explicitly assigned.

`spa_assignment_required=false` lets tenant users sign in to the SPA, but does
not grant API access. Set it to true to also assign each listed operator the
SPA's default access role and restrict SPA sign-in. Disabling API assignment
restrictions never disables the backend's role and scope checks. Sign out/in
after assignments to obtain a fresh access token containing the role.

The API scope is admin-consent-only; SPA preauthorization is explicitly managed
in Terraform and normally removes the end-user consent prompt for that scope.
Tenant consent policy or assignment-required settings can still require an
administrator to grant tenant-wide consent for the SPA's declared delegated API
permission in **Entra > App registrations > SPA > API permissions > Grant admin
consent**. Do not confuse this with granting Graph privileges to the provisioning
identity. No Graph delegated permission is required by the demo SPA itself.
The configuration does not automatically create tenant-wide OAuth consent grants.
Consent does not grant BackupOperator; both authorization requirements matter.

### Opt-in organizational multi-tenant access

The default `enable_multi_tenant=false` and `allowed_tenant_ids=[]` retain both
registrations' `AzureADMyOrg` audience and existing app settings. To approve
external organizations, set both inputs together in your local tfvars:

```hcl
enable_multi_tenant = true
allowed_tenant_ids  = ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
```

Supply 1–20 **additional tenant GUIDs**, not domains, tenant names, `common`, or
`organizations`. IDs must use the canonical hyphenated GUID format; letter case
is accepted and normalized to lowercase. The home tenant from the Azure provider
is always implicitly allowed and must not be listed. Personal Microsoft accounts
and the consumers tenant `9188040d-6c67-4c5b-b112-36a304b66dad` are not supported.
Terraform rejects an empty allowlist when enabled, a nonempty one when disabled,
malformed/consumer/home IDs, and lists exceeding 20 entries.

When enabled, both API and SPA use `AzureADMultipleOrgs`. The API identifier URI
remains `api://<api-client-guid>`; the v2 access-token audience remains the API
client GUID. Terraform adds `ENTRA_MULTI_TENANT=true` and comma-separated,
lowercase, sorted `ENTRA_ALLOWED_TENANT_IDS` to the web app and, if provisioned,
the Functions worker. When disabled these two settings are omitted, preserving
default plans; the runtime defaults are `false` and an empty string. The browser
uses the `organizations` authority only when enabled. The API verifies the
token's tenant and tenant-specific issuer against the home tenant plus allowlist,
in addition to signature, expiry, audience, and delegated scope checks. A
multi-tenant registration alone does not allow arbitrary organizations.

Approved external-tenant users with the delegated `access_as_user` scope can
read data; **actions still require the API's `BackupOperator` role**. Allowlisting
an organization is therefore a deliberate read-access trust decision, not an
operator assignment. Neither allowlisting nor admin consent grants that role.
The scope remains **admin-consent-only**. External tenant administrators must
approve consent and manage their own API/SPA enterprise applications, assignment
policies, and remote service-principal role assignments. SPA preauthorization
does not replace an external organization's consent and assignment policies.

Enabling this option does **not** weaken the home tenant's
`api_assignment_required=true` default or change `spa_assignment_required`
(false by default). `operator_object_ids` provisions only home-tenant API
operator assignments (and optional local SPA access); do not put external user
object IDs in it. This Terraform does not create or administer remote enterprise
applications, remote consent grants, or remote role assignments. Arrange those
with each external administrator and obtain fresh tokens after assignment changes.

## Build and deploy the application

The SPA registers both `/` (interactive sign-in) and `/auth/silent` (silent token
renewal) at the hosted origin and both localhost origins. The silent callback is
a script-free page: MSAL in the parent reads its URL fragment. It must not load
the application/router or rewrite the fragment. The dashboard permits same-origin
frames, but only this callback permits same-origin embedding; the dashboard and
APIs retain `frame-ancestors 'none'` and `X-Frame-Options: DENY`. The callback uses
`frame-ancestors 'self'`, `SAMEORIGIN`, and `Cache-Control: no-store`.

Deploy the registered callback URI before the frontend that requests it. A
`monitor_window_timeout` with a browser CSP framing error is a sign-in failure,
not evidence that `BackupOperator` is missing. Retry sign-in after correcting
the callback/CSP configuration; confirm `/api/me` succeeds before diagnosing role
assignments. Do not relax token validation or permit cross-origin embedding.

**Chosen process: build the frontend, stage and test Python dependencies on a
compatible Linux CI runner/container, then upload a ready-to-run zip.** The
platform-independent frontend assets may be built on macOS using dependencies
already restored from the required internal npm feed. Python dependencies must
be staged and executed on the Linux target platform, not copied from a macOS
virtualenv. Terraform sets
`SCM_DO_BUILD_DURING_DEPLOYMENT=false`: Azure must not run npm, pip, or Vite restores
or builds. `APP_ENV=production` replaces the removed `NODE_ENV` app setting and
activates the Python backend's production configuration checks.
All `ENTRA_*`, origin,
Commvault, and live-operation settings retain their meanings.

Use CPython **3.12 on glibc Linux x86_64**, matching this App Service runtime's
architecture and ABI. Use an approved compatible build image pinned by digest;
do not use an Alpine/musl image. In particular, **never bundle a macOS virtualenv,
macOS wheels, or macOS site-packages for Azure Linux**. Cryptography and
pydantic-core include native code. Building Vite on macOS does not make Python
dependencies portable. The recipe below fails immediately outside Linux x86_64.

**Microsoft's internal npm repository is mandatory.** The confirmed registry is
`https://packagefeedproxy.microsoft.io/npm/`; the lockfile resolves tarballs through
the approved internal mirror `https://ms-feed-25.pkgs.visualstudio.com`.
Never fall back to public npm. Terraform's provider registry is separate and is
unaffected by this requirement.

The project's `.npmrc` is credential-free: it pins that registry,
`strict-ssl=true`, and `audit=false`. Copy it into the frontend build directory for
installation, but exclude it from the deployment archive. The preflight below
checks its exact allowed settings before copying. If additional authentication
is required, use Microsoft's approved internal-feed procedure with an optional
authenticated user `.npmrc` **outside the repository and all staging/artifact
directories**, with owner-only permissions (for example mode 600). Set
`NPM_CONFIG_USERCONFIG` to that private file's absolute path only when needed.
Authentication must be scoped to the approved internal hosts/paths, never embedded
in a registry URL. No new token is needed just to copy the credential-free project
configuration.

Do not copy the authenticated file, print its contents, enable shell tracing, or
run npm config dumps in logs. Tokens must never appear in source, lockfiles,
staging directories, zip artifacts, `VITE_*`, Azure settings, Terraform variables,
plans, or state. Keep any credential-bearing environment supplied by approved
authentication tooling local to the packaging shell; never make it a build input.

Preserve TLS verification. If an approved public CA bundle is required, use it as
`NODE_EXTRA_CA_CERTS` in the packaging shell before starting Node/npm. For example,
`export NODE_EXTRA_CA_CERTS="/absolute/path/to/system-ca.pem"`. See the
[README](../README.md) for the system trust setup; do not copy its CA bundle into
staging or the zip. Never set `strict-ssl=false` or
`NODE_TLS_REJECT_UNAUTHORIZED=0`. The CA bundle contains public trust certificates,
not npm credentials, and Azure needs neither the local CA workaround nor registry
credentials for this prebuilt deployment.

Use Node 24 (or >=22.12), npm, Python 3.12 with venv/pip, and `zip`/`unzip` on
that Linux builder. Configure an approved Python package index separately through
external pip configuration/credential tooling; the internal npm proxy is not a
Python index. Do not put index credentials in `requirements.txt`, source,
staging, or the archive, and do not silently fall back to another index. Keep
TLS verification enabled for both package managers.

Run the following in **Bash from the repository root on the Linux builder**, using
the reviewed `requirements.txt` and npm manifests/lockfile.
Production requirements include FastAPI, Uvicorn, HTTPX, `PyJWT[crypto]` (or
PyJWT plus its resolved cryptography dependencies), and python-dotenv. Direct
version bounds can be used during development, but can resolve differently on
later builds; pin the tested full dependency set for reproducible releases.
`requirements-dev.txt` is for tests only and is never installed into the artifact.
Keep the builder, pip and Node/npm versions fixed for repeatable resolution.
`npm ci` fails on manifest/lockfile mismatches rather than changing the lockfile.

Local development on another Python version does not prove Python 3.12
compatibility. Before staging, check the pinned
set for CPython 3.12 Linux wheels with an approved Python index. This download-only
check can run on macOS and must not be confused with a Linux runtime smoke test:

```sh
WHEELS="$(mktemp -d "${TMPDIR:-/tmp}/red-button-cp312-wheels.XXXXXX")"
python -m pip download --disable-pip-version-check --only-binary=:all: \
  --python-version 3.12 --implementation cp --abi cp312 \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --dest "$WHEELS" -r requirements.txt
```

Use the packaging environment's Python/pip executable for this preliminary check.
It tests wheel availability and resolution for the requested tags; it does not
load native libraries or prove all conditional dependencies under a real 3.12
interpreter. If it fails, review the incompatible pins with the maintainer rather than
silently changing requirements or Azure's runtime. The actual staging/import
checks below must still run on compatible Linux with Python 3.12.

```bash
set -euo pipefail
python3.12 -c 'import platform, sys; assert sys.version_info[:2] == (3, 12) and sys.platform == "linux" and platform.machine() == "x86_64", "Build Python packages on matching Linux x86_64 with Python 3.12"'
export NPM_CONFIG_REGISTRY="https://packagefeedproxy.microsoft.io/npm/"
export NPM_CONFIG_STRICT_SSL=true
export NPM_CONFIG_AUDIT=false
export NPM_CONFIG_FUND=false
export NPM_CONFIG_IGNORE_SCRIPTS=true
ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/red-button-package.XXXXXX")"
BUILD="$WORK/build"
BUNDLE="$WORK/bundle"
ARCHIVE="$WORK/red-button.zip"

# Fail closed on external/userinfo-bearing tarball URLs or misplaced credentials.
ROOT="$ROOT" WORK="$WORK" node --input-type=module <<'NODE'
import assert from "node:assert/strict";
import { readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
const root = realpathSync(process.env.ROOT);
const work = realpathSync(process.env.WORK);
if (process.env.NPM_CONFIG_USERCONFIG) {
  assert.ok(isAbsolute(process.env.NPM_CONFIG_USERCONFIG), "Use an absolute userconfig path");
  const config = realpathSync(process.env.NPM_CONFIG_USERCONFIG);
  for (const directory of [root, work]) {
    const path = relative(directory, config);
    assert.ok(path.startsWith("../") || isAbsolute(path), "Keep authenticated npm config outside source and staging");
  }
}
assert.notEqual(process.env.NODE_TLS_REJECT_UNAUTHORIZED, "0", "TLS verification must remain enabled");
const settings = readFileSync(resolve(root, ".npmrc"), "utf8")
  .split(/\r?\n/).map(line => line.trim()).filter(Boolean);
const allowedSettings = new Set([
  "registry=https://packagefeedproxy.microsoft.io/npm/", "strict-ssl=true", "audit=false"
]);
assert.ok(settings.length === allowedSettings.size && [...allowedSettings].every(line => settings.includes(line)),
  "Project .npmrc must contain only the three credential-free approved settings");
const registry = new URL(process.env.NPM_CONFIG_REGISTRY);
assert.equal(registry.href, "https://packagefeedproxy.microsoft.io/npm/");
const prefix = registry.pathname.replace(/\/?$/, "/");
const lock = JSON.parse(readFileSync(resolve(root, "package-lock.json"), "utf8"));
assert.ok(lock.packages, "Use the committed npm v2/v3 lockfile");
for (const [name, entry] of Object.entries(lock.packages)) {
  if (name === "") continue;
  assert.ok(entry.resolved && entry.integrity, `Missing locked registry artifact: ${name}`);
  const url = new URL(entry.resolved);
  const approved = (url.origin === registry.origin && url.pathname.startsWith(prefix)) ||
    url.origin === "https://ms-feed-25.pkgs.visualstudio.com";
  assert.ok(approved &&
    !url.username && !url.password && !url.search && !url.hash,
    `Artifact must resolve through the approved internal registry: ${name}`);
}
NODE

mkdir "$BUILD" "$BUNDLE"

# Copy build inputs, never the working tree's node_modules or environment files.
cp "$ROOT/package.json" "$ROOT/package-lock.json" "$ROOT/.npmrc" \
  "$ROOT/index.html" "$ROOT/vite.config.js" "$BUILD/"
cp -R "$ROOT/web" "$BUILD/"
(
  cd "$BUILD"
  npm ci --include=dev
  npm run build
)

# Stage only Python source, built frontend assets, and production dependencies.
mkdir "$BUNDLE/server"
cp "$ROOT"/server/*.py "$BUNDLE/server/"
cp "$ROOT/requirements.txt" "$BUNDLE/"
cp -R "$BUILD/dist" "$BUNDLE/"
python3.12 -m venv "$WORK/python-tools"
PYTHON="$WORK/python-tools/bin/python"
PACKAGES="$BUNDLE/.python_packages/lib/site-packages"
"$PYTHON" -m pip install --disable-pip-version-check --only-binary=:all: \
  --no-compile --target "$PACKAGES" -r "$BUNDLE/requirements.txt"
(
  cd "$BUNDLE"
  PYTHONPATH="$PACKAGES" "$PYTHON" -m pip check
  PYTHONPATH="$PACKAGES" "$PYTHON" -c \
    'import fastapi, uvicorn, httpx, jwt, dotenv, pydantic_core; from cryptography.hazmat.bindings import _rust; print("Production Python imports passed")'
  test -f dist/index.html
  test -f server/main.py
  test -f server/__main__.py
  test ! -d node_modules
  # Explicit allowlist: no build tools, Node server, dev requirements, or credentials.
  zip -q -r "$ARCHIVE" dist server requirements.txt .python_packages \
    -x '*/__pycache__/*' '*.pyc'
)
unzip -tq "$ARCHIVE"
printf 'Ready-to-run archive: %s\n' "$ARCHIVE"
```

`--include=dev` makes Vite available even when npm would otherwise omit development
dependencies. Only the resulting `dist/` is copied into the Python
artifact; no production npm install is needed. The frontend install uses the
copied credential-free project `.npmrc`, explicit internal registry setting,
and any approved external user configuration selected by the packaging shell.
The preflight requires every locked npm tarball to
resolve through the proxy or the exact approved internal Azure feed origin above;
changing npm's default registry alone does not rewrite public `resolved` URLs in
an existing lockfile. If the check fails, stop and have the maintainer fix/approve
the lockfile before packaging. Additional mirror hosts require explicit approval;
do not permit all `visualstudio.com` hosts or arbitrary hosts, silently substitute
a registry, or modify the lockfile during packaging.

Npm lifecycle scripts are disabled to prevent dependency installers
from downloading binaries independently of the approved registry. `npm run build`
still executes the explicit Vite build; npm pre/post hooks do not run. The current
Vite/esbuild build relies on the platform-specific optional package supplied by
the internal feed. If the feed lacks that package, stop and have the feed owner
resolve it; do not enable public download fallbacks. Any future dependency that
requires lifecycle scripts needs a separate approved build procedure.

The pip install uses only wheels selected for the Linux/Python builder; if an
approved compatible wheel is unavailable, stop rather than copying macOS packages
or changing platforms. `--no-compile` and the zip exclusions avoid packaging
temporary bytecode. The temporary Python tooling virtualenv is not deployed.
If Python source gains nested packages or runtime data files, update the explicit
source allowlist accordingly; do not copy the entire working tree.

This process does not mutate source/dependencies or reuse stale `dist/`.
**Python packaging validation status (September 23, 2026): Linux archive build
and extracted-archive runtime smoke test passed.** The 42 pinned dependencies
were downloaded as CPython 3.12-compatible Linux/universal wheels through the
workstation's configured Microsoft Python feed,
`https://packagefeedproxy.microsoft.io/pypi/simple/`, with TLS verification enabled.
They were installed offline in a Python 3.12.14 Linux x86_64 container, using the
official `python:3.12-slim-bookworm` image pinned to
`sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`.
Native CFFI, cryptography, and pydantic-core dependencies loaded successfully.
The extracted ZIP passed `pip check`, production startup, health/configuration,
HTML/assets, production-header, and anonymous GET/POST rejection checks.
Temporary build containers and the test server were stopped and removed.
Terraform's mock tests validate configuration separately from this runtime
test. Rebuild and repeat these checks whenever deployment inputs change.

If a Linux builder cannot access the approved package feed directly, download
the target wheels on the trusted workstation using the wheel command above and
your approved pip configuration. Mount only that wheel directory and the
allowlisted staging directory into the Linux builder. Install without network
access or a public-index fallback:

```sh
python3.12 -m pip install --no-index --find-links=/path/to/wheels \
  --only-binary=:all: --no-compile --target "$PACKAGES" \
  -r "$BUNDLE/requirements.txt"
```

This still requires all import, dependency, and extracted-archive runtime checks
to execute on Linux. Do not copy workstation credentials or CA bundles into the
deployment ZIP.

The resulting **web** zip must have exactly four top-level entries: `dist/`, `server/`,
`requirements.txt`, and `.python_packages/`, with no enclosing directory. It must
contain no `.env`, npm/pip configuration, CA bundles, Terraform files/state,
project tests, old JavaScript server files, npm manifests, `node_modules`,
frontend source, or Vite configuration.

Before deployment, extract the zip into a clean directory on the same Linux
runtime, verify that allowlist, run the production import checks above using the
**extracted** site-packages, and run `python -m server` with synthetic valid GUIDs for all
three `ENTRA_*` settings, `APP_ENV=production`, `WEB_CONCURRENCY=1`, stub mode,
and live operations disabled. Set
`PYTHONPATH` to the extracted `.python_packages/lib/site-packages` locally (the
Azure absolute path is for App Service only). Confirm health, runtime config,
HTML and referenced assets return 200, and protected GET/POST APIs without a
token return 401. Stop the test server before deleting only the named temporary
build/extraction directories; the ASGI stub has no separate listener to stop.
Preserve the verified archive and record its SHA-256 digest for deployment and
rollback checks.

Keep the archive path printed above. Inspect it, then perform the **separate,
explicit remote deployment** only after authorized infrastructure provisioning.
From the repository root in the same shell:

```sh
az webapp deploy \
  --resource-group "$(terraform -chdir=infra output -raw resource_group_name)" \
  --name "$(terraform -chdir=infra output -raw web_app_name)" \
  --src-path "$ARCHIVE" --type zip
```

In a new shell, set `ARCHIVE` to the printed absolute path first. Current Azure
CLI deployments use Entra credentials; publishing profiles/FTP remain disabled.
App Service runs `python -m server`
as a single worker (`WEB_CONCURRENCY=1`) from `/home/site/wwwroot`, with
`PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages`. No virtualenv
activation, npm startup, or pip install happens on Azure. Keep the artifact for
rollback; remove only the printed
temporary packaging directory when no longer needed. The private authenticated
package-manager configuration stays at its original external location, never in
that directory or archive. No registry credentials are needed on Azure because remote
package restore is disabled. Packaging and archive validation are local;
`az webapp deploy` is a separate remote operation. If CLI startup polling lags
after upload, inspect `az webapp log deployment list`: the intended deployment
must be active and complete with status `4`, and the actual HTTPS health,
configuration and frontend must pass checks. Do not treat upload acceptance or
a successful Terraform apply alone as a healthy application deployment.

For local development only, `python -m server --reload` uses the loopback
development binding. Do not enable reload or change `APP_ENV` to development on
App Service.

### Separate Function artifact for three-tier mode

For a staged rollout, provision with `enable_three_tier=true` and
`activate_queued_execution=false`: durable resources remain provisioned, the
worker is stopped, and the web runtime stays synchronous. Set activation true
only when ready to run the worker and queued web app together. Pausing does not
cancel or delete saved requests; account for absolute schedule expiry when
resuming. Terraform manages this switch so rollback does not leave hidden
configuration drift. Monitor shared-plan CPU/memory and size it for both
applications; B1 is the minimum, not a guarantee of adequate combined capacity.
Changing the plan requires `Microsoft.Web/serverFarms/write` permission.

### Changing storage networking on an existing deployment

For the simpler demo setup, leave `enable_private_storage_networking=false`
(the default). Both storage accounts use public HTTPS endpoints with managed
identity and scoped RBAC; anonymous blob access and shared-key authentication
remain disabled. This does not make the stored data public and needs no storage
private endpoints, private DNS zones, or app VNet integration.

When switching an existing private deployment back to this mode, first confirm
that public storage networking is allowed. Review the plan for enabling both
storage endpoints, disconnecting both apps from the storage VNet, and removing
only the dedicated storage private endpoints, DNS, and network resources. Keep
storage accounts, containers, queues, identities, and the queued activation
state unchanged. Verify storage access after the change; do not delete private
connectivity if public access is blocked.

An Azure Policy with a `modify` effect can accept a storage update while
rewriting `publicNetworkAccess` back to `Disabled`. Do not rely only on
Terraform reporting a successful apply: re-read both accounts before removing
private connectivity. If policy forces private-only access, an authorized
policy exception or a different approved deployment environment is needed for
the public-endpoint setup; do not bypass organizational controls.

If a confirmed organizational requirement calls for private-only storage, set
`enable_private_storage_networking=true` together with `enable_three_tier=true`.
This keeps both storage accounts private and provisions four Blob/Queue private
endpoints, two private DNS zones/links, and outbound VNet integration for both
apps. The default dedicated network is `10.73.0.0/16`; customize
`storage_vnet_cidr` to avoid overlap with your environment. Apps share the
delegated integration subnet on the same hosting plan; endpoints have a separate
subnet. This is independent of optional Application Gateway ingress and does not
make the web UI private or add private Key Vault connectivity. Private endpoints,
DNS, and data processing add costs. Do not reopen storage to work around policy.
Verify host storage access and timer/queue execution after DNS/RBAC propagation.

### Packaging the Function app

Do not upload the web zip to the worker, or the worker zip to the web app.
Build the worker on the same approved Linux x86_64/Python 3.12 builder with
dependencies installed from root `requirements.txt` into
`.python_packages/lib/site-packages`. Use a new project-local staging directory,
not an existing deployment directory. The Function zip root must contain exactly:

```text
function_app.py
host.json
server/
requirements.txt
.python_packages/
```

Copy all required `server/` runtime Python modules/data (including nested packages
when introduced), excluding tests, bytecode and local configuration. `dist/` is
only needed for the web zip. Never package `.env`, `local.settings.json`, local
credentials, Azure CLI caches, feed configuration, Terraform/state/tfvars, test
fixtures or development dependencies in either artifact. Do not change the worker
startup to `python -m server`; Functions discovers the Python v2 decorators in
root `function_app.py` and uses root `host.json`. Remote build is disabled.

Validate the extracted Function archive on the matching Linux runtime:
import `function_app` using extracted dependencies, check `host.json` and verify
that the queue, inventory timer and poison queue functions index with Azure
Functions Core Tools v4 in an isolated test environment. Host extension startup
may require approved outbound access; never use production queue data for local
tests. A Python import or Terraform mock alone is not a Functions-host smoke test.
Record both artifact hashes. After separate authorized provisioning, deploy the
worker archive to output `worker_app_name` using an approved Entra-authenticated
Functions zip deployment workflow (not publishing passwords). Deployment is a
separate cloud write; none is performed by the Terraform validation commands.

Deploy/test worker handling and inventory readiness before routing traffic to a
queued web artifact. Verify actual Azure managed-identity access and Key Vault
reference resolution after propagation. If gateway mode is enabled, ensure the
web deployer's fixed public egress is in `gateway_scm_allowed_cidrs`; an empty
allowlist intentionally blocks SCM deployment access. Keep the previously
validated synchronous web artifact and reviewed Terraform settings for rollback.

The server provides public MSAL configuration at runtime from its `ENTRA_*` and
`PUBLIC_ORIGIN` settings; never put credentials in `VITE_*` variables. Outputs
include the app/group names, URL, tenant and API/SPA client IDs, delegated scope,
API service-principal/role IDs, vault name/ID, managed identity and telemetry IDs.
Use the ID outputs in local `.env`, retaining
`PUBLIC_ORIGIN=http://localhost:5173` for Vite development.

## Enable live Commvault deliberately

1. Provision and verify stub mode first. If vault public networking is disabled,
   establish approved vault connectivity before attempting secret writes or
   App Service Key Vault reference resolution. The demo does not provision
   private endpoints or App Service VNet integration automatically.
2. An authorized secret administrator must grant themselves or the designated
   credential writer **Key Vault Secrets Officer** on the vault, externally.
   Terraform deliberately grants no secret-writing access to the deployer.
3. Store the exact Commvault header value outside Terraform. Use a protected,
   local UTF-8 file containing only that value, no trailing newline:

   ```sh
   az keyvault secret set \
     --vault-name "$(terraform -chdir=infra output -raw key_vault_name)" \
     --name commvault-auth \
     --file "/secure/local/path/commvault-auth.txt" \
     --encoding utf-8 --output none
   ```

   Avoid `--value` in shell history, debug logs, or sharing command output.
   Remove the local credential file securely according to your policy.
4. Set `commvault_mode="live"`, an HTTPS `commvault_base_url` including the actual
   API prefix (for example `/commandcenter/api`), and the required
   `commvault_auth_header` (`Authorization` or `Authtoken`). Set
   `commvault_secret_name` if different from `commvault-auth`.
5. Review another plan and apply only when authorized. Keep
   `enable_live_operations=false` until the client, permissions, and operational
   impact have been verified. Live mode itself can contact the live service;
   this flag is an additional operation gate, not a network isolation control.

Only in live mode is `COMMVAULT_AUTH_VALUE` added, and then it is exclusively an
App Service `@Microsoft.KeyVault(SecretUri=...)` reference. The secret's exact
header value includes `Bearer ` only if the target service requires it.
Terraform never reads that value. The system identity resolves the versionless
reference using vault RBAC. RBAC propagation and reference caching can delay
availability/rotation; check App Service Key Vault reference status and restart
or refresh references through the supported Azure operation when necessary.
An unresolved reference is not a valid credential and must not be treated as
successful configuration.

## Costs, checks and cleanup

B1 is billable even when idle; stopping the app does not stop service-plan
charges. Region/currency affect pricing. Workspace/Application Insights
ingestion and retention, vault operations and data transfer can add costs.
Create an Azure budget and monitor usage; the demo does not create alerts,
private networking, or a guaranteed spending cap.

After an authorized deployment, verify the configured runtime, startup logs,
HTTPS, browser PKCE sign-in, rejected unauthenticated API calls, an assigned
operator's stub operations, rejected unassigned users, telemetry delivery, and
vault reference resolution before considering live use. No real-runtime or
cloud integration behavior is claimed by the mock tests.

The September 23, 2026 stub deployment passed hosted health/configuration checks,
byte-for-byte frontend asset checks against the validated ZIP, HTTPS security
headers, anonymous GET/POST rejection, and invalid-signature rejection using a
real Entra signing-key ID. The hosted MSAL authorization redirect includes the
correct HTTPS return URL and PKCE challenge. The complete Terraform plan then
reported no drift. Hosting used B1 in Central US because East US 2 had no B1
quota; monitoring and the restricted vault remained in East US 2. These checks
do not claim a completed interactive user session on the hosted origin, live
Commvault compatibility, private vault connectivity, or telemetry ingestion.

When finished, review `terraform -chdir=infra plan -destroy` and explicitly run
`terraform -chdir=infra destroy` if approved. It removes this configuration's
resources, app registrations and assignments, not externally managed directory
objects or backend storage. Vault purge protection prevents immediate permanent
deletion/name reuse for seven days. Keep state until cleanup is complete.

# Azure setup

Start with the recipe in the [README](../README.md#deploy-your-organizations-copy).
These instructions are for a fresh receiving-team environment. They do not
require changes to an existing demo, its state, or its tenant access.

## Prerequisites

- Terraform >=1.9 and <2.0 (tested: 1.14.7), Azure CLI, and approved feeds.
  Keep the provider [lockfile](../infra/.terraform.lock.hcl); provider constraints
  are in [versions.tf](../infra/versions.tf).
- Azure resource creation **and role-assignment** permissions, appropriately
  scoped. Contributor alone does not grant `roleAssignments/write`.
- Separate Entra application-management/assignment permissions. Application
  Administrator is a common interactive choice; tenant policy may require
  additional consent approval. Azure subscription Owner is not a directory role.
- Region/SKU quota and registered providers: `Microsoft.Web`,
  `Microsoft.Insights`, `Microsoft.OperationalInsights`, `Microsoft.KeyVault`;
  also `Microsoft.Storage` for queued mode, `Microsoft.Network` for private
  networking/gateway, and `Microsoft.ManagedIdentity` for the optional gateway.
  Provider registration is an authorized cloud operation, not local validation.

For unattended provisioning use an approved federated identity, not a new client
secret. Graph application-management, user-resolution, role-assignment, and
consent permissions are distinct; have the tenant administrator approve the
required scope. Owned registrations commonly use `Application.ReadWrite.OwnedBy`;
app-role assignments also need `AppRoleAssignment.ReadWrite.All` with
`Application.Read.All`, and user resolution may need `User.Read.All`.
Do not grant broad directory permissions merely to avoid
diagnosing a failed operation.

## Configure your environment

In your fresh clone, copy
[terraform.tfvars.example](../infra/terraform.tfvars.example) to
`infra/terraform.tfvars`. Replace the subscription placeholder and choose a
globally unique `app_name`. Select the recipe's switches and retain:

```hcl
commvault_mode                  = "stub"
enable_live_operations          = false
allow_signed_in_demo_operations = true
enable_multi_tenant             = false
allowed_tenant_ids              = []
operator_object_ids            = []
api_assignment_required        = null
spa_assignment_required        = false
enable_gateway_ingress         = false
```

The null API assignment override permits the open simulator and requires
assignment for live/restricted modes. Set `allow_signed_in_demo_operations=false`
to require `BackupOperator` for the simulator too. If SPA assignment is required,
assign its default access role as well as the API operator role.

`display_name` and `support_url` are optional public branding; never put secrets
in them. They do not change safety labels, identity, or resource names.

Choose [remote state](#remote-state) before the first team-managed apply.
Actual tfvars, backend configuration, plans, state, and `.env` are local/private
inputs, not handoff artifacts.

## Provision

```sh
az login
az account set --subscription "<your-subscription-id>"
az account show --query '{subscription:id,tenant:tenantId}' -o json
terraform -chdir=infra init
terraform -chdir=infra plan -out=demo.tfplan
# Review target, identity, resources, networking, and cost. Only after approval:
terraform -chdir=infra apply demo.tfplan
terraform -chdir=infra output
```

Match the CLI subscription to your variables and avoid conflicting `ARM_*`
authentication settings. The AzureAD provider uses the selected subscription's
tenant. Apply creates billable resources and Entra objects, **not application
packages**. Next use [Build and deploy](deployment-tools.md). Remove the saved
plan after approved use; protect the state and its backups.

For source-only validation, use `terraform -chdir=infra init -backend=false`
in a validation checkout, then `fmt -check -recursive`, `validate`, and `test`.
The mock tests do not contact Azure or Graph. Do not initialize a different
backend in an existing deployment merely to validate source.

## Sign-in and access

Terraform creates separate SPA/API registrations. MSAL uses authorization code
with PKCE; Python validates signature, issuer, API audience, tenant, SPA caller,
delegated scope, and expiry. The v2 audience is the API **client GUID**; the
requested scope is `api://<api-client-id>/access_as_user`.

Each origin needs both `/` and `/auth/silent` redirect URIs. Terraform registers
the hosted origin plus `http://localhost:5173` and `http://localhost:8080`.
The callback is script-free and same-origin frameable; the dashboard/API remain
non-frameable. A CSP error or `monitor_window_timeout` is a sign-in problem, not
proof that an operator role is missing.

The delegated scope is admin-consent-only. SPA preauthorization does not override
tenant consent policy; a directory administrator may still need to grant
consent. `az login` authenticates the provisioning operator, **not** browser users.

### Optional external organizations

Enable `enable_multi_tenant=true` and supply 1-20 verified additional tenant
GUIDs in `allowed_tenant_ids`; the home tenant remains implicitly allowed.
Email suffixes are not authorization rules. Personal Microsoft accounts and
unapproved tenants remain denied.

Each external organization controls consent, Conditional Access, enterprise-app
admission, and role assignments in its own tenant. This template does not create
remote tenant grants. Live/restricted-demo operators need `BackupOperator` in
the tenant issuing their token. Sign out/in after assignment changes.

## Storage and queued mode

`enable_three_tier=true` adds a Python 3.12 Functions app, separate work/host
storage accounts, Blob containers, queues, scoped managed-identity RBAC, and
monitoring. Web and Functions share the dedicated hosting plan; capacity must
be checked for both. No storage account keys or anonymous Blob access are used.

| Setting | Storage network |
|---|---|
| `enable_private_storage_networking=false` | Public HTTPS endpoints, still requiring Entra/RBAC |
| `enable_private_storage_networking=true` | Blob/Queue private endpoints, DNS, and app VNet integration |

Managed identity does not bypass network restrictions. Where Azure Policy
requires private storage, use the private recipe and a working network/DNS
path. Do not repeatedly re-enable public access against policy remediation.
Choose non-overlapping VNet ranges for the receiving environment.

`activate_queued_execution=false` stages/pauses the worker and keeps the web app
synchronous without deleting durable resources. Activation is a separately
reviewed Terraform change once both packages and connectivity are ready.
Pausing does not cancel requests; absolute re-enable deadlines can expire.

Changing an existing private deployment to public mode can remove endpoints,
DNS, and VNet resources. First establish that public access is permitted and
verify the new path; do not remove private connectivity while storage remains
private-only. Never apply a fresh recipe over existing variables without review.

Request records, inventory, coordination, and simulator state are private Blob
containers; request/poison queues have different retention/recovery concerns.
See [queued behavior](queued-architecture.md) for leases, ownership, ambiguous
outcomes, and operational limits.

## Remote state

The backend examples are inert until explicitly adopted. For a new team-managed
deployment, have the platform team provide a **separate** approved Blob account
and container: encryption, restricted access, retention/versioning, disabled
shared keys/anonymous access, and a distinct state key per environment.

State operators need scoped `Storage Blob Data Contributor`, including Blob
lease permissions. Management-plane Contributor alone is insufficient.
Private-only backends require a connected runner/workstation and private DNS.
Blob leases provide state locking; do not disable locking to bypass contention.

Only in a fresh clone **without existing state**:

```sh
cp infra/backend.tf.example infra/backend.tf
cp infra/backend.azurerm.tfbackend.example infra/backend.azurerm.tfbackend
# Fill in your state account, container, key, tenant, and subscription.
az login --tenant "<state-tenant-id>"
terraform -chdir=infra init -backend-config=backend.azurerm.tfbackend
```

The example uses `use_azuread_auth=true` and `use_cli=true`, not account keys.
Keep actual `*.tfbackend` files out of Git. Backend authentication is independent
of provider authentication; verify both before planning resources.
An approved Azure-hosted managed-identity runner can instead use
`use_cli=false`, `use_msi=true`, and `client_id` for a user-assigned identity.
GitHub-hosted runners need separately approved federation, not an assumed MSI.

Existing-state migration is **not** part of code deployment. Coordinate an
exclusive change, retain a protected backup, verify workspace/destination, then
use the reviewed `init -migrate-state` workflow. Do not substitute `-reconfigure`
or `-force-copy`, overwrite state, or delete it blindly. Verify resource
addresses and a no-unintended-change plan afterward. Provider-computed sensitive
values may exist in state even when the application uses managed identities.

## Local development

For local-only identity bootstrap, populate your own tfvars. These deliberate
targets create the identity graph without hosting; a later untargeted apply
would provision the hosting stack:

```sh
terraform -chdir=infra init
terraform -chdir=infra plan -out=identity.tfplan \
  -target=azuread_application_identifier_uri.api \
  -target=azuread_application_pre_authorized.spa \
  -target=azuread_service_principal.api \
  -target=azuread_service_principal.spa \
  -target=azuread_app_role_assignment.operator \
  -target=azuread_app_role_assignment.spa_access
# Review: only intended Entra resources. Only after approval:
terraform -chdir=infra apply identity.tfplan
```

Alternatively use existing compatible registrations. Copy
[.env.example](../.env.example) to `.env`, fill the three `ENTRA_*_ID` fields from
Terraform outputs, and keep stub mode/live writes off. Use
`PUBLIC_ORIGIN=http://localhost:5173` for Vite or `http://localhost:8080` for the
built frontend. Use **localhost**, not `127.0.0.1`, in the browser.

Follow [feed setup](package-feeds.md) first, then:

```sh
python3.12 scripts/configure_feeds.py check
export PIP_INDEX_URL="${PACKAGE_FEED_PYTHON_INDEX:-https://packagefeedproxy.microsoft.io/pypi/simple/}"
export PIP_CONFIG_FILE=/dev/null
export PIP_EXTRA_INDEX_URL=
export PIP_TRUSTED_HOST=
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --only-binary=:all: -r requirements-dev.txt
npm ci --include=dev --ignore-scripts --strict-ssl=true \
  --registry "${PACKAGE_FEED_NPM_REGISTRY:-https://packagefeedproxy.microsoft.io/npm/}"
```

Run `python -m server --reload` and `npm run dev` in separate terminals. For the
built UI, use `npm run build` then `python -m server`, with the matching origin.
Without configured identity the protected API returns 503; there is no bypass.
For corporate TLS inspection use approved `SSL_CERT_FILE`, `PIP_CERT`, and
`NODE_EXTRA_CA_CERTS` as needed. Never disable TLS or package local CA/config files.

The complete environment switch reference is [.env.example](../.env.example);
Terraform options are in [terraform.tfvars.example](../infra/terraform.tfvars.example).

## Optional integrations

- **Live Commvault:** first verify version, URL prefix, auth header/value format,
  token lifetime, network path, and read-only inventory in an approved target.
  Configure `commvault_mode="live"` and an externally populated Key Vault secret
  reference; Terraform must not receive its value. Keep live writes off until
  separately approved. Live actions require both `BackupOperator` and the gate.
  Browser tokens are never forwarded upstream.
- **Key Vault networking:** the stub does not read an upstream secret. Restricted
  stub environments can disable vault public access to match policy. Live mode
  needs a reachable vault; disabling public access does not create its private
  endpoint or DNS path.
- **Existing APIM:** configure `existing_apim_base_url` only with three-tier live
  mode and a verified route/auth contract; leave `commvault_base_url` empty.
  No APIM instance, routes, policies, or remote simulator are provisioned.
- **Gateway ingress:** an opt-in HTTPS WAF_v2 gateway requires an existing
  certificate reference, DNS, vault access, subnet planning, and explicit SCM
  deployment egress. It changes ingress and adds significant cost. A successful
  plan is not proof of certificate, routing, or private deployment connectivity.

## Costs, monitoring, and cleanup

The B1 plan is billable even when stopped; it is a minimum, not a capacity
guarantee. Storage, monitoring, and optional gateway resources have additional
costs. A separate hosting region can introduce data-residency considerations.
The monitoring ingestion cap is not a hard spending limit and can interrupt
diagnostics. An Application Insights connection string alone does not instrument
Python request/dependency traces.

Assign owners for budgets, log/record retention, queue age, poison messages,
stale inventory, unknown outcomes, access reviews, and teardown. Support details
can contain server/user identifiers; share them only through approved channels.
There is no complete audit-history viewer or automated reconciliation/unblock
endpoint. Do not delete coordination records to force a retry.

Use a reviewed destroy plan only for authorized cleanup; retain state until it
is complete. Vault purge protection/soft deletion may retain resources. Do not
destroy the separate state backend along with the demo.

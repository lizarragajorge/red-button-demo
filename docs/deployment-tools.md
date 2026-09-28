# Build and deploy

Provision your own environment using [Azure setup](infrastructure.md) first.
**These commands do not run automatically.** Building is local; deploying
uploads code and restarts the explicitly confirmed target. Neither changes
Terraform state, app settings, identity, or network configuration.

## 1. Build both packages

Use glibc Linux x86_64, Python 3.12, Node >=22.12, and your
[approved feeds](package-feeds.md). From the repository root:

```sh
python3.12 scripts/release.py build --output releases/candidate
```

Keep `web.zip`, `functions.zip`, and `manifest.json` together in a trusted
artifact store. The builder uses fresh npm/Python staging, exact Python pins,
the npm lockfile, native import checks, and Function indexing. It rejects
symlinks, credentials/configuration files, wrong platforms, and source changes
during the build. Remote package restore is disabled.

The manifest records source hashes, package hashes, platform, and a release UUID.
It is integrity evidence against a **trusted manifest**, not artifact signing.
The packaged `release.json` is loaded once by the web process and adds `releaseId`
to `/api/config`; normal source runs without the marker are unchanged.

For a separately verified frontend and dependency archive, an explicit offline
build is available:

```sh
python3.12 scripts/release.py build --output releases/offline \
  --prebuilt-dist dist \
  --dependency-archive prior/web.zip \
  --dependency-sha256 "$TRUSTED_PRIOR_SHA256"
```

The dependency archive must match the current requirements and trusted checksum.
Prebuilt frontend provenance remains the operator's responsibility; build it
from the intended source and retain its validation evidence. Neither reuse
option is an automatic fallback. Never reuse a failed build's partial output.

## 2. Deploy the web app explicitly

Sign in with Azure CLI using the target organization's approved Entra process.
Set your own subscription, resource group, and web app names, then:

```sh
python3 scripts/release.py deploy \
  --manifest releases/candidate/manifest.json \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --web-app "$WEB_APP" \
  --receipt releases/candidate/web-verified.json \
  --timeout 600 --confirm-deploy
```

The tool validates the full ARM resource identity, Python 3.12/prebuilt settings,
single-worker startup, Entra configuration, **stub mode and live writes off**.
It does not repair mismatches. It uses Entra-authenticated Kudu, not publishing
passwords. Prevent concurrent deployments/configuration changes operationally.

Each upload has unique operation metadata and a package hash. A `latest` response
is resolved to exactly one matching deployment ID; only that ID is polled.
The tool restarts after completion, then verifies the loaded release, configured
identity/mode, HTML/assets, health, and anonymous denial. Old HTTP 200 responses
and upload acceptance are not success.

No mutation is automatically retried. On timeout or connection failure, the
upload may have succeeded: use the printed operation/deployment ID to investigate,
then perform read-only verification rather than blindly uploading again:

```sh
python3 scripts/release.py verify \
  --manifest releases/candidate/manifest.json \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --web-app "$WEB_APP" \
  --receipt releases/candidate/web-rechecked.json --timeout 600
```

Use a new receipt path each time. Add `--ca-file path/to/approved-ca.pem` if
needed, and configure Azure CLI trust separately. TLS and hostname verification
cannot be disabled. Credentials, raw service bodies, and host keys are not logged.

## 3. Queued recipes only: deploy the worker

Skip this section for the simple demo. Worker verification is separate from web
verification; the web command deliberately rejects `--worker-app`.

The [worker helper](../scripts/release_worker.py) is the maintained, tested
version of the worker procedure, not a long script to copy from documentation.
It needs an approved SCM network path and permission to list Function host keys.
It requires a readable Running host baseline; an unhealthy/unreachable baseline
needs a separately reviewed recovery procedure.

```sh
export SUBSCRIPTION_ID='your-canonical-subscription-uuid'
export RESOURCE_GROUP='your-resource-group'
export WORKER_APP='your-function-app'
export RELEASE_MANIFEST='releases/candidate/manifest.json'
export WORKER_RECEIPT='releases/candidate/worker-verified.json'
export WORKER_CONFIRM_TARGET="$SUBSCRIPTION_ID/$RESOURCE_GROUP/$WORKER_APP"
# Optional approved private CA:
# export RELEASE_CA_FILE='path/to/approved-ca.pem'
python3 scripts/release_worker.py --confirm-deploy
```

**This command uploads and restarts only the confirmed worker.** It validates
the Function App identity and demo settings, correlates the upload, then requires
exact deployed-file fingerprints, a new Running host after restart, and the
three expected functions. Only bytecode/cache files are excluded from file
comparison. Missing uptime evidence, extra files, or unsupported Kudu ZIP access
fail closed; do not weaken checks just to obtain a receipt.

The receipt proves file fingerprints plus fresh host/indexing evidence, **not**
a module-loaded worker marker, queue completion, or user sign-in. Host uptime
is interpreted in milliseconds with monotonic request-time bounds. It does not
invoke functions or submit backup operations. Never rerun a mutation merely to
recover a verification timeout; inspect its exact deployment first.

## Rollback and acceptance

Retain the prior manifest, both ZIPs, and verification receipts. Web rollback
uses the prior artifacts and a matching receipt for the same full target:

```sh
python3 scripts/release.py deploy \
  --manifest releases/previous/manifest.json \
  --rollback-receipt releases/previous/web-verified.json \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$RESOURCE_GROUP" \
  --web-app "$WEB_APP" --receipt releases/previous/web-rollback.json \
  --timeout 600 --confirm-deploy
```

Worker rollback requires the owner to check the prior worker receipt's target,
release, and manifest hash, then explicitly authorize the worker helper with
those artifacts and a new receipt. A web receipt cannot authorize worker rollback.
Old packages without a release marker need a reviewed legacy recovery procedure.

Rollback restores code only: it does not revert state/settings, cancel queued
work, undo real backup actions, or guarantee stored-data compatibility. Review
in-flight requests and compatibility first. Complete the
[handoff checklist](publishing.md#handoff-checklist) before sharing the deployment.

## Supported scope and verification limits

- Public Azure, primary Linux App Service/Function hostnames, Python 3.12,
  prebuilt packages, and demo mode. No live override, slots, sovereign clouds,
  run-from-package, or remote-build configuration changes. Web assets are limited
  to 4 MiB each for bounded verification.
- Web polling and readiness have separate bounded timeouts; worker phases have
  bounded checks too. Initial ARM/CLI operations have their own limits.
- Real Linux packaging/local runtime checks and offline deployment tests have
  passed. The new remote deployment helpers have **not** been run against Azure
  as part of this source-only handoff.
- New receiving environments still need actual MSAL sign-in, consent, storage,
  worker, and simulated end-to-end acceptance. Local tests cannot certify those.

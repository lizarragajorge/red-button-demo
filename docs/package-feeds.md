# Approved package feeds for a receiver

The checked-in `.npmrc` and `package-lock.json` retain the Microsoft internal
defaults. Nothing in this handoff changes a running deployment, Azure, Terraform
inputs/state or `.env`. Feed selection is **opt-in source configuration**, not
deployment automation. The helper performs no network requests or installations.
Do this only in the receiving organization's separate checkout.

## Approval and prerequisites

Obtain organization approval for **both** the npm registry and every tarball
endpoint, plus the Python index. An accessible/public URL is not approval.
Repository administrators control these non-secret Actions variables:

| Variable | Unset/empty default |
| --- | --- |
| `PACKAGE_FEED_NPM_REGISTRY` | `https://packagefeedproxy.microsoft.io/npm/` |
| `PACKAGE_FEED_NPM_TARBALL_BASE` | Both internal bases below, only when the npm registry is the default |
| `PACKAGE_FEED_PYTHON_INDEX` | `https://packagefeedproxy.microsoft.io/pypi/simple/` |

The only default npm tarball bases are:

- `https://packagefeedproxy.microsoft.io/npm/`
- `https://ms-feed-25.pkgs.visualstudio.com/1es-public/_packaging/npm-public/npm/registry/`

An alternative registry requires an explicit tarball base; it cannot silently
retain either internal base. Both scoped and unscoped packages use the selected
registry. The checker allows **exact base paths and package/version filenames**,
not arbitrary URLs on approved hosts. Different registry and CDN hosts are
supported only by explicitly selecting the CDN base. Per-scope registries,
multiple CDNs and arbitrary/path-changing artifact layouts are not supported;
the helper fails rather than guessing or broadening the allowlist.

All feed URLs must be canonical HTTPS, with lowercase hostnames and trailing `/`.
They cannot contain userinfo, query strings, fragments, percent escapes,
backslashes, whitespace, dot segments or embedded credentials. Do not put a token
in a path. No fallback registry, extra Python index or disabled TLS validation is
provided. Supply credentials outside the repository (for example an approved
credential provider or protected user configuration; Python may use `.netrc`).
Never place credentials in repository variables, command-line URLs, generated
files or committed `.npmrc`. External npm configuration must not override
registries (including scoped registries) or TLS. Any additional authentication
step in CI must use the receiving organization's secret-management process.

## Pin-preserving mirror handoff

Before using `--confirm-mirror-layout`, the organization's mirror administrator
must confirm that **every locked package** is served as the **identical tarball
bytes**, including retained older versions and optional platform packages, at:

```text
<TARBALL_BASE><name>/-/<unscoped-name>-<locked-version>.tgz
```

Examples for `https://cdn.example.invalid/npm/`:

```text
plain 1.2.3          -> https://cdn.example.invalid/npm/plain/-/plain-1.2.3.tgz
@scope/scoped 1.2.3 -> https://cdn.example.invalid/npm/@scope/scoped/-/scoped-1.2.3.tgz
```

The helper verifies the source against both known internal layouts, transforms
each exact package/version suffix, and verifies every resulting URL. It preserves
all versions, integrity values and other lock metadata. Existing SHA-1 integrity
values are preserved, not upgraded or invented. It cannot prove mirror contents
offline; approval/layout confirmation is an explicit administrator attestation.
On installation npm verifies the retained integrity values and fails if bytes
differ. There is **no** automatic regeneration, version upgrade or fallback.
Unknown layouts, aliases, links, missing integrity and non-v3 lockfiles fail.

Replace the example URLs below with approved endpoints. Run from the receiving
checkout's root using Python 3.12+ (no helper dependencies):

```bash
python3 scripts/configure_feeds.py check
python3 scripts/configure_feeds.py prepare \
  --registry https://packages.example.invalid/npm/ \
  --tarball-base https://cdn.example.invalid/npm/ \
  --approved --confirm-mirror-layout \
  --output receiver-feeds
```

`receiver-feeds` must not exist; its parent must exist. All inputs and source
files are checked before output creation. A write failure rolls back newly
created output; existing output is never overwritten. The source `.npmrc` and
lockfile are never edited. After successful exit, review **both** exported files;
never use output from an interrupted process. Adopt them together **only in the
receiving checkout**, before any restore:

```bash
cp receiver-feeds/.npmrc .npmrc
cp receiver-feeds/package-lock.json package-lock.json
export PACKAGE_FEED_NPM_REGISTRY=https://packages.example.invalid/npm/
export PACKAGE_FEED_NPM_TARBALL_BASE=https://cdn.example.invalid/npm/
export PACKAGE_FEED_PYTHON_INDEX=https://packages.example.invalid/python/simple/
python3 scripts/configure_feeds.py check
```

Review the lock diff: only `resolved` values (and possibly formatting) should
change. Keep the export directory outside your publication snapshot, or remove
only that generated directory after reviewing and adopting both files. Do not
commit its duplicate `.npmrc`; the publication checker rejects nested npm
configuration. This example does not restore packages. If/when authorized to restore:

```bash
export NPM_CONFIG_REGISTRY="$PACKAGE_FEED_NPM_REGISTRY"
export NPM_CONFIG_STRICT_SSL=true
export PIP_INDEX_URL="$PACKAGE_FEED_PYTHON_INDEX"
export PIP_CONFIG_FILE=/dev/null
export PIP_EXTRA_INDEX_URL=
export PIP_TRUSTED_HOST=
python3 -m pip install --only-binary=:all: -r requirements-dev.txt
npm ci --include=dev --ignore-scripts
```

Do not merely change `registry=`: absolute `resolved` URLs otherwise keep
contacting the original feed. Do not delete the lock or run `npm install` as a
shortcut: semver ranges can select newer versions and require a separately
reviewed dependency/security change. If the mirror cannot preserve the required
layout and bytes, stop and arrange a compatible approved mirror; this helper
intentionally does not implement unreviewed regeneration.

## Validation workflow

Set all three repository variables to the approved values above when adopting
the exported pair. Python feed selection is independent and explicit; no public
index is inferred from the npm choice. Variables enter workflow `env`, never
interpolated into shell commands. The stdlib-only check runs **before** pip/npm
restore, requires `.npmrc` to match the selection, and validates every lock URL.
Only after success does it export installer settings through `$GITHUB_ENV`.
Python config files, extra indexes and trusted-host TLS bypasses are disabled.
An unchanged internal lock with alternative variables, or an alternative lock
with missing variables, fails before restore. Without opt-in, internal defaults
remain unchanged. Local tests use the same explicit selection rules.

```bash
python3 scripts/configure_feeds.py check
python3 -m pytest -p no:cacheprovider tests/test_feeds.py \
  tests/test_app.py::test_npm_configuration_and_lockfile_use_only_approved_feeds
```

Tests use offline fixtures, including scoped packages and both internal layouts;
they never download from example/public/alternative feeds. Browser downloads
(Playwright), GitHub Actions, dependency-advisory queries and Terraform provider
downloads are separate endpoints, not redirected by these npm/Python settings.
Review those separately under the receiver's network and supply-chain policies.

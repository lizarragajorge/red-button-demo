import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from server.app import create_app
from server.auth import EntraTokenVerifier, TokenRejected
from server.commvault import CommvaultClient, CommvaultError
from server.config import Settings
from server.models import ActionResult, DelayOptions
from server.stub import StubStore, create_stub

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = {
    "ENTRA_TENANT_ID": "11111111-1111-4111-8111-111111111111",
    "ENTRA_API_CLIENT_ID": "22222222-2222-4222-8222-222222222222",
    "ENTRA_SPA_CLIENT_ID": "33333333-3333-4333-8333-333333333333",
}
CONFIG = Settings.from_env({**IDENTITY, "APP_ENV": "test"})


@pytest.fixture(scope="session")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(private_key, claims=None, remove=()):
    now = int(time.time())
    payload = {
        "iss": f"https://login.microsoftonline.com/{CONFIG.tenant_id}/v2.0",
        "aud": CONFIG.api_client_id, "exp": now + 300, "nbf": now, "iat": now,
        "tid": CONFIG.tenant_id, "azp": CONFIG.spa_client_id,
        "oid": "operator-object-id", "scp": "access_as_user", "roles": ["BackupOperator"],
        **(claims or {}),
    }
    for name in remove:
        payload.pop(name)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key"})


class LocalKeys:
    def __init__(self, private_key):
        self.public_key = private_key.public_key()

    def get_signing_key_from_jwt(self, raw):
        if jwt.get_unverified_header(raw).get("kid") != "test-key":
            raise jwt.PyJWKClientError("Unknown key.")
        return SimpleNamespace(key=self.public_key)


@dataclass
class Harness:
    http: httpx.AsyncClient
    stub_http: httpx.AsyncClient
    store: StubStore
    client: CommvaultClient
    audit: list
    private_key: object

    async def request(self, path, body=None, claims=None, anonymous=False, method=None):
        return await self.http.request(
            method or ("POST" if body is not None else "GET"), path,
            headers={} if anonymous else {"Authorization": f"Bearer {token(self.private_key, claims)}"},
            json=body,
        )


@pytest.fixture
def harness(private_key):
    @asynccontextmanager
    async def make(settings=CONFIG, clock=time.time):
        store = StubStore(clock)
        stub = create_stub("test-credential", store=store)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=stub), base_url="http://stub") as stub_http:
            client = CommvaultClient(stub_http, "http://stub", "Authorization", "test-credential")
            audit = []
            app = create_app(settings, client, EntraTokenVerifier(settings, LocalKeys(private_key)), audit.append)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://app.test",
                ) as http:
                    yield Harness(http, stub_http, store, client, audit, private_key)
    return make


def disable(ids=None, options=None):
    return {"serverIds": [102] if ids is None else ids, "confirmation": "DISABLE BACKUPS", "options": options or {}}


def test_npm_configuration_and_lockfile_use_only_internal_feed():
    from urllib.parse import urlsplit
    npmrc = (ROOT / ".npmrc").read_text()
    assert "registry=https://packagefeedproxy.microsoft.io/npm/\n" in npmrc
    assert "strict-ssl=true\n" in npmrc
    lock = json.loads((ROOT / "package-lock.json").read_text())
    for dependency in lock["packages"].values():
        if "resolved" not in dependency:
            continue
        url = urlsplit(dependency["resolved"])
        assert url.hostname in ("packagefeedproxy.microsoft.io", "ms-feed-25.pkgs.visualstudio.com")
        assert url.scheme == "https"
        assert not (url.username or url.password or url.query)


def test_settings_default_to_stub_and_hide_credentials_in_errors():
    assert Settings.from_env({}).mode == "stub"
    assert not Settings.from_env({}).identity_configured
    with pytest.raises(ValueError) as error:
        Settings.from_env({**IDENTITY, "COMMVAULT_MODE": "live", "COMMVAULT_AUTH_VALUE": "private-test-token"})
    assert "private-test-token" not in str(error.value)

@pytest.mark.parametrize("env", [
    {"APP_DISPLAY_NAME": ""}, {"APP_DISPLAY_NAME": " "}, {"APP_DISPLAY_NAME": "x" * 61},
    {"APP_DISPLAY_NAME": "App\nname"}, {"SUPPORT_URL": "javascript:alert(1)"},
    {"SUPPORT_URL": "http://help.invalid"}, {"SUPPORT_URL": "https://user:secret@help.invalid"},
    {"SUPPORT_URL": "https://help.invalid/\npath"}, {"SUPPORT_URL": "https://help.invalid:bad/"},
    {"SUPPORT_URL": "https://help.invalid\\@external.invalid"},
])
def test_invalid_public_branding_is_rejected(env):
    with pytest.raises(ValueError):
        Settings.from_env(env)


async def test_public_branding_does_not_change_safety_gates(harness):
    settings = Settings.from_env({
        **IDENTITY, "APP_DISPLAY_NAME": "  Client Backup Control  ",
        "SUPPORT_URL": "https://support.example.invalid/help",
    })
    async with harness(settings=settings) as h:
        config = (await h.request("/api/config", anonymous=True)).json()
        assert config["displayName"] == "Client Backup Control"
        assert config["supportUrl"] == "https://support.example.invalid/help"
        assert config["mode"] == "stub"
        assert config["liveOperationsEnabled"] is False
        assert (await h.request("/api/disable", body=disable(), claims={"roles": []})).status_code == 403


@pytest.mark.parametrize("env", [
    {"APP_ENV": "production"}, {"COMMVAULT_MODE": "typo"}, {"ENABLE_LIVE_OPERATIONS": "yes"},
    {"ENTRA_API_CLIENT_ID": "invalid"}, {"PUBLIC_ORIGIN": "https://demo.invalid/path"},
    {"PUBLIC_ORIGIN": "http://demo.invalid"},
    {**IDENTITY, "COMMVAULT_MODE": "live", "COMMVAULT_BASE_URL": "http://demo.invalid", "COMMVAULT_AUTH_VALUE": "token"},
    {**IDENTITY, "COMMVAULT_MODE": "live", "COMMVAULT_BASE_URL": "https://demo.invalid", "COMMVAULT_AUTH_VALUE": "@Microsoft.KeyVault(SecretUri=missing)"},
    {**IDENTITY, "COMMVAULT_MODE": "live", "COMMVAULT_BASE_URL": "https://demo.invalid?token=bad", "COMMVAULT_AUTH_VALUE": "token"},
])
def test_invalid_settings_are_rejected(env):
    with pytest.raises(ValueError):
        Settings.from_env(env)


async def test_public_config_never_discloses_credentials_and_protected_apis_fail_closed(harness):
    async with harness() as h:
        response = await h.request("/api/config", anonymous=True)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "COMMVAULT_AUTH_VALUE" not in response.json()
        assert response.json()["mode"] == "stub"
        assert response.json()["displayName"] == "Red Button"
        assert response.json()["supportUrl"] == ""
        assert (await h.request("/api/servers", anonymous=True)).status_code == 401
    async with harness(settings=Settings.from_env({})) as h:
        assert (await h.request("/api/servers", anonymous=True)).status_code == 503


@pytest.mark.parametrize("claims", [
    {"tid": "wrong"}, {"azp": "wrong"}, {"scp": "read_only"}, {"scp": None},
    {"oid": None}, {"aud": "wrong"}, {"iss": "https://wrong.invalid"},
    {"exp": 1}, {"nbf": 4102444800}, {"roles": "BackupOperator"},
])
async def test_invalid_jwt_claims_are_rejected(private_key, claims):
    verifier = EntraTokenVerifier(CONFIG, LocalKeys(private_key))
    with pytest.raises((jwt.PyJWTError, TokenRejected)):
        await verifier.verify(token(private_key, claims))


async def test_jwt_signature_and_required_claims(private_key):
    verifier = EntraTokenVerifier(CONFIG, LocalKeys(private_key))
    assert (await verifier.verify(token(private_key))).oid == "operator-object-id"
    for missing in ("exp", "iat", "nbf", "oid", "tid", "azp", "scp"):
        with pytest.raises(jwt.PyJWTError):
            await verifier.verify(token(private_key, remove=(missing,)))
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.InvalidSignatureError):
        await verifier.verify(token(wrong_key))


async def test_rejected_token_is_audited_and_never_logged(harness):
    async with harness() as h:
        response = await h.request("/api/servers", claims={"scp": "wrong"})
        assert response.status_code == 401
        assert h.audit[-1]["event"] == "authentication_rejected"
        assert "Bearer" not in json.dumps(h.audit)


async def test_stub_default_filter_and_app_explicit_all_servers(harness):
    async with harness() as h:
        raw = await h.stub_http.get("/V4/Servers", headers={"Authorization": "test-credential"})
        assert raw.status_code == 200
        assert set(raw.json()) == {"servers", "totalServers"}
        assert raw.json()["totalServers"] == 1
        assert raw.json()["servers"][0]["isInfrastructure"] is True
        assert "backupEnabled" not in raw.json()["servers"][0]
        assert (await h.request("/api/servers")).json()["totalServers"] == 3
        assert (await h.request("/api/servers?showOnlyInfrastructureMachines=1")).json()["totalServers"] == 1
        assert (await h.request("/api/servers?showOnlyInfrastructureMachines=2")).status_code == 400
        assert (await h.stub_http.get("/V4/Servers")).status_code == 401


async def test_disable_only_selected_server_repeat_and_audit(harness):
    async with harness() as h:
        response = await h.request("/api/disable", body=disable())
        assert response.status_code == 200
        assert response.json()["results"] == [{"serverId": 102, "success": True}]
        assert h.store.get_state(102).disabled
        assert not h.store.get_state(101).disabled
        assert (await h.request("/api/disable", body=disable())).status_code == 200
        assert len([entry for entry in h.audit if entry["event"] == "disable_succeeded"]) == 2
        assert h.audit[0]["actorId"] == "operator-object-id"
        assert "test-credential" not in json.dumps(h.audit)


async def test_operator_role_and_live_gate_are_independently_required(harness):
    async with harness() as h:
        assert (await h.request("/api/disable", body=disable(), claims={"roles": []})).status_code == 403
        assert (await h.request("/api/me", claims={"roles": []})).json() == {"canDisable": False}
    for enabled in (False, True):
        settings = Settings.from_env({
            **IDENTITY, "APP_ENV": "test", "COMMVAULT_MODE": "live", "COMMVAULT_BASE_URL": "https://live.invalid",
            "COMMVAULT_AUTH_VALUE": "test-value", "ENABLE_LIVE_OPERATIONS": "true" if enabled else "false",
        })
        async with harness(settings=settings) as h:
            assert (await h.request("/api/disable", body=disable())).status_code == (200 if enabled else 403)
            assert h.store.get_state(102).disabled is enabled


@pytest.mark.parametrize("body", [
    {**disable(), "confirmation": "yes"}, disable([]), disable([102, 102]), disable([-1]),
    disable([2147483648]), disable([True]), disable(list(range(1, 52))),
    disable(options={"enableAfterADelay": 1}), disable(options={"enableAfterADelay": 2147483648}),
    disable(options={"enableAfterDelayTimeZone": 1}), {**disable(), "unexpected": True},
])
async def test_invalid_requests_never_mutate_state(harness, body):
    async with harness() as h:
        assert (await h.request("/api/disable", body=body)).status_code == 400
        assert not h.store.get_state(102).disabled


async def test_schedule_uses_epoch_seconds_and_exact_deadline(harness):
    now = [time.time()]
    async with harness(clock=lambda: now[0]) as h:
        deadline = int(now[0]) + 120
        await h.client.disable_backups(102, DelayOptions.model_validate({
            "enableAfterADelay": deadline, "enableAfterDelayTimeZone": 0,
        }))
        now[0] = deadline - 0.001
        assert h.store.get_state(102).disabled
        now[0] = deadline
        assert not h.store.get_state(102).disabled


async def test_partial_failure_returns_individual_outcomes(harness):
    async with harness() as h:
        response = await h.request("/api/disable", body=disable([102, 999, 103]))
        assert response.status_code == 207
        results = response.json()["results"]
        assert [result["success"] for result in results] == [True, False, True]
        assert "404" in results[1]["error"]
        assert len([entry for entry in h.audit if entry["event"] == "disable_failed"]) == 1


async def test_client_preserves_prefix_auth_header_and_business_errors():
    def respond(request):
        assert request.headers["Authtoken"] == "opaque-test-token"
        assert str(request.url).startswith("https://client.invalid/commandcenter/api/V4/")
        if request.method == "GET":
            assert request.url.params["showOnlyInfrastructureMachines"] == "0"
            return httpx.Response(200, json={"servers": [], "totalServers": 0})
        assert request.url.path.endswith("/Server/102/Backup/Action/Disable")
        assert request.url.params["enableAfterADelay"] == "2000000000"
        return httpx.Response(200, json={"errorCode": 23, "errorMessage": "sensitive upstream details"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = CommvaultClient(http, "https://client.invalid/commandcenter/api", "Authtoken", "opaque-test-token")
        assert (await client.list_servers()).totalServers == 0
        with pytest.raises(CommvaultError) as error:
            await client.disable_backups(102, DelayOptions.model_validate({"enableAfterADelay": 2000000000}))
        assert error.value.code == "23"
        assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("response", [
    httpx.Response(200, content="{"),
    httpx.Response(200, json={"servers": []}),
    httpx.Response(200, json={"servers": [], "totalServers": 2147483648}),
    httpx.Response(302, headers={"Location": "https://external.invalid"}),
    httpx.Response(503),
])
async def test_client_rejects_bad_responses_without_following_redirects_or_retrying(response):
    count = 0
    def respond(request):
        nonlocal count
        count += 1
        return response
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = CommvaultClient(http, "https://client.invalid", "Authorization", "test")
        with pytest.raises(CommvaultError):
            await client.list_servers()
    assert count == 1


async def test_timeout_is_explicit_with_no_automatic_write_retry():
    count = 0
    def timeout(request):
        nonlocal count
        count += 1
        assert request.extensions["timeout"]["read"] == 15
        raise httpx.ReadTimeout("mock timeout", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
        client = CommvaultClient(http, "https://client.invalid", "Authorization", "test")
        with pytest.raises(CommvaultError) as error:
            await client.disable_backups(102)
        assert error.value.code == "TRANSPORT_ERROR"
        assert "unknown" in str(error.value)
    assert count == 1


async def test_concurrent_overlap_rejected_and_locks_released(harness, monkeypatch):
    began = asyncio.Event()
    release = asyncio.Event()
    async def delayed(server_id, options):
        began.set()
        await release.wait()
        return ActionResult(errorCode=0, errorMessage="")
    async with harness() as h:
        monkeypatch.setattr(h.client, "disable_backups", delayed)
        first = asyncio.create_task(h.request("/api/disable", body=disable()))
        await asyncio.wait_for(began.wait(), timeout=5)
        assert (await h.request("/api/disable", body=disable())).status_code == 409
        release.set()
        assert (await first).status_code == 200
        assert (await h.request("/api/disable", body=disable())).status_code == 200


async def test_raw_stub_validation_and_success_shape(harness):
    async with harness() as h:
        headers = {"Authorization": "test-credential"}
        path = "/V4/Server/102/Backup/Action/Disable"
        for query in ("?enableAfterADelay=tomorrow", "?enableAfterADelay=1", "?enableAfterDelayTimeZone=1", "?extra=1"):
            assert (await h.stub_http.put(path + query, headers=headers)).status_code == 400
        assert (await h.stub_http.put(path, headers=headers)).json() == {"errorCode": 0, "errorMessage": ""}


async def test_malformed_and_oversized_bodies_are_explicit_errors(harness):
    async with harness() as h:
        headers = {"Authorization": f"Bearer {token(h.private_key)}", "Content-Type": "application/json"}
        assert (await h.http.post("/api/disable", content="{", headers=headers)).status_code == 400
        large = await h.http.post("/api/disable", content="x" * 16385, headers=headers)
        assert large.status_code == 413
        assert "too large" in large.json()["error"]
        assert "x-request-id" in large.headers


async def test_runtime_lifespan_uses_private_stub_without_network(private_key):
    app = create_app(CONFIG, verifier=EntraTokenVerifier(CONFIG, LocalKeys(private_key)), audit=lambda entry: None)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test") as http:
            response = await http.get("/api/servers", headers={"Authorization": f"Bearer {token(private_key)}"})
            assert response.status_code == 200
            assert response.json()["totalServers"] == 3
            assert (await http.get("/V4/Servers")).status_code == 404


async def test_production_security_headers(harness):
    settings = Settings.from_env({**IDENTITY, "APP_ENV": "production", "PUBLIC_ORIGIN": "https://demo.invalid"})
    async with harness(settings=settings) as h:
        response = await h.request("/api/health", anonymous=True)
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "upgrade-insecure-requests" in response.headers["content-security-policy"]
        assert response.headers["strict-transport-security"].startswith("max-age=")
        assert response.headers["cross-origin-opener-policy"] == "same-origin-allow-popups"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-src 'self' https://login.microsoftonline.com" in response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_silent_callback_is_script_free_same_origin_only_and_not_cached(harness):
    async with harness() as h:
        config = (await h.request("/api/config", anonymous=True)).json()
        assert config["silentRedirectUri"] == CONFIG.public_origin + "/auth/silent"
        response = await h.request("/auth/silent", anonymous=True)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-security-policy"] == "default-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"
        assert "<script" not in response.text and "location" not in response.text
        for path in ("/", "/api/me", "/auth/silent-missing"):
            protected = await h.request(path, anonymous=True)
            assert protected.headers["x-frame-options"] == "DENY"
            assert "frame-ancestors 'none'" in protected.headers["content-security-policy"]
        wrong_method = await h.request("/auth/silent", anonymous=True, method="POST")
        assert wrong_method.status_code == 405
        assert wrong_method.headers["x-frame-options"] == "DENY"


async def test_upstream_failures_are_explicit_and_unexpected_errors_are_redacted(harness, monkeypatch):
    async with harness() as h:
        async def failed_list(flag):
            raise CommvaultError("Commvault returned HTTP 503.", "HTTP_ERROR")
        monkeypatch.setattr(h.client, "list_servers", failed_list)
        assert (await h.request("/api/servers")).status_code == 502
        async def unexpected(server_id, options):
            raise RuntimeError("private-error-detail")
        monkeypatch.setattr(h.client, "disable_backups", unexpected)
        response = await h.request("/api/disable", body=disable())
        assert response.status_code == 500
        assert "private-error-detail" not in response.text + json.dumps(h.audit)
        async def recovered(server_id, options):
            return ActionResult(errorCode=0, errorMessage="")
        monkeypatch.setattr(h.client, "disable_backups", recovered)
        assert (await h.request("/api/disable", body=disable())).status_code == 200


def test_python_launcher_respects_port_environment_and_reload_guard(monkeypatch):
    from server import __main__ as launcher
    for key, value in CONFIG.model_dump(by_alias=True).items():
        monkeypatch.setenv(key, ",".join(value) if isinstance(value, tuple) else str(value))
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setattr("sys.argv", ["server", "--reload"])
    calls = []
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **options: calls.append((app, options)))
    launcher.main()
    assert calls == [("server.main:app", {
        "host": "127.0.0.1", "port": 8123, "reload": True, "server_header": False,
    })]
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 2
    monkeypatch.setattr("sys.argv", ["server"])
    launcher.main()
    assert calls[-1][1]["host"] == "0.0.0.0"

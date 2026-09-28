"""Explicit demo-worker deployment; separate from web readiness and queue acceptance."""

import argparse
import io
import json
import os
import re
import stat
import sys
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release import (
    Azure, Http, ReleaseError, decode_response, json_bytes, output_path,
    require, sha, validate_manifest,
)


class WorkerHttp(Http):
    restart_started = None

    def request(self, method, url, *args, **kwargs):
        if method == "POST" and "/restart?" in url:
            self.restart_started = time.monotonic()
        return super().request(method, url, *args, **kwargs)


def worker_release():
    subscription = os.environ["SUBSCRIPTION_ID"]
    group = os.environ["RESOURCE_GROUP"]
    name = os.environ["WORKER_APP"]
    require(os.environ.get("WORKER_CONFIRM_TARGET") == f"{subscription}/{group}/{name}",
            "Explicit full worker-target confirmation is required.")
    manifest_path = Path(os.environ["RELEASE_MANIFEST"])
    manifest = validate_manifest(manifest_path)
    manifest_hash = sha(manifest_path.read_bytes())
    receipt_path = output_path(os.environ["WORKER_RECEIPT"])
    require(not receipt_path.exists(), "Choose a new worker receipt path.")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    archive = manifest_path.parent / manifest["artifacts"]["functions"]["file"]
    expected_archive_hash = manifest["artifacts"]["functions"]["sha256"]
    ca_file = os.environ.get("RELEASE_CA_FILE") or None
    transport = WorkerHttp(ca_file)
    target = Azure(SimpleNamespace(
        subscription=subscription, resource_group=group,
        web_app=name, ca_file=ca_file,
    ), http=transport)
    site = decode_response(target.arm())
    require(site.get("id", "").lower() == target.resource_id.lower(),
            "Wrong full worker resource identity.")
    props = site.get("properties", {})
    require("functionapp" in site.get("kind", "").lower()
            and props.get("reserved") is True and props.get("httpsOnly") is True,
            "Target must be an HTTPS Linux Function App.")
    host = props.get("defaultHostName", "")
    require(re.fullmatch(r"[A-Za-z0-9-]+\.azurewebsites\.net", host),
            "Unsupported worker hostname/cloud.")
    scm = host.replace(".azurewebsites.net", ".scm.azurewebsites.net")
    require(scm in props.get("enabledHostNames", []), "Worker SCM binding mismatch.")
    target.web, target.scm = "https://" + host, "https://" + scm
    config = decode_response(target.arm("/config/web")).get("properties", {})
    require(config.get("linuxFxVersion", "").upper() == "PYTHON|3.12",
            "Worker must use Python 3.12.")
    settings = decode_response(target.arm("/config/appsettings/list", "POST")).get("properties", {})
    for key, expected in {
        "APP_ENV": "production", "COMMVAULT_MODE": "stub",
        "ENABLE_LIVE_OPERATIONS": "false", "EXECUTION_MODE": "queued",
        "FUNCTIONS_WORKER_RUNTIME": "python", "FUNCTIONS_EXTENSION_VERSION": "~4",
        "SCM_DO_BUILD_DURING_DEPLOYMENT": "false", "ENABLE_ORYX_BUILD": "false",
    }.items():
        require(settings.get(key) == expected, "Worker runtime/demo configuration mismatch.")
    require(not settings.get("WEBSITE_RUN_FROM_PACKAGE"),
            "Run-from-package needs a different worker procedure.")
    keys = decode_response(target.arm("/host/default/listkeys", "POST"))
    master_key = keys.get("masterKey")
    require(isinstance(master_key, str) and bool(master_key), "Authorized host key unavailable.")
    admin_headers = {"x-functions-key": master_key}

    def host_snapshot(timeout=30):
        started = time.monotonic()
        status = decode_response(transport.request(
            "GET", target.web + "/admin/host/status", admin_headers, timeout=timeout))
        finished = time.monotonic()
        uptime = status.get("processUptime")
        require(status.get("state") == "Running" and isinstance(status.get("id"), str)
                and bool(status["id"]) and isinstance(status.get("instanceId"), str)
                and bool(status["instanceId"]) and type(uptime) in (int, float)
                and 0 <= uptime < 10**12, "Running host identity/uptime evidence unavailable.")
        return status, started - uptime / 1000, finished - uptime / 1000

    baseline, _, baseline_latest_start = host_snapshot()
    deployment_id = target.deploy(archive, 600, expected_archive_hash)
    require(transport.restart_started is not None, "No observed restart request.")
    deadline = time.monotonic() + 600
    last_error = "Worker not checked."
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Worker readiness deadline exceeded: " + last_error)
        try:
            current, earliest_start, _ = host_snapshot(min(30, remaining))
            require(current["id"] == baseline["id"], "Unexpected host identity.")
            require(earliest_start >= transport.restart_started
                    and earliest_start > baseline_latest_start,
                    "Host did not demonstrably start after upload/restart.")
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Worker discovery deadline exceeded.")
            discovered = decode_response(transport.request(
                "GET", target.web + "/admin/functions", admin_headers, timeout=min(30, remaining)))
            require(isinstance(discovered, list)
                    and sorted(item["name"] for item in discovered)
                    == ["inventory_refresh", "request_poison", "request_worker"],
                    "Expected worker functions are not indexed.")
            break
        except ReleaseError as error:
            last_error = str(error)
            time.sleep(min(3, max(0, deadline - time.monotonic())))

    def fingerprints(raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            names = bundle.namelist()
            require(len(names) == len(set(names)), "Duplicate file in worker ZIP.")
            result = {}
            for item in bundle.infolist():
                parts = PurePosixPath(item.filename).parts
                require(parts and not item.filename.startswith("/") and "\\" not in item.filename
                        and ".." not in parts and not stat.S_ISLNK(item.external_attr >> 16),
                        "Unsafe file in worker ZIP.")
                if not item.is_dir() and "__pycache__" not in parts and not item.filename.endswith(".pyc"):
                    result[item.filename] = sha(bundle.read(item))
            return result

    expected_bytes = archive.read_bytes()
    require(sha(expected_bytes) == expected_archive_hash, "Local worker archive changed.")
    request = urllib.request.Request(
        target.scm + "/api/zip/site/wwwroot/", headers=target.headers, method="GET")
    with transport.opener.open(request, timeout=120) as response:
        require(response.status == 200, "Worker Kudu snapshot failed.")
        deployed = response.read(128 * 1024 * 1024 + 1)
    require(len(deployed) <= 128 * 1024 * 1024, "Worker snapshot exceeds this procedure's limit.")
    require(fingerprints(deployed) == fingerprints(expected_bytes),
            "Deployed worker files differ from the trusted Functions ZIP.")
    final, final_earliest_start, _ = host_snapshot()
    require(final["id"] == current["id"] and final["instanceId"] == current["instanceId"]
            and final["processUptime"] >= current["processUptime"]
            and final_earliest_start >= transport.restart_started,
            "Worker host changed during fingerprint verification.")
    require(sha(manifest_path.read_bytes()) == manifest_hash, "Local manifest changed.")
    receipt = {
        "resourceId": target.resource_id, "releaseId": manifest["releaseId"],
        "manifestSha256": manifest_hash, "deploymentId": deployment_id,
        "verifiedUtc": datetime.now(UTC).isoformat(),
        "workerFilesAndFreshHostVerified": True,
        "workerRuntimeReleaseMarkerVerified": False,
        "queueCompletionVerified": False, "apiUserSignInVerified": False,
        "baselineInstanceId": baseline["instanceId"], "instanceId": final["instanceId"],
        "baselineProcessUptimeMs": baseline["processUptime"],
        "processUptimeMs": final["processUptime"],
        "functions": ["inventory_refresh", "request_poison", "request_worker"],
    }
    with receipt_path.open("xb") as output:
        output.write(json_bytes(receipt))
    print(json.dumps(receipt, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-deploy", action="store_true",
                        help="Authorize deployment to the full WORKER_CONFIRM_TARGET environment value.")
    args = parser.parse_args(argv)
    if not args.confirm_deploy:
        parser.error("Worker deployment requires --confirm-deploy; no Azure operation performed.")
    try:
        worker_release()
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, ReleaseError) else type(error).__name__
        print("Worker procedure failed: " + message + ". If upload began, inspect its exact "
              "deployment before further mutation. No automatic retry or rollback.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

import { PublicClientApplication, InteractionRequiredAuthError } from "@azure/msal-browser";
import "./style.css";

document.querySelector("#app").innerHTML = `
  <a class="skip-link" href="#workspace">Skip to backup controls</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="Red Button home"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name"><span id="brand-name">Red Button</span><span class="brand-sub">BACKUP OPERATIONS</span></span></a>
    <div class="account"><span id="account-name"></span><button id="sign-in" class="secondary" disabled>Sign in with Microsoft</button></div>
  </header>
  <main>
    <section class="heading" aria-labelledby="page-title">
      <div class="hero-copy"><p class="eyebrow">OPERATIONS / BACKUP CONTROL</p><h1 id="page-title">The <span class="hero-red">Red Button.</span></h1><p class="hero-description">Select your scope. Review the impact. Take control.</p></div>
      <div class="hero-aside"><div id="mode" class="mode">CONNECTING</div></div>
    </section>
    <div id="notice" class="notice" role="status">Connecting to the application...</div>
    <div id="error" class="error" role="alert" hidden></div>
    <section id="workspace" class="workspace" tabindex="-1" aria-label="Backup controls">
      <div id="inventory" class="panel inventory" aria-busy="false">
        <div class="panel-heading"><div><p class="eyebrow">01 / SELECT</p><h2>Server inventory <span id="server-count" class="count">0</span></h2></div><button id="refresh" class="secondary" disabled>Refresh</button></div>
        <div class="inventory-toolbar">
          <div class="search-row"><label for="server-search" class="sr-only">Find a server</label><div class="search-input"><span aria-hidden="true" class="search-icon"></span><input id="server-search" type="search" placeholder="Search servers, hostnames, or IDs" disabled autocomplete="off"></div></div>
          <div class="filter-row"><label><input id="infrastructure" type="checkbox" disabled> Infrastructure only</label></div>
        </div>
        <div class="inventory-meta"><span id="inventory-status" class="muted" role="status">Inventory not loaded.</span><span>50 servers / request</span></div>
        <p id="inventory-freshness" class="inventory-freshness" role="status" hidden></p>
        <div class="selection-bar"><span id="selection-status" role="status">0 selected</span><button id="clear-selection" class="text-button" disabled>Clear selection</button></div>
        <p id="selection-limit" class="selection-limit" hidden>These visible servers would exceed the 50-server limit. Select individual servers or narrow your search.</p>
        <div class="table-scroll" tabindex="0" role="region" aria-label="Server inventory table"><table><thead><tr><th scope="col"><input type="checkbox" id="select-all" aria-label="Select all visible servers" aria-describedby="selection-status" disabled></th><th scope="col">SERVER</th><th scope="col">TYPE</th><th scope="col">LAST REQUEST<span class="column-note">This session only</span></th></tr></thead><tbody id="servers"></tbody></table></div>
        <div class="empty-state"><p id="empty" class="empty">Your inventory will appear here.</p></div>
      </div>
      <aside class="panel control">
        <div class="control-heading"><p class="eyebrow">02 / REVIEW &amp; ACT</p><span class="control-label">MANUAL CONTROL</span></div>
        <h2>The red button</h2>
        <p class="muted">Pause backups. Keep control.</p>
        <div class="button-stage">
          <button id="red-button" disabled aria-label="Review disable backups request" aria-describedby="button-guidance"><span class="button-label">DISABLE<br>BACKUPS</span><span class="button-caption">REVIEW &amp; CONFIRM</span></button>
          <p id="button-guidance" class="button-guidance">Review first. Nothing changes until you confirm.</p>
        </div>
        <div class="selection"><strong id="selection-count">0</strong> <span id="selection-noun">servers selected</span></div>
        <div class="control-scope"><span>SCOPE OF ACTION</span><p class="fine">Selected servers only. Running jobs and restores are not affected.</p></div>
        <div class="safeguard"><span class="status-dot"></span><span>Confirmation required for every request</span></div>
      </aside>
    <section id="activity" class="panel activity" aria-labelledby="results-title">
      <div class="panel-heading"><div><p class="eyebrow">03 / VERIFY</p><h2 id="results-title" tabindex="-1">Action results</h2></div><span id="result-state" class="result-state">No actions yet</span></div>
      <p id="result-summary" role="status">No requests yet.</p>
      <p id="result-next-step" class="result-next-step">Results show requests made in this session, not current backup state.</p>
      <div id="request-tracking" class="request-tracking" hidden>
        <button id="check-status" class="secondary" hidden>Check status</button>
        <button id="stop-tracking" class="text-button" hidden>Stop tracking</button>
        <p id="tracking-message" role="status"></p>
        <p id="tracking-storage-warning" class="fine" role="status"></p>
        <form id="lookup-request">
          <label for="request-id">Find a saved request</label>
          <div class="request-lookup"><input id="request-id" type="text" placeholder="Request ID" autocomplete="off" spellcheck="false" required aria-describedby="tracking-help"><button id="lookup-submit" class="secondary" type="submit">Look up</button></div>
          <p id="tracking-help" class="fine">Only requests submitted by your signed-in account can be viewed. Status is not a query of current backup state.</p>
        </form>
      </div>
      <ul id="results" aria-label="Per-server action results"></ul>
      <details id="result-details" class="support-details" hidden>
        <summary>Support details</summary>
        <p class="fine">Includes server names and IDs. Share only with your trusted support team.</p>
        <pre id="result-detail-text" tabindex="0" aria-label="Request support details"></pre>
        <div class="copy-controls"><button id="copy-details" class="secondary">Copy details</button><span id="copy-status" role="status"></span></div>
      </details>
    </section>
    </section>
    <footer><span id="footer-name">Red Button</span><a id="support-link" hidden target="_blank" rel="noopener noreferrer">Contact support<span class="sr-only"> (opens in a new tab)</span></a></footer>
  </main>
  <dialog id="confirm-dialog">
    <form id="confirm-form">
      <p class="eyebrow">CONFIRM OPERATION</p><h2 id="dialog-title" tabindex="-1">Disable backups?</h2>
      <p id="confirm-mode" class="notice"></p><p id="confirm-count"></p>
      <ul id="confirm-targets" class="target-list" aria-label="Selected servers"></ul>
      <label class="field">Request automatic re-enable after (minutes)<input id="delay" type="number" min="1" max="1440" value="60" required></label>
      <label class="check"><input id="indefinite" type="checkbox"> Keep disabled until re-enabled in Commvault instead</label>
      <p id="schedule-summary" class="schedule-summary" role="status"></p>
      <label class="field">Type <strong>DISABLE BACKUPS</strong> to confirm<input id="confirmation" autocomplete="off" spellcheck="false" placeholder="DISABLE BACKUPS" required></label>
      <p id="confirmation-help" class="fine">A successful response means Commvault accepted the request. Check Commvault for the current backup state and any re-enable schedule.</p>
      <div class="dialog-actions"><button type="button" id="cancel" class="secondary">Cancel</button><button type="submit" id="confirm-submit" class="danger" disabled>Confirm disable</button></div>
    </form>
  </dialog>
  <dialog id="stop-tracking-dialog" aria-labelledby="stop-tracking-title">
    <h2 id="stop-tracking-title">Stop tracking this request?</h2>
    <p>This does not cancel queued or running work. Save the Request ID and verify its outcome before submitting the same operation again.</p>
    <div class="dialog-actions"><button id="keep-tracking" class="secondary">Keep tracking</button><button id="confirm-stop-tracking" class="secondary">Stop tracking</button></div>
  </dialog>
`;

const $ = (id) => document.getElementById(id);
const state = { config: null, msal: null, account: null, servers: [], selected: new Set(), results: new Map(), canDisable: false, busy: false, phase: "", loaded: false, inventoryFailed: false, updatedAt: null, inventory: null, requestId: null, requestTargets: null, trackingBlocked: false, polling: false, pollTimer: null };
const queuedMode = () => state.config?.executionMode === "queued";
const validRequestId = (value) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const terminalRequestStates = new Set(["completed", "partial", "failed", "unknown"]);
const showError = (message) => { $("error").textContent = message; $("error").hidden = false; };
const clearError = () => { $("error").hidden = true; $("error").textContent = ""; };
const safeError = (error) => error.errorCode ? `Microsoft sign-in failed (${error.errorCode}).` : error.message;
const displayName = (server) => server.displayName || server.name;
const visibleServers = () => {
  const query = $("server-search").value.trim().toLowerCase();
  return state.servers.filter((server) => [server.name, server.displayName, server.hostName, String(server.id)]
    .some((value) => value?.toLowerCase().includes(query)));
};

class ApiError extends Error {
  constructor(message, requestId, status) {
    super(message);
    this.requestId = requestId;
    this.status = status;
  }
}

function applyBranding(config) {
  const name = config.displayName ?? "Red Button";
  $("brand-name").textContent = name;
  $("footer-name").textContent = name;
  document.querySelector(".brand").setAttribute("aria-label", `${name} home`);
  document.title = `${name} | Backup control`;
  if (name !== "Red Button") $("page-title").textContent = name;
  if (config.supportUrl) {
    const support = new URL(config.supportUrl);
    if (support.protocol !== "https:" || support.username || support.password) {
      throw new Error("The support destination is invalid. Contact your administrator.");
    }
    $("support-link").href = support.href;
    $("support-link").hidden = false;
  }
}

function setSupportDetails(details) {
  state.supportDetails = details;
  $("result-detail-text").textContent = JSON.stringify(details, null, 2);
  $("result-details").hidden = false;
}

function requestStorageKey() {
  return `red-button:last-request:${state.config.tenantId}:${state.config.clientId}:${state.account.homeAccountId}`;
}

function rememberRequest(id) {
  $("request-id").value = id;
  try {
    localStorage.setItem(requestStorageKey(), id);
    $("tracking-storage-warning").textContent = "";
  } catch {
    $("tracking-storage-warning").textContent = "Browser storage is unavailable. Save the Request ID in support details so you can look it up later.";
  }
}

function forgetRequest() {
  clearTimeout(state.pollTimer);
  state.requestId = null;
  state.requestTargets = null;
  state.trackingBlocked = false;
  state.polling = false;
  try {
    localStorage.removeItem(requestStorageKey());
  } catch {
    $("tracking-storage-warning").textContent = "The saved browser reference could not be cleared; this request may reappear after reload.";
  }
}

function validateQueuedRecord(data) {
  const statuses = new Set(["queued", "running", ...terminalRequestStates]);
  const targetStatuses = new Set(["pending", "running", "accepted", "failed", "unknown"]);
  const ids = data?.serverIds;
  if (data?.requestId !== state.requestId || !statuses.has(data.status)
    || !["stub", "live"].includes(data.mode)
    || typeof data.submittedAt !== "string" || !Number.isFinite(Date.parse(data.submittedAt))
    || typeof data.updatedAt !== "string" || !Number.isFinite(Date.parse(data.updatedAt))
    || !Array.isArray(ids) || !ids.length || ids.length > 50
    || ids.some((id) => !Number.isInteger(id) || id <= 0 || id > 2147483647)
    || new Set(ids).size !== ids.length
    || (state.requestTargets && (ids.length !== state.requestTargets.length || ids.some((id) => !state.requestTargets.includes(id))))
    || !Array.isArray(data.results) || data.results.length !== ids.length
    || new Set(data.results.map((item) => item?.serverId)).size !== ids.length
    || data.results.some((item) => !ids.includes(item?.serverId) || !targetStatuses.has(item.status)
      || (item.status === "accepted" ? item.success !== true : item.success !== false && item.success !== null))
    || (terminalRequestStates.has(data.status) && data.results.some((item) => ["pending", "running"].includes(item.status)))
    || (data.status === "completed" && data.results.some((item) => item.status !== "accepted"))
    || (data.status === "queued" && data.results.some((item) => item.status !== "pending"))) {
    throw new Error("The saved request returned incomplete or invalid status information.");
  }
  if (terminalRequestStates.has(data.status)) {
    const expected = data.results.some((item) => item.status === "unknown") ? "unknown"
      : data.results.every((item) => item.status === "accepted") ? "completed"
        : data.results.some((item) => item.status === "accepted") ? "partial" : "failed";
    if (data.status !== expected) throw new Error("The saved request returned inconsistent outcomes.");
  }
}

function renderQueuedRecord(data) {
  validateQueuedRecord(data);
  state.requestTargets = data.serverIds;
  state.trackingBlocked = !terminalRequestStates.has(data.status);
  const labels = { queued: "Queued", running: "Processing", completed: "Requests accepted", partial: "Partially accepted", failed: "Requests failed", unknown: "Check outcomes" };
  $("result-state").textContent = labels[data.status];
  $("result-state").dataset.tone = state.trackingBlocked ? "pending" : data.status === "completed" ? "success" : "failure";
  const accepted = data.results.filter((item) => item.status === "accepted").length;
  const finished = data.results.filter((item) => !["pending", "running"].includes(item.status)).length;
  $("result-summary").textContent = data.status === "queued" ? "Request saved. Waiting for a worker."
    : data.status === "running" ? `${finished} of ${data.results.length} servers processed.`
      : data.status === "unknown" ? "Outcome uncertain for one or more servers."
        : `${accepted} of ${data.results.length} requests accepted.`;
  $("result-next-step").textContent = state.trackingBlocked
    ? "Processing continues on the server. You can leave this page and look up the saved request later."
    : data.status === "completed" ? "Check Commvault to verify the backup state and any requested re-enable schedule."
      : "Check each target in Commvault before retrying. Support details include the per-server outcomes.";
  $("tracking-message").textContent = `Saved ${data.mode === "stub" ? "Demo" : "Live"} request.${data.mode !== state.config.mode ? " This is not the current environment." : ""} ${state.trackingBlocked ? "Status updates automatically. Do not submit the same operation again." : "Outcomes loaded."}`;
  const names = new Map(state.servers.map((server) => [server.id, displayName(server)]));
  const resultLabels = { pending: "Waiting", running: "Processing", accepted: "Request accepted", failed: "Needs review", unknown: "Outcome unknown - check Commvault" };
  $("results").replaceChildren();
  for (const result of data.results) {
    state.results.set(result.serverId, { ...result, unknown: result.status === "unknown" });
    const item = document.createElement("li");
    item.className = result.success ? "success-text" : ["pending", "running"].includes(result.status) ? "muted" : "failure-text";
    item.textContent = `${names.get(result.serverId) ?? `Server ${result.serverId}`}: ${resultLabels[result.status]}`;
    $("results").append(item);
  }
  setSupportDetails({
    requestId: data.requestId, mode: data.mode, status: data.status,
    submittedAt: data.submittedAt, updatedAt: data.updatedAt,
    options: data.options, results: data.results,
    targets: data.serverIds.map((id) => ({ serverId: id, name: names.get(id) ?? `Server ${id}` })),
  });
  rememberRequest(data.requestId);
  renderServers();
}

function scheduleStatusCheck() {
  clearTimeout(state.pollTimer);
  if (state.trackingBlocked) state.pollTimer = setTimeout(checkRequestStatus, 3000);
}

async function checkRequestStatus() {
  if (!state.requestId || state.polling) return;
  clearTimeout(state.pollTimer);
  state.polling = true;
  const requestId = state.requestId;
  updateControls();
  try {
    const data = await api(`/api/requests/${requestId}`, { signal: AbortSignal.timeout(15000) });
    if (state.requestId !== requestId) return;
    renderQueuedRecord(data);
    scheduleStatusCheck();
  } catch (error) {
    if (state.requestId !== requestId) return;
    state.trackingBlocked = true;
    $("result-state").textContent = "Status unavailable";
    $("result-state").dataset.tone = "failure";
    $("tracking-message").textContent = "Status could not be checked. This does not cancel the request. Use Check status; do not submit a duplicate.";
    const lastKnown = state.supportDetails?.requestId === requestId ? state.supportDetails : {};
    setSupportDetails({
      ...lastKnown, requestId, statusCheckError: safeError(error),
      statusCheckHttpStatus: error instanceof ApiError ? error.status : undefined,
    });
  } finally {
    if (state.requestId === requestId) {
      state.polling = false;
      updateControls();
    }
  }
}

$("check-status").addEventListener("click", checkRequestStatus);
$("stop-tracking").addEventListener("click", () => $("stop-tracking-dialog").showModal());
$("keep-tracking").addEventListener("click", () => $("stop-tracking-dialog").close());
$("confirm-stop-tracking").addEventListener("click", () => {
  forgetRequest();
  $("stop-tracking-dialog").close();
  $("result-state").textContent = "Tracking stopped";
  $("result-state").dataset.tone = "pending";
  $("tracking-message").textContent = "Tracking stopped, not processing. Verify the request's outcome before submitting the same operation again.";
  updateControls();
  $("results-title").focus();
});
$("lookup-request").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("request-id").value.trim().toLowerCase();
  if (!validRequestId(id)) {
    $("tracking-message").textContent = "Enter a valid Request ID from support details.";
    return;
  }
  if (state.trackingBlocked && state.requestId !== id) {
    $("tracking-message").textContent = "Check the current request's outcome before switching to another request.";
    return;
  }
  state.requestId = id;
  state.requestTargets = null;
  state.trackingBlocked = true;
  state.selected.clear();
  $("copy-status").textContent = "";
  rememberRequest(id);
  await checkRequestStatus();
});

$("copy-details").addEventListener("click", async () => {
  $("copy-status").textContent = "";
  try {
    await navigator.clipboard.writeText($("result-detail-text").textContent);
    $("copy-status").textContent = "Details copied.";
  } catch {
    $("copy-status").textContent = "Copy unavailable. Select and copy the details above manually.";
  }
});

async function token() {
  try {
    return (await state.msal.acquireTokenSilent({ account: state.account, scopes: [state.config.scope] })).accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await state.msal.acquireTokenRedirect({ account: state.account, scopes: [state.config.scope] });
      throw new Error("Sign-in is required. No operation was submitted; retry after signing in.");
    }
    throw error;
  }
}

async function api(path, options = {}) {
  const accessToken = await token();
  const response = await fetch(path, { ...options, headers: {
    ...options.headers,
    "Content-Type": "application/json", Authorization: `Bearer ${accessToken}`,
  } });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(`Invalid server response (HTTP ${response.status}).`, response.headers.get("X-Request-Id"), response.status);
  }
  if (!response.ok) throw new ApiError(data.error ?? `Request failed (HTTP ${response.status}).`, data.requestId ?? response.headers.get("X-Request-Id"), response.status);
  return data;
}

function updateControls() {
  const visible = visibleServers();
  const visibleSelected = visible.filter((s) => state.selected.has(s.id)).length;
  const hiddenSelected = state.selected.size - visibleSelected;
  const allVisibleSelected = visible.length > 0 && visibleSelected === visible.length;
  const exceedsLimit = state.selected.size + visible.length - visibleSelected > 50;
  $("selection-count").textContent = state.selected.size;
  $("selection-noun").textContent = state.selected.size === 1 ? "server selected" : "servers selected";
  $("red-button").disabled = state.busy || state.trackingBlocked || !state.canDisable || state.selected.size === 0 || state.selected.size > 50;
  $("refresh").disabled = state.busy || !state.account;
  $("infrastructure").disabled = state.busy || !state.account;
  $("server-search").disabled = state.busy || !state.loaded;
  $("select-all").disabled = state.busy || state.trackingBlocked || !state.canDisable || !visible.length || (exceedsLimit && !allVisibleSelected);
  $("select-all").checked = allVisibleSelected;
  $("select-all").indeterminate = visibleSelected > 0 && !allVisibleSelected;
  $("selection-status").textContent = `${state.selected.size} of 50 selected${hiddenSelected ? ` / ${hiddenSelected} hidden by search` : ""}`;
  $("selection-limit").hidden = !exceedsLimit || !state.canDisable;
  $("clear-selection").disabled = state.busy || state.selected.size === 0;
  $("sign-in").disabled = state.busy || !state.config?.identityConfigured;
  $("inventory").setAttribute("aria-busy", String(state.phase === "loading"));
  $("red-button").setAttribute("aria-busy", String(state.phase === "submitting"));
  $("refresh").textContent = state.phase === "loading" ? "Loading..." : state.inventoryFailed ? "Retry inventory" : queuedMode() ? "Reload inventory" : "Refresh";
  $("check-status").hidden = !state.requestId;
  $("stop-tracking").hidden = !state.requestId;
  $("stop-tracking").disabled = state.busy;
  $("check-status").disabled = state.busy || state.polling;
  $("lookup-submit").disabled = state.busy || state.polling;
  $("request-id").disabled = state.busy || state.polling;
  $("red-button").querySelector(".button-caption").textContent = state.phase === "submitting" ? "SUBMITTING..." : "REVIEW & CONFIRM";
  let guidance = "Review first. Nothing changes until you confirm.";
  if (!state.config) guidance = "Connecting to the application...";
  else if (!state.config.identityConfigured) guidance = "Unavailable until sign-in is restored.";
  else if (!state.account) guidance = "Sign in with Microsoft to get started.";
  else if (state.phase === "submitting") guidance = "Request in progress. Do not retry or close this page.";
  else if (state.phase === "loading") guidance = "Loading your server inventory...";
  else if (state.trackingBlocked) guidance = "A saved request still needs an outcome. Check its status before submitting another.";
  else if (!state.canDisable) guidance = "Read-only access. Contact your administrator to request permission.";
  else if (state.inventoryFailed) guidance = "Inventory could not be loaded. Use Retry inventory.";
  else if (!state.selected.size) guidance = "Select at least one server to enable the red button.";
  $("button-guidance").textContent = guidance;
  for (const checkbox of $("servers").querySelectorAll("input")) {
    checkbox.disabled = state.busy || state.trackingBlocked || !state.canDisable || (state.selected.size >= 50 && !checkbox.checked);
    checkbox.closest("tr").classList.toggle("selected-row", checkbox.checked);
  }
}

function renderServers() {
  const visible = visibleServers();
  $("servers").replaceChildren();
  $("server-count").textContent = state.servers.length;
  $("empty").hidden = visible.length > 0;
  if (state.loaded) {
    $("empty").textContent = state.servers.length ? "No matching servers. Try a different name, hostname, or ID." : "No servers returned. Try turning off Infrastructure only or refresh the inventory.";
    $("inventory-status").textContent = `${visible.length} of ${state.servers.length} shown / ${queuedMode() ? "Cached as of" : "Updated"} ${state.updatedAt.toLocaleString([], { ...(queuedMode() ? { month: "short", day: "numeric" } : {}), hour: "2-digit", minute: "2-digit" })}`;
  }
  $("inventory-freshness").hidden = !state.loaded || !state.inventory || (!state.inventory.stale && !state.inventory.refreshError);
  $("inventory-freshness").textContent = state.inventory?.stale
    ? "Cached inventory is out of date. Confirm target identity before submitting; the background refresh has not supplied a fresh list."
    : state.inventory?.refreshError ? "The last background refresh failed. Showing the last known inventory." : "";
  for (const server of visible) {
    const row = document.createElement("tr");
    const checkCell = row.insertCell();
    const check = document.createElement("input");
    check.type = "checkbox";
    check.setAttribute("aria-label", `Select ${server.displayName || server.name}`);
    check.checked = state.selected.has(server.id);
    check.addEventListener("change", () => {
      if (check.checked && state.selected.size < 50) state.selected.add(server.id);
      else { state.selected.delete(server.id); check.checked = false; }
      updateControls();
    });
    checkCell.append(check);
    const nameCell = row.insertCell();
    const name = document.createElement("strong");
    name.textContent = server.displayName || server.name;
    const details = document.createElement("small");
    details.textContent = `${server.hostName || server.name} / ID ${server.id}`;
    nameCell.append(name, details);
    row.insertCell().textContent = typeof server.isInfrastructure !== "boolean" ? "Unknown" : server.isInfrastructure ? "Infrastructure" : "Workload";
    const result = state.results.get(server.id);
    const status = row.insertCell();
    const pending = result && ["pending", "running"].includes(result.status);
    status.textContent = pending ? result.status === "pending" ? "Waiting" : "Processing" : result ? result.unknown ? "Outcome unknown" : result.success ? "Request accepted" : "Failed / check result" : "No action";
    status.className = pending ? "muted" : result ? result.success ? "success-text" : "failure-text" : "muted";
    $("servers").append(row);
  }
  updateControls();
}

async function refresh() {
  if (state.busy) return;
  clearError();
  state.busy = true;
  state.phase = "loading";
  state.inventoryFailed = false;
  state.selected.clear();
  $("inventory-status").textContent = "Loading servers. Selection is cleared when inventory is refreshed.";
  updateControls();
  try {
    const data = await api(`/api/servers?showOnlyInfrastructureMachines=${$("infrastructure").checked ? 1 : 0}`);
    if (queuedMode() && (!data.inventory || typeof data.inventory.stale !== "boolean"
      || typeof data.inventory.updatedAt !== "string" || Number.isNaN(Date.parse(data.inventory.updatedAt)))) {
      throw new Error("Cached inventory has no valid refresh timestamp.");
    }
    state.servers = data.servers;
    state.loaded = true;
    state.inventory = data.inventory ?? null;
    state.updatedAt = queuedMode() ? new Date(data.inventory.updatedAt) : new Date();
    renderServers();
  } catch (error) {
    state.servers = [];
    state.loaded = false;
    state.inventoryFailed = true;
    renderServers();
    $("inventory-status").textContent = "Inventory unavailable. Retry when the connection is restored.";
    $("empty").textContent = "Inventory could not be loaded. See the error above.";
    showError(safeError(error));
  } finally {
    state.busy = false;
    state.phase = "";
    updateControls();
  }
}

$("sign-in").addEventListener("click", async () => {
  clearError();
  clearTimeout(state.pollTimer);
  try {
    if (state.account) await state.msal.logoutRedirect({ account: state.account, postLogoutRedirectUri: state.config.redirectUri });
    else await state.msal.loginRedirect({ scopes: [state.config.scope] });
  } catch (error) { showError(safeError(error)); }
});
$("refresh").addEventListener("click", refresh);
$("infrastructure").addEventListener("change", refresh);
$("server-search").addEventListener("input", renderServers);
$("clear-selection").addEventListener("click", () => { state.selected.clear(); renderServers(); });
$("select-all").addEventListener("change", () => {
  const visible = visibleServers();
  if ($("select-all").checked) {
    const combined = new Set([...state.selected, ...visible.map((s) => s.id)]);
    if (combined.size <= 50) state.selected = combined;
  } else {
    visible.forEach((s) => state.selected.delete(s.id));
  }
  renderServers();
});
$("red-button").addEventListener("click", () => {
  if ($("red-button").disabled) return;
  $("confirmation").value = "";
  $("confirm-submit").disabled = true;
  $("delay").value = "60";
  $("indefinite").checked = false;
  $("delay").disabled = false;
  $("delay").required = true;
  $("confirm-mode").textContent = state.config.mode === "stub" ? "DEMO: only simulated servers will change." : "LIVE: this will change the client's backup configuration.";
  $("confirm-count").textContent = `${state.selected.size} selected ${state.selected.size === 1 ? "server" : "servers"}. Only these targets will be affected.`;
  $("confirm-targets").replaceChildren();
  for (const server of state.servers.filter((s) => state.selected.has(s.id))) {
    const item = document.createElement("li");
    item.textContent = `${displayName(server)} / ${server.hostName || server.name} / ID ${server.id}`;
    $("confirm-targets").append(item);
  }
  updateSchedule();
  $("confirm-dialog").showModal();
  $("dialog-title").focus();
});
$("confirm-dialog").setAttribute("aria-labelledby", "dialog-title");
$("cancel").addEventListener("click", () => $("confirm-dialog").close());
$("confirmation").addEventListener("input", () => { $("confirm-submit").disabled = $("confirmation").value !== "DISABLE BACKUPS"; });
function updateSchedule() {
  if ($("indefinite").checked) {
    $("schedule-summary").textContent = "No automatic re-enable. You must re-enable backups in Commvault.";
  } else if ($("delay").validity.valid && $("delay").value) {
    const minutes = Number($("delay").value);
    const deadline = new Date(Date.now() + minutes * 60000);
    $("schedule-summary").textContent = `Re-enable requested ${minutes} minutes after confirmation (approximately ${deadline.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}, your local time).${queuedMode() ? " This deadline does not move if processing starts later." : ""}`;
  } else {
    $("schedule-summary").textContent = "Choose a whole number from 1 to 1,440 minutes.";
  }
}
$("delay").addEventListener("input", updateSchedule);
$("indefinite").addEventListener("change", () => {
  $("delay").disabled = $("indefinite").checked;
  $("delay").required = !$("indefinite").checked;
  updateSchedule();
});
$("confirm-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || state.trackingBlocked || !state.canDisable || $("confirmation").value !== "DISABLE BACKUPS" || !$("confirm-form").reportValidity()) return;
  const serverIds = [...state.selected];
  const targetNames = new Map(state.servers.map((s) => [s.id, displayName(s)]));
  const options = $("indefinite").checked ? {} : { enableAfterADelay: Math.floor(Date.now() / 1000) + Number($("delay").value) * 60 };
  const supportContext = {
    submittedAt: new Date().toISOString(),
    environment: state.config.mode === "stub" ? "Demo" : "Live",
    targets: serverIds.map((id) => ({ serverId: id, name: targetNames.get(id) })),
    requestedReenableAt: options.enableAfterADelay ? new Date(options.enableAfterADelay * 1000).toISOString() : null,
  };
  $("confirm-dialog").close();
  clearError();
  state.busy = true;
  state.phase = "submitting";
  updateControls();
  $("result-state").textContent = "In progress";
  $("result-state").dataset.tone = "pending";
  $("results-title").focus();
  $("result-summary").textContent = "Submitting selected servers. Do not retry while this request is running.";
  $("result-next-step").textContent = "Keep this page open while the requests are processed.";
  $("results").replaceChildren();
  $("result-details").hidden = true;
  $("result-details").open = false;
  $("result-detail-text").textContent = "";
  $("copy-status").textContent = "";
  if (queuedMode()) {
    state.requestId = crypto.randomUUID();
    state.requestTargets = serverIds;
    state.trackingBlocked = true;
    rememberRequest(state.requestId);
    setSupportDetails({ ...supportContext, requestId: state.requestId });
  }
  try {
    const data = await api("/api/disable", {
      method: "POST",
      ...(queuedMode() ? { headers: { "Idempotency-Key": state.requestId }, signal: AbortSignal.timeout(20000) } : {}),
      body: JSON.stringify({ serverIds, confirmation: "DISABLE BACKUPS", options }),
    });
    if (queuedMode()) {
      renderQueuedRecord(data);
      scheduleStatusCheck();
      return;
    }
    if (!Array.isArray(data.results) || data.results.length !== serverIds.length
      || new Set(data.results.map((result) => result?.serverId)).size !== serverIds.length
      || data.results.some((result) => !serverIds.includes(result?.serverId) || typeof result.success !== "boolean")) {
      throw new ApiError("The server returned incomplete or invalid request results.", data.requestId);
    }
    const accepted = data.results.filter((r) => r.success).length;
    $("result-state").textContent = accepted === data.results.length ? "Requests accepted" : accepted ? "Partially accepted" : "Requests failed";
    $("result-state").dataset.tone = accepted === data.results.length ? "success" : "failure";
    $("result-summary").textContent = `${accepted} of ${data.results.length} requests accepted.`;
    $("result-next-step").textContent = accepted === data.results.length
      ? "Check Commvault to verify the backup state and any re-enable schedule."
      : "Some requests need review. Check their outcomes in Commvault before retrying; support details are available below.";
    setSupportDetails({ ...supportContext, requestId: data.requestId, results: data.results });
    for (const result of data.results) {
      state.results.set(result.serverId, result);
      const li = document.createElement("li");
      li.className = result.success ? "success-text" : "failure-text";
      li.textContent = `${targetNames.get(result.serverId)}: ${result.success ? "Request accepted" : "Needs review - check Commvault before retrying."}`;
      $("results").append(li);
    }
  } catch (error) {
    $("result-state").textContent = "Check outcomes";
    $("result-state").dataset.tone = "failure";
    $("result-summary").textContent = "Outcome unknown. Some operations may have completed.";
    $("result-next-step").textContent = "Do not assume the request failed. Check each target in Commvault before submitting again.";
    setSupportDetails({
      ...supportContext,
      outcome: "Unknown",
      error: safeError(error),
      ...(error instanceof ApiError ? { requestId: error.requestId, httpStatus: error.status } : {}),
      ...(queuedMode() ? { requestId: state.requestId } : {}),
    });
    serverIds.forEach((id) => state.results.set(id, { unknown: true, success: false }));
    if (queuedMode() && error instanceof ApiError && [400, 401, 403, 413].includes(error.status)) {
      forgetRequest();
      serverIds.forEach((id) => state.results.set(id, { success: false, status: "failed" }));
      $("result-state").textContent = "Request rejected";
      $("result-summary").textContent = "The request was rejected before it could be queued.";
      $("result-next-step").textContent = "Resolve the reported problem before submitting another request.";
      $("tracking-message").textContent = "";
      showError(safeError(error));
    } else if (queuedMode()) {
      $("result-next-step").textContent = "Submission could not be confirmed. Check the saved Request ID before trying another operation.";
      $("tracking-message").textContent = "The request may have been queued. Checking its saved status does not repeat the operation.";
      await checkRequestStatus();
    } else {
      showError("We could not confirm all outcomes. Check Commvault before retrying, or share the support details with your administrator.");
    }
  } finally {
    state.selected.clear();
    state.busy = false;
    state.phase = "";
    renderServers();
    $("results-title").focus();
  }
});

async function initialize() {
  const response = await fetch("/api/config");
  if (!response.ok) throw new Error(`Unable to connect to the application (HTTP ${response.status}).`);
  state.config = await response.json();
  applyBranding(state.config);
  if (queuedMode()) {
    $("request-tracking").hidden = false;
    document.querySelector(".column-note").textContent = "Tracked requests";
    $("result-next-step").textContent = "Requests are saved on the server. Look up a Request ID to recover its outcomes.";
    $("confirmation-help").textContent = "Confirmation queues a request; it does not mean backups have changed. Check Commvault for the actual backup state and any re-enable schedule.";
  }
  const demo = state.config.mode === "stub";
  $("mode").textContent = demo ? "DEMO" : "LIVE";
  $("mode").classList.toggle("live", !demo);
  $("notice").textContent = demo
    ? "Simulated environment. No real backups will change."
    : "Live environment. Actions change real backup settings. Verify your selected servers before proceeding.";
  if (!state.config.identityConfigured) {
    $("sign-in").textContent = "Sign-in unavailable";
    showError("Sign-in is currently unavailable. Contact your administrator.");
    updateControls();
    return;
  }
  state.msal = new PublicClientApplication({
    auth: { clientId: state.config.clientId, authority: `https://login.microsoftonline.com/${state.config.tenantId}`, redirectUri: state.config.redirectUri },
    cache: { cacheLocation: "sessionStorage" },
  });
  await state.msal.initialize();
  const redirect = await state.msal.handleRedirectPromise();
  state.account = redirect?.account ?? state.msal.getActiveAccount() ?? state.msal.getAllAccounts()[0] ?? null;
  if (state.account) {
    state.msal.setActiveAccount(state.account);
    $("account-name").textContent = state.account.name || state.account.username;
    $("sign-in").textContent = "Sign out";
    const me = await api("/api/me");
    state.canDisable = me.canDisable;
    await refresh();
    if (queuedMode()) {
      let previous;
      try {
        previous = localStorage.getItem(requestStorageKey());
      } catch {
        $("tracking-storage-warning").textContent = "Browser storage is unavailable. Use a saved Request ID to look up earlier work.";
      }
      if (previous) {
        if (validRequestId(previous)) {
          state.requestId = previous.toLowerCase();
          state.trackingBlocked = true;
          $("request-id").value = state.requestId;
          await checkRequestStatus();
        } else {
          $("tracking-storage-warning").textContent = "The saved request reference is invalid. Use a Request ID from support details.";
        }
      }
    }
  }
  updateControls();
}
initialize().catch((error) => { showError(safeError(error)); updateControls(); });

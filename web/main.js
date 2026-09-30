import { PublicClientApplication, InteractionRequiredAuthError } from "@azure/msal-browser";
import "./style.css";

document.querySelector("#app").innerHTML = `
  <a class="skip-link" href="#workspace">Skip to backup controls</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="Red Button home"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name" id="brand-name">Red Button</span></a>
    <div class="account"><span id="account-name"></span><button id="sign-in" class="secondary" disabled>Sign in with Microsoft</button></div>
  </header>
  <main>
    <section class="heading" aria-labelledby="page-title">
      <div class="hero-copy"><h1 id="page-title">The <span class="hero-red">Red Button.</span></h1></div>
      <div class="hero-aside"><div id="mode" class="mode">CONNECTING</div></div>
    </section>
    <div id="notice" class="notice" role="status">Connecting to the application...</div>
    <div id="error" class="error" role="alert" hidden></div>
    <section id="workspace" class="workspace" tabindex="-1" aria-label="Backup controls">
      <div id="inventory" class="panel inventory" aria-busy="false">
        <div class="panel-heading"><h2>Servers <span id="server-count" class="count">0</span></h2><button id="refresh" class="secondary" disabled>Refresh</button></div>
        <div class="inventory-toolbar">
          <div class="search-row"><label for="server-search" class="sr-only">Find a server</label><div class="search-input"><span aria-hidden="true" class="search-icon"></span><input id="server-search" type="search" placeholder="Search servers, hostnames, or IDs" disabled autocomplete="off"></div></div>
        </div>
        <div class="inventory-meta"><span id="inventory-status" class="muted" role="status">Inventory not loaded.</span></div>
        <p id="inventory-freshness" class="inventory-freshness" role="status" hidden></p>
        <div class="selection-bar">
          <label class="page-selection"><input type="checkbox" id="select-page" aria-describedby="selection-status" disabled> Select page</label>
          <button id="select-all" class="text-button" aria-describedby="selection-status" disabled>Select all</button>
          <span id="selection-status" role="status"><strong id="selection-count">0</strong> selected<span id="off-page-count"></span></span>
          <button id="clear-selection" class="text-button" disabled>Clear selection</button>
        </div>
        <div class="table-scroll" tabindex="0" role="region" aria-label="Server inventory table"><table><thead><tr><th scope="col"><span class="sr-only">Select server</span></th><th scope="col">SERVER</th><th scope="col">TYPE</th><th scope="col">LAST REQUEST<span class="column-note">This session only</span></th></tr></thead><tbody id="servers"></tbody></table></div>
        <div class="empty-state"><p id="empty" class="empty">Your inventory will appear here.</p></div>
        <nav id="pagination" class="pagination" aria-label="Server pages" hidden>
          <button id="previous-page" class="secondary" disabled>Previous</button>
          <span id="page-status" role="status"></span>
          <button id="next-page" class="secondary" disabled>Next</button>
        </nav>
      </div>
      <aside class="panel control">
        <h2>Backup control</h2>
        <div class="button-stage">
          <button id="red-button" disabled aria-label="Review disable backups request" aria-describedby="button-guidance"><span class="button-label">DISABLE<br>BACKUPS</span><span class="button-caption">REVIEW &amp; CONFIRM</span></button>
          <p id="button-guidance" class="button-guidance">Review first. Nothing changes until you confirm.</p>
        </div>
        <details id="timing-options" class="timing-options">
          <summary id="timing-label">Duration: 60 minutes</summary>
          <form id="options-form">
            <label class="field">Duration (minutes)<input id="delay" type="number" min="1" max="1440" step="1" value="60" required disabled></label>
            <label class="check"><input id="indefinite" type="checkbox" disabled> Until manually re-enabled</label>
          </form>
        </details>
      </aside>
    <section id="activity" class="panel activity" aria-labelledby="results-title">
      <div class="panel-heading"><h2 id="results-title" tabindex="-1">Action results</h2><span id="result-state" class="result-state">No actions yet</span></div>
      <p id="result-summary" role="status">No requests yet.</p>
      <p id="result-next-step" class="result-next-step" hidden></p>
      <div id="request-tracking" class="request-tracking" hidden>
        <button id="check-status" class="secondary" hidden>Retry status</button>
        <p id="tracking-message" role="status"></p>
        <p id="tracking-storage-warning" class="fine" role="status"></p>
      </div>
      <ul id="results" aria-label="Per-server action results"></ul>
      <details id="result-details" class="support-details" hidden>
        <summary>Support details</summary>
        <form id="lookup-request" hidden>
          <label for="request-id">Find a saved request</label>
          <div class="request-lookup"><input id="request-id" type="text" placeholder="Request ID" autocomplete="off" spellcheck="false" required aria-describedby="tracking-help"><button id="lookup-submit" class="secondary" type="submit">Look up</button></div>
          <p id="tracking-help" class="fine">Your requests only.</p>
          <p id="lookup-message" role="status"></p>
        </form>
        <div id="result-support" hidden>
        <p class="fine">Includes server names and IDs. Share only with your trusted support team.</p>
        <pre id="result-detail-text" tabindex="0" aria-label="Request support details"></pre>
        <div class="copy-controls"><button id="copy-details" class="secondary">Copy details</button><span id="copy-status" role="status"></span></div>
        </div>
      </details>
    </section>
    </section>
    <footer><span id="footer-name">Red Button</span><a id="support-link" hidden target="_blank" rel="noopener noreferrer">Contact support<span class="sr-only"> (opens in a new tab)</span></a></footer>
  </main>
  <dialog id="confirm-dialog">
    <form id="confirm-form">
      <div class="confirmation-heading"><h2 id="dialog-title" tabindex="-1"></h2><span id="confirm-mode" class="mode"></span></div>
      <p id="confirm-count"></p>
      <ul id="confirm-targets" class="target-list" aria-label="Selected servers" tabindex="0"></ul>
      <details id="server-details" class="server-details">
        <summary>Server details</summary>
        <ul id="confirm-server-details" class="target-list" aria-label="Selected server details" tabindex="0"></ul>
      </details>
      <div class="dialog-actions"><button type="button" id="cancel" class="secondary">Cancel</button><button type="submit" id="confirm-submit" class="danger">Disable backups</button></div>
    </form>
  </dialog>
`;

const $ = (id) => document.getElementById(id);
const PAGE_SIZE = 10;
const state = { config: null, msal: null, account: null, servers: [], page: 0, selected: new Set(), confirmation: null, results: new Map(), canDisable: null, busy: false, phase: "", loaded: false, inventoryFailed: false, updatedAt: null, inventory: null, requestId: null, requestTargets: null, trackingBlocked: false, statusUnavailable: false, polling: false, pollTimer: null };
const queuedMode = () => state.config?.executionMode === "queued";
const validRequestId = (value) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const terminalRequestStates = new Set(["completed", "partial", "failed", "unknown"]);
const showError = (message) => { $("error").textContent = message; $("error").hidden = false; };
const clearError = () => { $("error").hidden = true; $("error").textContent = ""; };
const safeError = (error) => error.errorCode ? `Microsoft sign-in failed (${error.errorCode}).` : error.message;
const displayName = (server) => server.displayName || server.name;
const durationLabel = (minutes) => `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
const matchingServers = () => {
  const query = $("server-search").value.trim().toLowerCase();
  return state.servers.filter((server) => [server.name, server.displayName, server.hostName, String(server.id)]
    .some((value) => value?.toLowerCase().includes(query)));
};
const visibleServers = () => matchingServers().slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE);
const selectionIncluding = (servers) => new Set([...state.selected, ...servers.map((server) => server.id)]);

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
  $("result-support").hidden = false;
}

function commandSummary(accepted, total) {
  return accepted === total
    ? `Disable command accepted for ${total} server${total === 1 ? "" : "s"}.`
    : `${accepted} of ${total} disable commands accepted.`;
}

function requestStorageKey() {
  const tenant = state.account.tenantId ?? state.config.tenantId;
  const context = tenant === state.config.tenantId ? "" : `:${tenant}`;
  return `red-button:last-request:${state.config.tenantId}:${state.config.clientId}:${state.account.homeAccountId}${context}`;
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
  state.statusUnavailable = false;
  state.polling = false;
  try {
    localStorage.removeItem(requestStorageKey());
  } catch {
    $("tracking-storage-warning").textContent = "The saved browser reference could not be cleared; this request may reappear after reload.";
  }
}

function validateQueuedRecord(data, requestId = state.requestId, requestTargets = state.requestTargets) {
  const statuses = new Set(["queued", "running", ...terminalRequestStates]);
  const targetStatuses = new Set(["pending", "running", "accepted", "failed", "unknown"]);
  const ids = data?.serverIds;
  const targetIds = new Set(Array.isArray(ids) ? ids : []);
  if (data?.requestId !== requestId || !statuses.has(data.status)
    || !["stub", "live"].includes(data.mode)
    || typeof data.submittedAt !== "string" || !Number.isFinite(Date.parse(data.submittedAt))
    || typeof data.updatedAt !== "string" || !Number.isFinite(Date.parse(data.updatedAt))
    || !Array.isArray(ids) || !ids.length
    || ids.some((id) => !Number.isInteger(id) || id <= 0 || id > 2147483647)
    || targetIds.size !== ids.length
    || (requestTargets && (ids.length !== requestTargets.length || requestTargets.some((id) => !targetIds.has(id))))
    || !Array.isArray(data.results) || data.results.length !== ids.length
    || new Set(data.results.map((item) => item?.serverId)).size !== ids.length
    || data.results.some((item) => !targetIds.has(item?.serverId) || !targetStatuses.has(item.status)
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
  state.statusUnavailable = false;
  $("lookup-message").textContent = "";
  $("result-next-step").hidden = false;
  state.requestTargets = data.serverIds;
  state.trackingBlocked = !terminalRequestStates.has(data.status);
  const labels = { queued: "Queued", running: "Processing", completed: "Request completed", partial: "Partially completed", failed: "Request failed", unknown: "Outcome unknown" };
  $("result-state").textContent = labels[data.status];
  $("result-state").dataset.tone = state.trackingBlocked ? "pending" : data.status === "completed" ? "success" : "failure";
  const accepted = data.results.filter((item) => item.status === "accepted").length;
  const finished = data.results.filter((item) => !["pending", "running"].includes(item.status)).length;
  $("result-summary").textContent = data.status === "queued" ? "Request saved. Waiting for a worker."
    : data.status === "running" ? `${finished} of ${data.results.length} servers processed.`
      : data.status === "unknown" ? "Outcome uncertain for one or more servers."
        : commandSummary(accepted, data.results.length);
  $("result-next-step").textContent = state.trackingBlocked
    ? "Updates automatically. You can leave this page."
    : data.status === "completed" ? "Backup state and re-enable are not monitored."
      : "Check each target in Commvault before retrying. Support details include the per-server outcomes.";
  $("tracking-message").textContent = data.mode !== state.config.mode
    ? `Saved ${data.mode === "stub" ? "Demo" : "Live"} request. This is not the current environment.` : "";
  const names = new Map(state.servers.map((server) => [server.id, displayName(server)]));
  const resultLabels = { pending: "Waiting", running: "Processing", accepted: "Disable command accepted", failed: "Needs review", unknown: "Outcome unknown - check Commvault" };
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
    state.statusUnavailable = true;
    $("result-state").textContent = "Status unavailable";
    $("result-state").dataset.tone = "failure";
    $("result-summary").textContent = "Unable to get the latest status.";
    $("result-next-step").hidden = false;
    $("result-next-step").textContent = "Retry status to check this request, not submit it again.";
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
$("lookup-request").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || state.polling) return;
  const id = $("request-id").value.trim().toLowerCase();
  if (!validRequestId(id)) {
    $("lookup-message").textContent = "Enter a valid Request ID.";
    return;
  }
  if (state.trackingBlocked && state.requestId !== id) {
    $("lookup-message").textContent = "Wait for the current request's outcome before looking up another.";
    return;
  }
  if (state.requestId === id) {
    await checkRequestStatus();
    return;
  }
  state.polling = true;
  $("lookup-message").textContent = "";
  updateControls();
  try {
    const data = await api(`/api/requests/${id}`, { signal: AbortSignal.timeout(15000) });
    validateQueuedRecord(data, id, null);
    state.requestId = id;
    state.requestTargets = null;
    state.selected.clear();
    $("copy-status").textContent = "";
    renderQueuedRecord(data);
    scheduleStatusCheck();
  } catch (error) {
    $("lookup-message").textContent = safeError(error);
  } finally {
    state.polling = false;
    updateControls();
  }
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
    return (await state.msal.acquireTokenSilent({
      account: state.account, scopes: [state.config.scope], redirectUri: state.config.silentRedirectUri,
    })).accessToken;
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
  const matching = matchingServers();
  const visible = visibleServers();
  const visibleSelected = visible.filter((s) => state.selected.has(s.id)).length;
  const hiddenSelected = state.selected.size - visibleSelected;
  const allVisibleSelected = visible.length > 0 && visibleSelected === visible.length;
  const allMatchingSelected = matching.every((server) => state.selected.has(server.id));
  const selectionDisabled = state.busy || state.polling || state.trackingBlocked || !state.canDisable;
  $("selection-count").textContent = state.selected.size;
  $("off-page-count").textContent = hiddenSelected ? ` (${hiddenSelected} off-page)` : "";
  $("red-button").disabled = selectionDisabled || state.selected.size === 0;
  $("refresh").disabled = state.busy || !state.account;
  $("server-search").disabled = state.busy || !state.loaded;
  $("select-page").disabled = selectionDisabled || !visible.length;
  $("select-page").checked = allVisibleSelected;
  $("select-page").indeterminate = visibleSelected > 0 && !allVisibleSelected;
  $("select-page").setAttribute("aria-label", `Select page (${visible.length} servers)`);
  $("select-all").textContent = $("server-search").value.trim() ? `Select all ${matching.length} matches` : `Select all (${matching.length})`;
  $("select-all").disabled = selectionDisabled || !matching.length || allMatchingSelected;
  $("previous-page").disabled = state.busy || state.page === 0;
  $("next-page").disabled = state.busy || (state.page + 1) * PAGE_SIZE >= matching.length;
  const timingDisabled = selectionDisabled;
  $("indefinite").disabled = timingDisabled;
  $("delay").disabled = timingDisabled || $("indefinite").checked;
  $("clear-selection").disabled = state.busy || state.selected.size === 0;
  $("sign-in").disabled = state.busy || !state.config?.identityConfigured;
  $("inventory").setAttribute("aria-busy", String(state.phase === "loading"));
  $("red-button").setAttribute("aria-busy", String(state.phase === "submitting"));
  $("refresh").textContent = state.phase === "loading" ? "Loading..." : state.account && state.canDisable === null ? "Retry sign-in" : state.inventoryFailed ? "Retry inventory" : queuedMode() ? "Reload inventory" : "Refresh";
  $("check-status").hidden = !state.requestId || !state.statusUnavailable;
  $("request-tracking").hidden = !queuedMode() || !(state.statusUnavailable || $("tracking-message").textContent || $("tracking-storage-warning").textContent);
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
  else if (state.canDisable === null) guidance = "Sign-in has not been verified. Use Retry sign-in, or sign out and sign in again.";
  else if (!state.canDisable) guidance = "Read-only access. Contact your administrator to request permission.";
  else if (state.inventoryFailed) guidance = "Inventory could not be loaded. Use Retry inventory.";
  else if (!state.selected.size) guidance = "Select at least one server to enable the red button.";
  $("button-guidance").textContent = guidance;
  for (const checkbox of $("servers").querySelectorAll("input")) {
    checkbox.disabled = selectionDisabled;
    checkbox.closest("tr").classList.toggle("selected-row", checkbox.checked);
  }
}

function renderServers() {
  const matching = matchingServers();
  const pageCount = Math.max(1, Math.ceil(matching.length / PAGE_SIZE));
  state.page = Math.min(state.page, pageCount - 1);
  const start = state.page * PAGE_SIZE;
  const visible = matching.slice(start, start + PAGE_SIZE);
  $("servers").replaceChildren();
  $("server-count").textContent = state.servers.length;
  $("empty").hidden = visible.length > 0;
  if (state.loaded) {
    $("empty").textContent = state.servers.length ? "No matching servers. Try a different name, hostname, or ID." : "No servers returned. Refresh the inventory to try again.";
    $("inventory-status").textContent = `${matching.length ? start + 1 : 0}-${start + visible.length} of ${matching.length}${queuedMode() ? ` / Cached as of ${state.updatedAt.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : ""}`;
  }
  $("pagination").hidden = !state.loaded || pageCount === 1;
  $("page-status").textContent = `Page ${state.page + 1} of ${pageCount}`;
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
      if (check.checked) state.selected.add(server.id);
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
    status.textContent = pending ? result.status === "pending" ? "Waiting" : "Processing" : result ? result.unknown ? "Outcome unknown" : result.success ? "Disable command accepted" : "Failed / check result" : "No action";
    status.className = pending ? "muted" : result ? result.success ? "success-text" : "failure-text" : "muted";
    $("servers").append(row);
  }
  updateControls();
}

async function loadPermissions() {
  const me = await api("/api/me");
  if (typeof me.canDisable !== "boolean") throw new Error("The server did not return valid operation permissions.");
  state.canDisable = me.canDisable;
}

async function refresh() {
  if (state.busy) return;
  clearError();
  state.busy = true;
  state.phase = "loading";
  state.inventoryFailed = false;
  state.selected.clear();
  state.page = 0;
  $("inventory-status").textContent = "Loading servers...";
  updateControls();
  try {
    if (state.canDisable === null) await loadPermissions();
    const data = await api("/api/servers?showOnlyInfrastructureMachines=0");
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
$("server-search").addEventListener("input", () => { state.page = 0; renderServers(); });
$("previous-page").addEventListener("click", () => {
  if (!$("previous-page").disabled) { state.page--; renderServers(); }
});
$("next-page").addEventListener("click", () => {
  if (!$("next-page").disabled) { state.page++; renderServers(); }
});
$("clear-selection").addEventListener("click", () => { state.selected.clear(); renderServers(); });
$("select-all").addEventListener("click", () => {
  if ($("select-all").disabled) return;
  state.selected = selectionIncluding(matchingServers());
  renderServers();
});
$("select-page").addEventListener("change", () => {
  if ($("select-page").disabled) return;
  const visible = visibleServers();
  if ($("select-page").checked) {
    state.selected = selectionIncluding(visible);
  } else {
    visible.forEach((s) => state.selected.delete(s.id));
  }
  renderServers();
});
$("red-button").addEventListener("click", () => {
  if ($("red-button").disabled) return;
  if (!$("options-form").checkValidity()) {
    $("timing-options").open = true;
    $("options-form").reportValidity();
    return;
  }
  state.confirmation = {
    serverIds: [...state.selected],
    delayMinutes: $("indefinite").checked ? null : Number($("delay").value),
  };
  const demo = state.config.mode === "stub";
  $("confirm-mode").textContent = demo ? "DEMO" : "LIVE";
  $("confirm-mode").classList.toggle("live", !demo);
  const count = state.confirmation.serverIds.length;
  $("confirm-count").textContent = `${count} ${count === 1 ? "server" : "servers"}`;
  $("confirm-count").hidden = count === 1;
  $("server-details").open = false;
  $("confirm-targets").replaceChildren();
  $("confirm-server-details").replaceChildren();
  for (const server of state.servers.filter((s) => state.selected.has(s.id))) {
    const item = document.createElement("li");
    item.textContent = displayName(server);
    $("confirm-targets").append(item);
    const detail = document.createElement("li");
    detail.textContent = `${displayName(server)} / ${server.hostName || server.name} / ID ${server.id}`;
    $("confirm-server-details").append(detail);
  }
  $("dialog-title").textContent = state.confirmation.delayMinutes === null
    ? "Disable backups until manually re-enabled?"
    : `Disable backups for ${durationLabel(state.confirmation.delayMinutes)}?`;
  $("confirm-dialog").showModal();
  $("dialog-title").focus();
});
$("confirm-dialog").setAttribute("aria-labelledby", "dialog-title");
$("confirm-dialog").setAttribute("aria-describedby", "confirm-mode confirm-count");
$("cancel").addEventListener("click", () => $("confirm-dialog").close());
$("confirm-dialog").addEventListener("close", () => { state.confirmation = null; });
$("options-form").addEventListener("submit", (event) => { event.preventDefault(); });
function updateSchedule() {
  if ($("indefinite").checked) {
    $("timing-label").textContent = "Duration: until manually re-enabled";
  } else if ($("delay").validity.valid && $("delay").value) {
    $("timing-label").textContent = `Duration: ${durationLabel(Number($("delay").value))}`;
  } else {
    $("timing-label").textContent = "Choose 1-1,440 whole minutes";
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
  if (state.busy || state.polling || state.trackingBlocked || !state.canDisable || !$("confirm-dialog").open || !state.confirmation) return;
  const { serverIds, delayMinutes } = state.confirmation;
  const targetNames = new Map(state.servers.map((s) => [s.id, displayName(s)]));
  const options = delayMinutes === null ? {} : { enableAfterADelay: Math.floor(Date.now() / 1000) + delayMinutes * 60 };
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
  $("result-next-step").hidden = false;
  $("result-next-step").textContent = "Keep this page open while the requests are processed.";
  $("results").replaceChildren();
  $("result-details").hidden = !queuedMode();
  $("result-support").hidden = true;
  $("result-details").open = false;
  $("result-detail-text").textContent = "";
  $("copy-status").textContent = "";
  $("lookup-message").textContent = "";
  $("tracking-message").textContent = "";
  state.statusUnavailable = false;
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
    const targetIds = new Set(serverIds);
    if (!Array.isArray(data.results) || data.results.length !== serverIds.length
      || new Set(data.results.map((result) => result?.serverId)).size !== serverIds.length
      || data.results.some((result) => !targetIds.has(result?.serverId) || typeof result.success !== "boolean")) {
      throw new ApiError("The server returned incomplete or invalid request results.", data.requestId);
    }
    const accepted = data.results.filter((r) => r.success).length;
    $("result-state").textContent = accepted === data.results.length ? "Request completed" : accepted ? "Partially completed" : "Request failed";
    $("result-state").dataset.tone = accepted === data.results.length ? "success" : "failure";
    $("result-summary").textContent = commandSummary(accepted, data.results.length);
    $("result-next-step").textContent = accepted === data.results.length
      ? "Backup state and re-enable are not monitored."
      : "Some requests need review. Check their outcomes in Commvault before retrying; support details are available below.";
    setSupportDetails({ ...supportContext, requestId: data.requestId, results: data.results });
    for (const result of data.results) {
      state.results.set(result.serverId, result);
      const li = document.createElement("li");
      li.className = result.success ? "success-text" : "failure-text";
      li.textContent = `${targetNames.get(result.serverId)}: ${result.success ? "Disable command accepted" : "Needs review - check Commvault before retrying."}`;
      $("results").append(li);
    }
  } catch (error) {
    $("result-state").textContent = "Outcome unknown";
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
    if (error instanceof ApiError && [400, 401, 403, 413].includes(error.status)) {
      if (queuedMode()) forgetRequest();
      serverIds.forEach((id) => state.results.set(id, { success: false, status: "failed" }));
      $("result-state").textContent = "Request rejected";
      $("result-summary").textContent = queuedMode()
        ? "The request was rejected before it could be queued."
        : "The request was rejected before any backup changes.";
      $("result-next-step").textContent = "Resolve the reported problem before submitting another request.";
      $("tracking-message").textContent = "";
      setSupportDetails({ ...state.supportDetails, outcome: "Rejected" });
      showError(safeError(error));
    } else if (queuedMode()) {
      $("result-next-step").textContent = "Submission could not be confirmed. Check the saved Request ID before trying another operation.";
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
    $("lookup-request").hidden = false;
    $("result-details").hidden = false;
    document.querySelector(".column-note").textContent = "Tracked requests";
  }
  const demo = state.config.mode === "stub";
  $("mode").textContent = demo ? "DEMO" : "LIVE";
  $("mode").classList.toggle("live", !demo);
  $("notice").textContent = "Manage backup activity for your servers.";
  if (!state.config.identityConfigured) {
    $("sign-in").textContent = "Sign-in unavailable";
    showError("Sign-in is currently unavailable. Contact your administrator.");
    updateControls();
    return;
  }
  state.msal = new PublicClientApplication({
    auth: { clientId: state.config.clientId, authority: `https://login.microsoftonline.com/${state.config.multiTenant === true ? "organizations" : state.config.tenantId}`, redirectUri: state.config.redirectUri },
    cache: { cacheLocation: "sessionStorage" },
  });
  await state.msal.initialize();
  const redirect = await state.msal.handleRedirectPromise();
  state.account = redirect?.account ?? state.msal.getActiveAccount() ?? state.msal.getAllAccounts()[0] ?? null;
  if (state.account) {
    state.msal.setActiveAccount(state.account);
    $("account-name").textContent = state.account.name || state.account.username;
    $("sign-in").textContent = "Sign out";
    if (state.config.multiTenant === true && !state.config.allowedTenantIds?.includes(state.account.tenantId)) {
      throw new Error("Your organization is not enabled for this application. Sign out and use an approved work account.");
    }
    await loadPermissions();
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

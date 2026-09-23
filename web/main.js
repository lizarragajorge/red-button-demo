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
      <p class="fine">A successful response means Commvault accepted the request. Check Commvault for the current backup state and any re-enable schedule.</p>
      <div class="dialog-actions"><button type="button" id="cancel" class="secondary">Cancel</button><button type="submit" id="confirm-submit" class="danger" disabled>Confirm disable</button></div>
    </form>
  </dialog>
`;

const $ = (id) => document.getElementById(id);
const state = { config: null, msal: null, account: null, servers: [], selected: new Set(), results: new Map(), canDisable: false, busy: false, phase: "", loaded: false, inventoryFailed: false, updatedAt: null };
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
  $("result-detail-text").textContent = JSON.stringify(details, null, 2);
  $("result-details").hidden = false;
}

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
  $("red-button").disabled = state.busy || !state.canDisable || state.selected.size === 0 || state.selected.size > 50;
  $("refresh").disabled = state.busy || !state.account;
  $("infrastructure").disabled = state.busy || !state.account;
  $("server-search").disabled = state.busy || !state.loaded;
  $("select-all").disabled = state.busy || !state.canDisable || !visible.length || (exceedsLimit && !allVisibleSelected);
  $("select-all").checked = allVisibleSelected;
  $("select-all").indeterminate = visibleSelected > 0 && !allVisibleSelected;
  $("selection-status").textContent = `${state.selected.size} of 50 selected${hiddenSelected ? ` / ${hiddenSelected} hidden by search` : ""}`;
  $("selection-limit").hidden = !exceedsLimit || !state.canDisable;
  $("clear-selection").disabled = state.busy || state.selected.size === 0;
  $("sign-in").disabled = state.busy || !state.config?.identityConfigured;
  $("inventory").setAttribute("aria-busy", String(state.phase === "loading"));
  $("red-button").setAttribute("aria-busy", String(state.phase === "submitting"));
  $("refresh").textContent = state.phase === "loading" ? "Loading..." : state.inventoryFailed ? "Retry inventory" : "Refresh";
  $("red-button").querySelector(".button-caption").textContent = state.phase === "submitting" ? "SUBMITTING..." : "REVIEW & CONFIRM";
  let guidance = "Review first. Nothing changes until you confirm.";
  if (!state.config) guidance = "Connecting to the application...";
  else if (!state.config.identityConfigured) guidance = "Unavailable until sign-in is restored.";
  else if (!state.account) guidance = "Sign in with Microsoft to get started.";
  else if (state.phase === "submitting") guidance = "Request in progress. Do not retry or close this page.";
  else if (state.phase === "loading") guidance = "Loading your server inventory...";
  else if (!state.canDisable) guidance = "Read-only access. Contact your administrator to request permission.";
  else if (state.inventoryFailed) guidance = "Inventory could not be loaded. Use Retry inventory.";
  else if (!state.selected.size) guidance = "Select at least one server to enable the red button.";
  $("button-guidance").textContent = guidance;
  for (const checkbox of $("servers").querySelectorAll("input")) {
    checkbox.disabled = state.busy || !state.canDisable || (state.selected.size >= 50 && !checkbox.checked);
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
    $("inventory-status").textContent = `${visible.length} of ${state.servers.length} shown / Updated ${state.updatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }
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
    status.textContent = result ? result.unknown ? "Outcome unknown" : result.success ? "Request accepted" : "Failed / check result" : "No action";
    status.className = result ? result.success ? "success-text" : "failure-text" : "muted";
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
    state.servers = data.servers;
    state.loaded = true;
    state.updatedAt = new Date();
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
    $("schedule-summary").textContent = `Re-enable requested ${minutes} minutes after confirmation (approximately ${deadline.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}, your local time).`;
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
  if (state.busy || !state.canDisable || $("confirmation").value !== "DISABLE BACKUPS" || !$("confirm-form").reportValidity()) return;
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
  try {
    const data = await api("/api/disable", { method: "POST", body: JSON.stringify({ serverIds, confirmation: "DISABLE BACKUPS", options }) });
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
    });
    serverIds.forEach((id) => state.results.set(id, { unknown: true, success: false }));
    showError("We could not confirm all outcomes. Check Commvault before retrying, or share the support details with your administrator.");
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
  }
  updateControls();
}
initialize().catch((error) => { showError(safeError(error)); updateControls(); });

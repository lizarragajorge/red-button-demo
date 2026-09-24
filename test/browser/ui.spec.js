import { test, expect } from "@playwright/test";
import { mockApp, servers } from "./fixtures.js";

test("unconfigured app visibly fails closed", async ({ page }) => {
  await mockApp(page, { configured: false });
  await page.goto("/");
  await expect(page.getByText("DEMO", { exact: true })).toBeVisible();
  await expect(page.locator("#notice")).toHaveText("Simulated environment. No real backups will change.");
  await expect(page.getByRole("alert")).toHaveText("Sign-in is currently unavailable. Contact your administrator.");
  await expect(page.getByRole("button", { name: "Sign-in unavailable", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toHaveAccessibleDescription("Unavailable until sign-in is restored.");
  await expect(page.locator("body")).not.toContainText(/ENTRA_|PUBLIC_ORIGIN|Terraform|setup checklist|app registrations|in-memory|V4 integration|Server-side credentials|Audited operations/i);
  await expect(page.getByRole("link", { name: /Contact support/ })).toBeHidden();
  await expect(page.locator("#setup")).toHaveCount(0);
});

test("unavailable sign-in shows one concise warning and keeps the red button visible on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockApp(page, { configured: false });
  await page.goto("/");
  await expect(page.getByRole("alert")).toHaveCount(1);
  await expect(page.getByRole("alert")).toHaveText("Sign-in is currently unavailable. Contact your administrator.");
  const button = await page.getByRole("button", { name: "Review disable backups request" }).boundingBox();
  expect(button.y + button.height).toBeLessThanOrEqual(1000);
  await expect(page.locator("#setup")).toHaveCount(0);
});

test("selected IDs, typed confirmation, default delay and partial results", async ({ page }) => {
  await mockApp(page);
  let submitted;
  await page.route("**/api/disable", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 207, json: { requestId: "test-request", results: [
      { serverId: 101, success: true }, { serverId: 102, success: false, error: "Commvault returned HTTP 503." },
    ] } });
  });
  await page.goto("/");
  await expect(page.getByText("Demo operator", { exact: true })).toBeVisible();
  await expect(page.getByText("Finance <script>alert(1)</script>", { exact: true })).toBeVisible();
  await expect(page.locator("#servers script")).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Select all visible servers" }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.getByRole("button", { name: "Confirm disable", exact: true })).toBeDisabled();
  await page.getByPlaceholder("DISABLE BACKUPS").fill("disable backups");
  await expect(page.getByRole("button", { name: "Confirm disable", exact: true })).toBeDisabled();
  await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
  const before = Math.floor(Date.now() / 1000);
  await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
  await expect(page.locator("#result-summary")).toContainText("1 of 2 requests accepted");
  expect(submitted.serverIds).toEqual([101, 102]);
  expect(submitted.confirmation).toBe("DISABLE BACKUPS");
  expect(submitted.options.enableAfterADelay).toBeGreaterThanOrEqual(before + 3600);
  expect(submitted.options.enableAfterADelay).toBeLessThanOrEqual(Math.floor(Date.now() / 1000) + 3600);
  await expect(page.locator("#results li").filter({ hasText: "Finance" })).toContainText("Needs review");
  await expect(page.locator("#results")).not.toContainText(/503|102/);
  await expect(page.locator("#result-summary")).not.toContainText("test-request");
  await expect(page.getByRole("heading", { name: "Action results", exact: true })).toBeFocused();
  await expect(page.locator("#result-detail-text")).toBeHidden();
  await page.locator("#result-details summary").click();
  await expect(page.locator("#result-detail-text")).toContainText("503");
  await expect(page.locator("#result-detail-text")).toContainText("test-request");
  await expect(page.locator("#result-detail-text script")).toHaveCount(0);
  await expect(page.locator("#result-state")).toHaveText("Partially accepted");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
});

test("read-only operator cannot select or submit, live state is conspicuous", async ({ page }) => {
  await mockApp(page, { canDisable: false, mode: "live" });
  await page.goto("/");
  await expect(page.getByText("LIVE", { exact: true })).toBeVisible();
  await expect(page.locator("#notice")).toContainText("Actions change real backup settings.");
  await expect(page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
});

test("filter clears selection and cancellation sends no mutation", async ({ page }) => {
  await mockApp(page);
  let mutations = 0;
  await page.route("**/api/disable", (route) => { mutations++; return route.abort(); });
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(mutations).toBe(0);
  await page.getByRole("checkbox", { name: "Infrastructure only" }).check();
  await expect(page.locator("#server-count")).toHaveText("1");
  await expect(page.locator("#selection-count")).toHaveText("0");
});

test("network failure warns about unknown outcomes and never auto-retries", async ({ page }) => {
  await mockApp(page);
  let mutations = 0;
  await page.route("**/api/disable", (route) => { mutations++; return route.abort("failed"); });
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByLabel("Keep disabled until re-enabled in Commvault instead").check();
  await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
  await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
  await expect(page.locator("#result-summary")).toContainText("Some operations may have completed");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator("#servers")).toContainText("Outcome unknown");
  await expect(page.locator("#selection-count")).toHaveText("0");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  expect(mutations).toBe(1);
});

for (const width of [390, 820, 1440]) {
  test(`layout and confirmation fit a ${width}px viewport`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApp(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "The Red Button.", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeVisible();
    const control = page.getByRole("button", { name: "Review disable backups request" });
    const buttonBounds = await control.boundingBox();
    expect(buttonBounds.width).toBeGreaterThanOrEqual(200);
    expect(Math.abs(buttonBounds.width - buttonBounds.height)).toBeLessThan(1);
    await expect(control).toHaveCSS("border-radius", "50%");
    if (width === 1440) {
      const inventoryBounds = await page.locator("#inventory").boundingBox();
      const activityBounds = await page.locator("#activity").boundingBox();
      const controlPanelBounds = await page.locator(".control").boundingBox();
      expect(controlPanelBounds.x).toBeGreaterThan(inventoryBounds.x + inventoryBounds.width);
      expect(Math.abs(activityBounds.x - inventoryBounds.x)).toBeLessThan(1);
      expect(activityBounds.y).toBeGreaterThan(inventoryBounds.y + inventoryBounds.height);
      expect(buttonBounds.y + buttonBounds.height).toBeLessThanOrEqual(900);
    }
    await expect(control).toHaveAccessibleDescription("Select at least one server to enable the red button.");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
    await expect(control).toHaveAccessibleDescription("Review first. Nothing changes until you confirm.");
    await page.screenshot({ path: testInfo.outputPath("operator-view.png"), fullPage: true });
    await page.getByRole("button", { name: "Review disable backups request" }).click();
    const dialog = page.getByRole("dialog", { name: "Disable backups?" });
    await expect(dialog).toBeVisible();
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await expect(page.getByRole("button", { name: "Confirm disable", exact: true })).toBeDisabled();
    await page.screenshot({ path: testInfo.outputPath("confirmation-view.png") });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
  });
}

test("unavailable infrastructure classification is not shown as a workload", async ({ page }) => {
  await mockApp(page);
  await page.route("**/api/servers?*", (route) => route.fulfill({
    json: { totalServers: 1, servers: [{ id: 103, name: "unknown-type", isInfrastructure: null }] },
  }));
  await page.goto("/");
  await expect(page.locator("#servers")).toContainText("Unknown");
  await expect(page.locator("#servers")).not.toContainText("Workload");
});

test("search preserves hidden selections and review includes every selected server", async ({ page }) => {
  await mockApp(page);
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("searchbox", { name: "Find a server" }).fill("finance.demo.invalid");
  await expect(page.locator("#selection-status")).toHaveText("1 of 50 selected / 1 hidden by search");
  await expect(page.locator("#servers tr")).toHaveCount(1);
  await page.getByRole("checkbox", { name: "Select all visible servers" }).check();
  await expect(page.locator("#selection-count")).toHaveText("2");
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.getByRole("heading", { name: "Disable backups?", exact: true })).toBeFocused();
  await expect(page.locator("#confirm-targets li")).toHaveCount(2);
  await expect(page.locator("#confirm-targets")).toContainText("ID 101");
  await expect(page.locator("#confirm-targets")).toContainText("ID 102");
  await expect(page.locator("#confirm-targets script")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeFocused();
  await page.getByRole("button", { name: "Clear selection", exact: true }).click();
  await expect(page.locator("#selection-count")).toHaveText("0");
});

test("search has an actionable empty state and supports numeric IDs", async ({ page }) => {
  await mockApp(page);
  await page.goto("/");
  const search = page.getByRole("searchbox", { name: "Find a server" });
  await expect(search).toBeEnabled();
  await search.fill("does-not-exist");
  await expect(page.locator("#empty")).toContainText("No matching servers");
  await expect(page.getByRole("checkbox", { name: "Select all visible servers" })).toBeDisabled();
  await search.fill("101");
  await expect(page.locator("#servers tr")).toHaveCount(1);
  await expect(page.locator("#servers")).toContainText("Demo CommServe");
});

test("bulk selection never silently truncates and individual selection is capped at 50", async ({ page }) => {
  await mockApp(page);
  const many = Array.from({ length: 51 }, (_, index) => ({
    id: index + 1, name: `server-${index + 1}`, hostName: `host-${index + 1}.invalid`,
  }));
  await page.route("**/api/servers?*", (route) => route.fulfill({ json: { totalServers: many.length, servers: many } }));
  await page.goto("/");
  await expect(page.locator("#servers tr")).toHaveCount(51);
  await expect(page.getByRole("checkbox", { name: "Select all visible servers" })).toBeDisabled();
  await expect(page.locator("#selection-limit")).toBeVisible();
  for (let id = 1; id <= 50; id++) {
    await page.getByRole("checkbox", { name: `Select server-${id}`, exact: true }).check();
  }
  await expect(page.locator("#selection-count")).toHaveText("50");
  await expect(page.getByRole("checkbox", { name: "Select server-51", exact: true })).toBeDisabled();
  await page.getByRole("checkbox", { name: "Select server-1", exact: true }).uncheck();
  await expect(page.getByRole("checkbox", { name: "Select server-51", exact: true })).toBeEnabled();
});

test("inventory failure provides retry and loading feedback without enabling actions", async ({ page }) => {
  await mockApp(page);
  let failed = true;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/servers?*", async (route) => {
    if (failed) return route.fulfill({ status: 502, json: { error: "Inventory service unavailable." } });
    await gate;
    return route.fulfill({ json: { totalServers: servers.length, servers } });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Inventory service unavailable");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toHaveAccessibleDescription("Inventory could not be loaded. Use Retry inventory.");
  failed = false;
  await page.getByRole("button", { name: "Retry inventory", exact: true }).click();
  await expect(page.locator("#inventory")).toHaveAttribute("aria-busy", "true");
  await expect(page.getByRole("button", { name: "Loading...", exact: true })).toBeDisabled();
  release();
  await expect(page.locator("#inventory")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#servers tr")).toHaveCount(2);
  await expect(page.getByRole("alert")).toBeHidden();
});

test("review resets indefinite mode and describes the schedule explicitly", async ({ page }) => {
  await mockApp(page);
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  const red = page.getByRole("button", { name: "Review disable backups request" });
  await red.click();
  await expect(page.locator("#schedule-summary")).toContainText("60 minutes after confirmation");
  await page.getByLabel("Keep disabled until re-enabled in Commvault instead").check();
  await expect(page.locator("#schedule-summary")).toContainText("No automatic re-enable");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await red.click();
  await expect(page.getByLabel("Keep disabled until re-enabled in Commvault instead")).not.toBeChecked();
  await expect(page.getByRole("spinbutton")).toHaveValue("60");
  await expect(page.getByPlaceholder("DISABLE BACKUPS")).toHaveValue("");
});

test("pending submission is visible and blocks repeat actions until results arrive", async ({ page }) => {
  await mockApp(page);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let mutations = 0;
  await page.route("**/api/disable", async (route) => {
    mutations++;
    await gate;
    return route.fulfill({ json: { requestId: "pending-test", results: [{ serverId: 101, success: true }] } });
  });
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  const red = page.getByRole("button", { name: "Review disable backups request" });
  await red.click();
  await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
  await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
  await expect(red).toHaveAttribute("aria-busy", "true");
  await expect(red).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeDisabled();
  await expect(page.locator("#result-state")).toHaveText("In progress");
  release();
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(red).toHaveAttribute("aria-busy", "false");
  expect(mutations).toBe(1);
});

test("signed-out users get a clear next step rather than a setup error", async ({ page }) => {
  await mockApp(page, { signedIn: false });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in with Microsoft" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toHaveAccessibleDescription("Sign in with Microsoft to get started.");
  await expect(page.getByRole("alert")).toBeHidden();
  await expect(page.locator("#setup")).toHaveCount(0);
});

test("keyboard navigation supports skip link, selection, review and safe cancellation", async ({ page }) => {
  await mockApp(page);
  let mutations = 0;
  await page.route("**/api/disable", (route) => { mutations++; return route.abort(); });
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to backup controls" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#workspace")).toBeFocused();
  await expect(page.locator("#servers tr")).toHaveCount(2);
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).focus();
  await page.keyboard.press("Space");
  const red = page.getByRole("button", { name: "Review disable backups request" });
  await red.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Disable backups?", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(red).toBeFocused();
  expect(mutations).toBe(0);
});

test("unknown outcomes replace old success labels instead of implying the latest action succeeded", async ({ page }) => {
  await mockApp(page);
  let calls = 0;
  await page.route("**/api/disable", (route) => {
    calls++;
    return calls === 1
      ? route.fulfill({ json: { requestId: "initial", results: [{ serverId: 101, success: true }] } })
      : route.abort("failed");
  });
  await page.goto("/");
  for (let attempt = 1; attempt <= 2; attempt++) {
    await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
    await page.getByRole("button", { name: "Review disable backups request" }).click();
    await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
    await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
    await expect(page.locator("#result-state")).toHaveText(attempt === 1 ? "Requests accepted" : "Check outcomes");
  }
  await expect(page.locator("#servers")).toContainText("Outcome unknown");
  await expect(page.locator("#servers")).not.toContainText("Request accepted");
  await expect(page.locator("#result-details")).not.toHaveAttribute("open", "");
  await expect(page.locator("#result-detail-text")).not.toContainText("initial");
  await expect(page.locator("#copy-status")).toHaveText("");
});

test("public branding is plain text and support is optional without changing safety", async ({ page }) => {
  const name = 'Client <img src=x onerror="alert(1)">';
  await mockApp(page, { configured: false, displayName: name, supportUrl: "https://support.example.invalid/help" });
  await page.goto("/");
  await expect(page).toHaveTitle(`${name} | Backup control`);
  await expect(page.locator("#brand-name")).toHaveText(name);
  await expect(page.locator("#page-title")).toHaveText(name);
  await expect(page.locator("#footer-name")).toHaveText(name);
  await expect(page.getByRole("link", { name: `${name} home`, exact: true })).toBeVisible();
  await expect(page.locator(".brand img, #page-title img, footer img")).toHaveCount(0);
  const support = page.getByRole("link", { name: /Contact support/ });
  await expect(support).toHaveAttribute("href", "https://support.example.invalid/help");
  await expect(support).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  await expect(page.locator("#mode")).toHaveText("DEMO");
});

test("long custom name fits a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockApp(page, { displayName: "X".repeat(60), supportUrl: "https://support.example.invalid/" });
  await page.goto("/");
  await expect(page.locator("#page-title")).toHaveText("X".repeat(60));
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("unsafe support destination is rejected, not rendered as a link", async ({ page }) => {
  await mockApp(page, { supportUrl: "javascript:alert(1)" });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("support destination is invalid");
  await expect(page.getByRole("link", { name: /Contact support/ })).toBeHidden();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
});

test("support copy includes useful diagnostics but no authentication data", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mockApp(page);
  await page.route("**/api/disable", (route) => route.fulfill({
    status: 502, json: { requestId: "support-502", error: "Upstream service unavailable." },
  }));
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.getByRole("spinbutton")).toHaveAccessibleName("Request automatic re-enable after (minutes)");
  await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
  await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Check outcomes");
  await expect(page.locator("#result-detail-text")).toBeHidden();
  await page.locator("#result-details summary").focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Copy details", exact: true }).click();
  await expect(page.locator("#copy-status")).toHaveText("Details copied.");
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(JSON.parse(copied)).toMatchObject({
    environment: "Demo", requestId: "support-502", httpStatus: 502, outcome: "Unknown",
    targets: [{ serverId: 101, name: "Demo CommServe" }], error: "Upstream service unavailable.",
  });
  expect(copied).not.toMatch(/browser-fixture-not-a-real-token|Authorization|accessToken/);
});

test("clipboard denial provides manual copy guidance", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.clipboard, "writeText", {
      value: async () => { throw new DOMException("Denied", "NotAllowedError"); },
    });
  });
  await mockApp(page);
  await page.route("**/api/disable", (route) => route.fulfill({
    json: { requestId: "accepted-copy", results: [{ serverId: 101, success: true }] },
  }));
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
  await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#result-next-step")).toContainText("verify the backup state");
  await page.locator("#result-details summary").click();
  await page.getByRole("button", { name: "Copy details", exact: true }).click();
  await expect(page.locator("#copy-status")).toContainText("Select and copy the details above manually.");
  await expect(page.locator("#result-detail-text")).toBeVisible();
});

for (const responseType of ["incomplete", "duplicate", "non-json"]) {
  test(`${responseType} response cannot imply complete success and retains support correlation`, async ({ page }) => {
    await mockApp(page);
    let submissions = 0;
    await page.route("**/api/disable", (route) => {
      submissions++;
      return route.fulfill(responseType === "non-json"
        ? { status: 502, headers: { "X-Request-Id": "bad-response" }, contentType: "text/html", body: "Unavailable" }
        : { json: { requestId: "bad-response", results: responseType === "duplicate"
          ? [{ serverId: 101, success: true }, { serverId: 101, success: true }]
          : [{ serverId: 101, success: true }] } });
    });
    await page.goto("/");
    await page.getByRole("checkbox", { name: "Select all visible servers" }).check();
    await page.getByRole("button", { name: "Review disable backups request" }).click();
    await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
    await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
    await expect(page.locator("#result-state")).toHaveText("Check outcomes");
    await expect(page.locator("#servers")).not.toContainText("Request accepted");
    await expect(page.locator("#servers tr").filter({ hasText: "Outcome unknown" })).toHaveCount(2);
    await expect(page.locator("#selection-count")).toHaveText("0");
    await page.locator("#result-details summary").click();
    await expect(page.locator("#result-detail-text")).toContainText("bad-response");
    expect(submissions).toBe(1);
  });
}

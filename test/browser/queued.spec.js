import { test, expect } from "@playwright/test";
import { mockApp, publicConfig } from "./fixtures.js";

const savedId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const storageKey = `red-button:last-request:${publicConfig.tenantId}:${publicConfig.clientId}:fixture-user`;

function record(requestId, status = "queued") {
  const resultStatus = { queued: "pending", running: "running", completed: "accepted", failed: "failed", unknown: "unknown" }[status];
  return {
    requestId, status, mode: "stub", serverIds: [101], options: {},
    submittedAt: "2026-09-23T12:00:00Z", updatedAt: "2026-09-23T12:01:00Z",
    results: [{ serverId: 101, status: resultStatus, success: resultStatus === "accepted" ? true : ["pending", "running"].includes(resultStatus) ? null : false }],
  };
}

async function submit(page) {
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByPlaceholder("DISABLE BACKUPS").fill("DISABLE BACKUPS");
  await page.getByRole("button", { name: "Confirm disable", exact: true }).click();
}

test("queued submission tracks completion without repeating the mutation", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  let submittedId;
  let mutations = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    submittedId = route.request().headers()["idempotency-key"];
    return route.fulfill({ status: 202, json: record(submittedId) });
  });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: record(submittedId, "completed") }));
  await page.goto("/");
  await submit(page);
  await expect(page.locator("#result-state")).toHaveText("Queued");
  expect(submittedId).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.locator("#results")).toContainText("Waiting");
  await expect(page.locator("#results")).not.toContainText("Request accepted");
  await expect(page.locator("#result-next-step")).toContainText("Processing continues on the server");
  await page.clock.fastForward(3100);
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#servers")).toContainText("Request accepted");
  expect(mutations).toBe(1);
});

test("reloading restores the same saved request without resubmitting", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  let id;
  let mutations = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    id = route.request().headers()["idempotency-key"];
    return route.fulfill({ status: 202, json: record(id) });
  });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: record(id, "completed") }));
  await page.goto("/");
  await submit(page);
  await expect(page.locator("#result-state")).toHaveText("Queued");
  await page.reload();
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#request-id")).toHaveValue(id);
  expect(mutations).toBe(1);
});

test("a lost submission response recovers by idempotency key instead of retrying the write", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  let id;
  let mutations = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    id = route.request().headers()["idempotency-key"];
    return route.abort("failed");
  });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: record(id, "completed") }));
  await page.goto("/");
  await submit(page);
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#request-id")).toHaveValue(id);
  await page.locator("#result-details summary").click();
  await expect(page.locator("#result-detail-text")).toContainText(id);
  expect(mutations).toBe(1);
});

test("status failure stops automatic polling and provides an explicit read-only retry", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  let id;
  let checks = 0;
  let fail = true;
  await page.route("**/api/disable", (route) => {
    id = route.request().headers()["idempotency-key"];
    return route.fulfill({ status: 202, json: record(id) });
  });
  await page.route("**/api/requests/*", (route) => {
    checks++;
    return fail ? route.fulfill({ status: 503, json: { error: "Storage unavailable." } })
      : route.fulfill({ json: record(id, "unknown") });
  });
  await page.goto("/");
  await submit(page);
  await page.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Status unavailable");
  await expect(page.locator("#tracking-message")).toContainText("does not cancel");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  await page.clock.fastForward(30000);
  expect(checks).toBe(1);
  fail = false;
  await page.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Check outcomes");
  await expect(page.locator("#results")).toContainText("Outcome unknown");
  await expect(page.locator("#result-next-step")).toContainText("before retrying");
});

test("cached inventory shows source freshness rather than claiming a new refresh", async ({ page }) => {
  await mockApp(page, {
    executionMode: "queued",
    inventory: { updatedAt: "2026-09-01T00:00:00Z", stale: true, refreshError: "Refresh failed" },
  });
  await page.goto("/");
  await expect(page.locator("#inventory-status")).toContainText("Cached as of");
  await expect(page.locator("#inventory-freshness")).toContainText("out of date");
  await page.getByRole("button", { name: "Reload inventory", exact: true }).click();
  await expect(page.locator("#inventory-freshness")).toContainText("out of date");
});

test("saved outcomes remain available even when inventory cache is unavailable", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  await page.route("**/api/servers?*", (route) => route.fulfill({ status: 503, json: { error: "Inventory has not been refreshed yet." } }));
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: record(savedId, "completed") }));
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#results")).toContainText("Server 101");
  await expect(page.getByRole("button", { name: "Retry inventory", exact: true })).toBeEnabled();
});

test("saved request references are scoped to the signed-in account", async ({ page }) => {
  await mockApp(page, { executionMode: "queued", accountId: "other-user" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  let checks = 0;
  await page.route("**/api/requests/*", (route) => { checks++; return route.fulfill({ status: 404, json: { error: "Not found" } }); });
  await page.goto("/");
  await expect(page.locator("#result-summary")).toHaveText("No requests yet.");
  expect(checks).toBe(0);
});

test("stopping tracking is explicit and does not send cancellation or another mutation", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  let mutations = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    return route.fulfill({ status: 202, json: record(route.request().headers()["idempotency-key"]) });
  });
  await page.goto("/");
  await submit(page);
  await page.locator("#stop-tracking").click();
  const dialog = page.getByRole("dialog", { name: "Stop tracking this request?" });
  await expect(dialog).toContainText("does not cancel");
  await dialog.getByRole("button", { name: "Keep tracking", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Queued");
  await page.locator("#stop-tracking").click();
  await dialog.getByRole("button", { name: "Stop tracking", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Tracking stopped");
  await expect(page.locator("#tracking-message")).toContainText("not processing");
  expect(mutations).toBe(1);
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBeNull();
});

test("definitive validation rejection does not invent a queued request or block future submissions", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  let checks = 0;
  await page.route("**/api/disable", (route) => route.fulfill({ status: 400, json: { error: "Re-enable time has expired." } }));
  await page.route("**/api/requests/*", (route) => { checks++; return route.abort(); });
  await page.goto("/");
  await submit(page);
  await expect(page.locator("#result-state")).toHaveText("Request rejected");
  await expect(page.getByRole("alert")).toContainText("Re-enable time has expired");
  expect(checks).toBe(0);
  await expect(page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true })).toBeEnabled();
});

test("malformed terminal status cannot imply successful completion", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: { ...record(savedId), status: "completed" } }));
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Status unavailable");
  await expect(page.locator("#result-summary")).not.toContainText("requests accepted");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
});

test("manual lookup validates IDs and never treats other-owner not-found as success", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  let checks = 0;
  await page.route("**/api/requests/*", (route) => {
    checks++;
    return route.fulfill({ status: 404, json: { error: "Request not found." } });
  });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Find a saved request" }).fill("not-an-id");
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#tracking-message")).toContainText("valid Request ID");
  expect(checks).toBe(0);
  await page.getByRole("textbox", { name: "Find a saved request" }).fill(savedId);
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Status unavailable");
  expect(checks).toBe(1);
});

test("running targets become partial outcomes without moving keyboard focus", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  let checks = 0;
  await page.route("**/api/requests/*", (route) => {
    checks++;
    return route.fulfill({
      json: {
        ...record(savedId), serverIds: [101, 102], status: checks === 1 ? "running" : "partial",
        results: [
          { serverId: 101, status: "accepted", success: true },
          { serverId: 102, status: checks === 1 ? "running" : "failed", success: checks === 1 ? null : false },
        ],
      },
    });
  });
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Processing");
  await expect(page.locator("#result-summary")).toHaveText("1 of 2 servers processed.");
  await page.getByRole("searchbox", { name: "Find a server" }).focus();
  await page.clock.fastForward(3100);
  await expect(page.locator("#result-state")).toHaveText("Partially accepted");
  await expect(page.locator("#result-summary")).toHaveText("1 of 2 requests accepted.");
  await expect(page.getByRole("searchbox", { name: "Find a server" })).toBeFocused();
});

test("storage-denied mobile browsers can save a visible Request ID and track outcomes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => { throw new DOMException("Denied", "SecurityError"); };
  });
  await page.route("**/api/disable", (route) => route.fulfill({
    status: 202, json: record(route.request().headers()["idempotency-key"], "completed"),
  }));
  await page.goto("/");
  await submit(page);
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#tracking-storage-warning")).toContainText("Save the Request ID");
  await expect(page.locator("#request-id")).toHaveValue(/^[0-9a-f-]{36}$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("saved requests retain their original environment label after configuration changes", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: { ...record(savedId, "completed"), mode: "live" } }));
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Requests accepted");
  await expect(page.locator("#tracking-message")).toContainText("Saved Live request. This is not the current environment.");
  await expect(page.locator("#mode")).toHaveText("DEMO");
});

test("stopping tracking ignores an already in-flight status response", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  let checks = 0;
  let release;
  await page.route("**/api/requests/*", async (route) => {
    checks++;
    if (checks > 1) await new Promise((resolve) => { release = resolve; });
    await route.fulfill({ json: record(savedId) });
  });
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Queued");
  await page.getByRole("button", { name: "Check status", exact: true }).click();
  await expect.poll(() => checks).toBe(2);
  await page.locator("#stop-tracking").click();
  await page.getByRole("dialog", { name: "Stop tracking this request?" }).getByRole("button", { name: "Stop tracking", exact: true }).click();
  const response = page.waitForResponse(`**/api/requests/${savedId}`);
  release();
  await response;
  await expect(page.locator("#result-state")).toHaveText("Tracking stopped");
  await expect(page.locator("#check-status")).toBeHidden();
});

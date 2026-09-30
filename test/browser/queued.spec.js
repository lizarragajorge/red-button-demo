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
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
}

test("queued submission tracks completion without repeating the mutation", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  let submittedId;
  let mutations = 0;
  let statusChecks = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    submittedId = route.request().headers()["idempotency-key"];
    return route.fulfill({ status: 202, json: record(submittedId) });
  });
  await page.route("**/api/requests/*", (route) => {
    statusChecks++;
    return route.fulfill({ json: record(submittedId, statusChecks === 1 ? "running" : "completed") });
  });
  await page.goto("/");
  await submit(page);
  await expect(page.locator("#result-state")).toHaveText("Queued");
  expect(submittedId).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.locator("#results")).toContainText("Waiting");
  await expect(page.locator("#results")).not.toContainText("Disable command accepted");
  await expect(page.locator("#result-next-step")).toHaveText("Updates automatically. You can leave this page.");
  await expect(page.locator("#check-status")).toBeHidden();
  await page.clock.fastForward(3100);
  await expect(page.locator("#result-state")).toHaveText("Processing");
  await expect(page.locator("#result-summary")).toHaveText("0 of 1 servers processed.");
  await page.clock.fastForward(3100);
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.locator("#result-summary")).toHaveText("Disable command accepted for 1 server.");
  await expect(page.locator("#result-next-step")).toHaveText("Backup state and re-enable are not monitored.");
  await expect(page.locator("#results")).toContainText("Demo CommServe: Disable command accepted");
  await expect(page.locator("#servers")).toContainText("Disable command accepted");
  await expect(page.locator("#check-status")).toBeHidden();
  await expect(page.locator("#request-tracking")).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Find a saved request" })).toBeHidden();
  await page.clock.fastForward(10000);
  expect(statusChecks).toBe(2);
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
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.locator("#result-summary")).toHaveText("Disable command accepted for 1 server.");
  await expect(page.locator("#result-next-step")).toHaveText("Backup state and re-enable are not monitored.");
  await expect(page.locator("#request-id")).toHaveValue(id);
  expect(mutations).toBe(1);
});

test("large queued selections are tracked and restored without truncation or replay", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  const ids = Array.from({ length: 125 }, (_, index) => index + 1);
  const servers = ids.map((id) => ({ id, name: `server-${id}` }));
  let submitted;
  let id;
  let mutations = 0;
  const largeRecord = (status) => ({
    ...record(id, status), serverIds: ids,
    results: ids.map((serverId) => ({
      serverId, status: status === "queued" ? "pending" : "accepted", success: status === "queued" ? null : true,
    })),
  });
  await page.route("**/api/servers?*", (route) => route.fulfill({
    json: { totalServers: ids.length, servers, inventory: { updatedAt: new Date().toISOString(), stale: false, refreshError: null } },
  }));
  await page.route("**/api/disable", (route) => {
    mutations++;
    submitted = route.request().postDataJSON();
    id = route.request().headers()["idempotency-key"];
    return route.fulfill({ status: 202, json: largeRecord("queued") });
  });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: largeRecord("completed") }));
  await page.goto("/");
  await page.getByRole("button", { name: "Select all (125)", exact: true }).click();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.locator("#confirm-targets li")).toHaveCount(125);
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Queued");
  expect(submitted.serverIds).toEqual(ids);
  await expect(page.locator("#results li")).toHaveCount(125);
  await page.clock.fastForward(3100);
  await expect(page.locator("#result-summary")).toHaveText("Disable command accepted for 125 servers.");
  await page.reload();
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.locator("#results li")).toHaveCount(125);
  await expect(page.getByRole("alert")).toBeHidden();
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
  await expect(page.locator("#result-state")).toHaveText("Request completed");
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
  let mutations = 0;
  let fail = true;
  await page.route("**/api/disable", (route) => {
    mutations++;
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
  await expect(page.getByRole("button", { name: "Retry status", exact: true })).toBeHidden();
  await page.clock.fastForward(3100);
  await expect(page.locator("#result-state")).toHaveText("Status unavailable");
  await expect(page.locator("#result-next-step")).toHaveText("Retry status to check this request, not submit it again.");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  await expect(page.getByRole("button", { name: /^Select all/ })).toBeDisabled();
  await page.clock.fastForward(30000);
  expect(checks).toBe(1);
  fail = false;
  await page.getByRole("button", { name: "Retry status", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Outcome unknown");
  await expect(page.locator("#results")).toContainText("Outcome unknown");
  await expect(page.locator("#result-next-step")).toContainText("before retrying");
  await expect(page.getByRole("button", { name: "Retry status", exact: true })).toBeHidden();
  expect(mutations).toBe(1);
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
  await expect(page.locator("#result-state")).toHaveText("Request completed");
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

test("tracking is automatic with no stop controls and cannot switch away from pending work", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  let mutations = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    return route.fulfill({ status: 202, json: record(route.request().headers()["idempotency-key"]) });
  });
  await page.goto("/");
  await submit(page);
  await expect(page.getByRole("button", { name: /Stop tracking|Keep tracking|Check status/ })).toHaveCount(0);
  await expect(page.locator("#check-status")).toBeHidden();
  const id = await page.evaluate((key) => localStorage.getItem(key), storageKey);
  await page.locator("#result-details summary").click();
  await page.getByRole("textbox", { name: "Find a saved request" }).fill(savedId);
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#lookup-message")).toContainText("Wait for the current request");
  await expect(page.locator("#result-state")).toHaveText("Queued");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  expect(mutations).toBe(1);
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe(id);
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
  await expect(page.locator("#result-summary")).not.toContainText("disable commands accepted");
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
  await expect(page.getByRole("textbox", { name: "Find a saved request" })).toBeHidden();
  await page.locator("#result-details summary").click();
  await page.getByRole("textbox", { name: "Find a saved request" }).fill("not-an-id");
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#lookup-message")).toContainText("valid Request ID");
  expect(checks).toBe(0);
  await page.getByRole("textbox", { name: "Find a saved request" }).fill(savedId);
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#lookup-message")).toContainText("Request not found.");
  await expect(page.locator("#result-state")).toHaveText("No actions yet");
  await expect(page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true })).toBeEnabled();
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBeNull();
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
  await expect(page.locator("#result-state")).toHaveText("Partially completed");
  await expect(page.locator("#result-summary")).toHaveText("1 of 2 disable commands accepted.");
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
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.locator("#tracking-storage-warning")).toContainText("Save the Request ID");
  await expect(page.locator("#request-id")).toHaveValue(/^[0-9a-f-]{36}$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("saved requests retain their original environment label after configuration changes", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: { ...record(savedId, "completed"), mode: "live" } }));
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.locator("#tracking-message")).toContainText("Saved Live request. This is not the current environment.");
  await expect(page.locator("#mode")).toHaveText("DEMO");
});

test("automatic in-flight status checks prevent duplicate submissions and request switching", async ({ page }) => {
  await page.clock.install();
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  let checks = 0;
  let release;
  await page.route("**/api/requests/*", async (route) => {
    checks++;
    if (checks > 1) await new Promise((resolve) => { release = resolve; });
    await route.fulfill({ json: record(savedId, checks > 1 ? "completed" : "queued") });
  });
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Queued");
  await page.clock.fastForward(3100);
  await expect.poll(() => checks).toBe(2);
  await page.locator("#result-details summary").click();
  await expect(page.getByRole("button", { name: "Look up", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  const response = page.waitForResponse(`**/api/requests/${savedId}`);
  release();
  await response;
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.locator("#check-status")).toBeHidden();
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe(savedId);
});

test("support lookup preserves a completed result on error and loads another owned request on success", async ({ page }) => {
  await mockApp(page, { executionMode: "queued" });
  await page.addInitScript(({ key, id }) => localStorage.setItem(key, id), { key: storageKey, id: savedId });
  const nextId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  let fail = true;
  await page.route("**/api/requests/*", (route) => {
    if (route.request().url().endsWith(savedId)) return route.fulfill({ json: record(savedId, "completed") });
    return fail ? route.fulfill({ status: 404, json: { error: "Request not found." } })
      : route.fulfill({ json: record(nextId, "failed") });
  });
  await page.goto("/");
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await page.locator("#result-details summary").click();
  await page.getByRole("textbox", { name: "Find a saved request" }).fill(nextId);
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#lookup-message")).toHaveText("Request not found.");
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe(savedId);
  fail = false;
  await page.getByRole("button", { name: "Look up", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Request failed");
  await expect(page.locator("#lookup-message")).toBeEmpty();
  await expect(page.locator("#check-status")).toBeHidden();
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe(nextId);
});

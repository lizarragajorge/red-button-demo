import { test, expect } from "@playwright/test";
import { mockApp, publicConfig } from "./fixtures.js";

const external = "44444444-4444-4444-8444-444444444444";

test("single-tenant default still uses the configured home authority", async ({ page }) => {
  await mockApp(page);
  await page.goto("/");
  await expect(page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true })).toBeEnabled();
  expect(await page.evaluate(() => globalThis.fixtureMsalAuthority)).toBe(`https://login.microsoftonline.com/${publicConfig.tenantId}`);
});

test("allowed external viewers use organizations authority without operation permission", async ({ page }) => {
  await mockApp(page, { multiTenant: true, accountTenant: external, allowedTenantIds: [publicConfig.tenantId, external], canDisable: false });
  await page.goto("/");
  await expect(page.locator("#servers")).toContainText("Demo CommServe");
  expect(await page.evaluate(() => globalThis.fixtureMsalAuthority)).toBe("https://login.microsoftonline.com/organizations");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  await expect(page.locator("#button-guidance")).toContainText("Read-only access");
});

test("unapproved organizations get sign-out guidance without calling protected APIs", async ({ page }) => {
  await mockApp(page, { multiTenant: true, accountTenant: external });
  let calls = 0;
  await page.route("**/api/me", (route) => { calls++; return route.fulfill({ status: 401, json: { error: "Rejected" } }); });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Your organization is not enabled");
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeEnabled();
  expect(calls).toBe(0);
});

test("the same home account cannot resume a request from a different tenant context", async ({ page }) => {
  const key = `red-button:last-request:${publicConfig.tenantId}:${publicConfig.clientId}:fixture-user`;
  await page.addInitScript((key) => localStorage.setItem(key, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), key);
  await mockApp(page, { executionMode: "queued", multiTenant: true, accountTenant: external, allowedTenantIds: [publicConfig.tenantId, external] });
  let lookups = 0;
  await page.route("**/api/requests/*", (route) => { lookups++; return route.fulfill({ status: 404, json: { error: "Not found" } }); });
  await page.goto("/");
  await expect(page.locator("#servers")).toContainText("Demo CommServe");
  await expect(page.locator("#result-summary")).toHaveText("No requests yet.");
  expect(lookups).toBe(0);
});

test("external tenant requests can be saved and resumed in their own context", async ({ page }) => {
  await mockApp(page, { executionMode: "queued", multiTenant: true, accountTenant: external, allowedTenantIds: [publicConfig.tenantId, external] });
  let id;
  let mutations = 0;
  const record = (status) => ({
    requestId: id, status, mode: "stub", serverIds: [101], options: {},
    submittedAt: "2026-09-23T12:00:00Z", updatedAt: "2026-09-23T12:01:00Z",
    results: [{ serverId: 101, status: status === "queued" ? "pending" : "accepted", success: status === "queued" ? null : true }],
  });
  await page.route("**/api/disable", (route) => {
    mutations++;
    id = route.request().headers()["idempotency-key"];
    return route.fulfill({ status: 202, json: record("queued") });
  });
  await page.route("**/api/requests/*", (route) => route.fulfill({ json: record("completed") }));
  await page.goto("/");
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Queued");
  const key = `red-button:last-request:${publicConfig.tenantId}:${publicConfig.clientId}:fixture-user:${external}`;
  expect(await page.evaluate((key) => localStorage.getItem(key), key)).toBe(id);
  await page.reload();
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  expect(mutations).toBe(1);
});

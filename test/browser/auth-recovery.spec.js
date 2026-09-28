import { test, expect } from "@playwright/test";
import { mockApp, publicConfig } from "./fixtures.js";

test("silent token requests use the dedicated callback instead of reloading the application", async ({ page }) => {
  await mockApp(page);
  await page.goto("/");
  await expect(page.locator("#servers")).toContainText("Demo CommServe");
  const request = await page.evaluate(() => globalThis.fixtureSilentRequest);
  expect(request.redirectUri).toBe(publicConfig.silentRedirectUri);
  expect(request.scopes).toEqual([publicConfig.scope]);
});

test("a silent sign-in timeout is not misreported as read-only access and can be retried", async ({ page }) => {
  await mockApp(page, { tokenError: "monitor_window_timeout" });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("monitor_window_timeout");
  await expect(page.locator("#button-guidance")).toContainText("Sign-in has not been verified");
  await expect(page.locator("#button-guidance")).not.toContainText("Read-only access");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
  await page.evaluate(() => { globalThis.fixtureTokenRecovered = true; });
  await page.getByRole("button", { name: "Retry sign-in", exact: true }).click();
  await expect(page.getByRole("alert")).toBeHidden();
  await expect(page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true })).toBeEnabled();
  await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeEnabled();
});

test("retrying failed sign-in does not grant operation permission to a viewer", async ({ page }) => {
  await mockApp(page, { tokenError: "monitor_window_timeout", canDisable: false });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Retry sign-in", exact: true })).toBeEnabled();
  await page.evaluate(() => { globalThis.fixtureTokenRecovered = true; });
  await page.getByRole("button", { name: "Retry sign-in", exact: true }).click();
  await expect(page.locator("#servers")).toContainText("Demo CommServe");
  await expect(page.locator("#button-guidance")).toContainText("Read-only access");
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
});

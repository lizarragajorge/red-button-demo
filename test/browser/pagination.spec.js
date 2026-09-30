import { test, expect } from "@playwright/test";
import { mockApp } from "./fixtures.js";

async function inventory(page, count = 23, options = {}) {
  await mockApp(page, options);
  const servers = Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    name: `server-${index + 1}`,
    hostName: `host-${index + 1}.invalid`,
    isInfrastructure: index === 0,
  }));
  await page.route("**/api/servers?*", (route) => {
    expect(new URL(route.request().url()).searchParams.get("showOnlyInfrastructureMachines")).toBe("0");
    return route.fulfill({ json: { totalServers: servers.length, servers } });
  });
  await page.goto("/");
  await expect(page.locator("#server-count")).toHaveText(String(count));
}

test("pages contain ten rows, with correct boundaries and a partial last page", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await inventory(page);
  const controlBounds = await page.locator(".control").boundingBox();
  expect(controlBounds.height).toBeLessThan(500);
  await expect(page.locator("#servers tr")).toHaveCount(10);
  await expect(page.locator("#inventory-status")).toHaveText("1-10 of 23");
  await expect(page.locator("#page-status")).toHaveText("Page 1 of 3");
  await expect(page.getByRole("button", { name: "Previous", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("#servers tr")).toHaveCount(10);
  await expect(page.locator("#inventory-status")).toHaveText("11-20 of 23");
  await expect(page.locator("#page-status")).toHaveText("Page 2 of 3");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("#servers tr")).toHaveCount(3);
  await expect(page.locator("#inventory-status")).toHaveText("21-23 of 23");
  await expect(page.locator("#page-status")).toHaveText("Page 3 of 3");
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "Select page (3 servers)", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.locator("#inventory-status")).toHaveText("11-20 of 23");
});

test("Select all selects and submits every server across pages", async ({ page }) => {
  await inventory(page, 63);
  let submitted;
  await page.route("**/api/disable", (route) => {
    submitted = route.request().postDataJSON();
    return route.fulfill({
      json: { requestId: "all-pages", results: submitted.serverIds.map((serverId) => ({ serverId, success: true })) },
    });
  });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  const selectAll = page.getByRole("button", { name: "Select all (63)", exact: true });
  await selectAll.click();
  await expect(page.locator("#selection-status")).toHaveText("63 selected (53 off-page)");
  await expect(selectAll).toHaveAccessibleDescription("63 selected (53 off-page)");
  await expect(selectAll).toBeDisabled();
  await expect(page.locator("#servers input:checked")).toHaveCount(10);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("#servers input:checked")).toHaveCount(10);
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).toBeChecked();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.locator("#confirm-targets li")).toHaveCount(63);
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  expect(submitted.serverIds).toEqual(Array.from({ length: 63 }, (_, index) => index + 1));
  await expect(page.locator("#selection-count")).toHaveText("0");
});

test("oversized submissions are reported as rejected, not unknown mutations", async ({ page }) => {
  await inventory(page, 200);
  let mutations = 0;
  await page.route("**/api/disable", (route) => {
    mutations++;
    return route.fulfill({ status: 413, json: { error: "Request body is too large.", requestId: "too-large" } });
  });
  await page.getByRole("button", { name: "Select all (200)", exact: true }).click();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Request rejected");
  await expect(page.getByRole("alert")).toHaveText("Request body is too large.");
  await expect(page.locator("#result-summary")).toHaveText("The request was rejected before any backup changes.");
  await expect(page.locator("#servers")).not.toContainText("Outcome unknown");
  await expect(page.locator("#result-detail-text")).toContainText('"outcome": "Rejected"');
  expect(mutations).toBe(1);
});

test("Select all applies to search matches across pages and preserves other selections", async ({ page }) => {
  await inventory(page, 35);
  await page.getByRole("checkbox", { name: "Select server-2", exact: true }).check();
  await page.getByRole("searchbox", { name: "Find a server" }).fill("server-1");
  const selectAll = page.getByRole("button", { name: "Select all 11 matches", exact: true });
  await selectAll.click();
  await expect(page.locator("#selection-status")).toHaveText("12 selected (2 off-page)");
  await expect(selectAll).toBeDisabled();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select server-19", exact: true })).toBeChecked();
  await page.getByRole("searchbox", { name: "Find a server" }).fill("");
  await expect(page.getByRole("checkbox", { name: "Select server-2", exact: true })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "Select server-3", exact: true })).not.toBeChecked();
  await page.getByRole("button", { name: "Clear selection", exact: true }).click();
  await expect(page.locator("#selection-count")).toHaveText("0");
  await expect(page.getByRole("button", { name: "Select all (35)", exact: true })).toBeEnabled();
  await page.getByRole("searchbox", { name: "Find a server" }).fill("no-match");
  await expect(page.getByRole("button", { name: "Select all 0 matches", exact: true })).toBeDisabled();
});

for (const count of [51, 200, 1000]) {
  test(`Select all includes ${count} targets without truncation`, async ({ page }) => {
    await inventory(page, count);
    const selectAll = page.getByRole("button", { name: `Select all (${count})`, exact: true });
    await selectAll.click();
    await expect(page.locator("#selection-count")).toHaveText(String(count));
    await expect(page.locator("#selection-limit")).toHaveCount(0);
    await page.getByRole("checkbox", { name: /^Select page/ }).uncheck();
    await expect(page.locator("#selection-count")).toHaveText(String(count - 10));
    await selectAll.click();
    await expect(page.locator("#selection-count")).toHaveText(String(count));
    await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeEnabled();
  });
}

test("Select all adds search matches to existing selections beyond 50", async ({ page }) => {
  await inventory(page, 61);
  for (let index = 0; index < 4; index++) {
    await page.getByRole("checkbox", { name: /^Select page/ }).check();
    await page.getByRole("button", { name: "Next", exact: true }).click();
  }
  await page.getByRole("searchbox", { name: "Find a server" }).fill("server-5");
  await expect(page.getByRole("button", { name: "Select all 11 matches", exact: true })).toBeEnabled();
  await page.getByRole("checkbox", { name: "Select server-50", exact: true }).check();
  await page.getByRole("searchbox", { name: "Find a server" }).fill("server-4");
  await page.getByRole("checkbox", { name: "Select server-41", exact: true }).check();
  await page.getByRole("searchbox", { name: "Find a server" }).fill("server-5");
  await expect(page.locator("#selection-count")).toHaveText("42");
  await page.getByRole("button", { name: "Select all 11 matches", exact: true }).click();
  await expect(page.locator("#selection-count")).toHaveText("51");
  await page.getByRole("searchbox", { name: "Find a server" }).fill("server-41");
  await expect(page.getByRole("checkbox", { name: "Select server-41", exact: true })).toBeChecked();
});

test("pending work locks pagination and timing without losing selected targets", async ({ page }) => {
  await inventory(page);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/disable", async (route) => {
    await gate;
    return route.fulfill({ json: { requestId: "pending-page", results: [{ serverId: 11, success: true }] } });
  });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("checkbox", { name: "Select server-11", exact: true }).check();
  await page.locator("#timing-options summary").click();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Previous", exact: true })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /^Select all/ })).toBeDisabled();
  await expect(page.getByRole("spinbutton")).toBeDisabled();
  await expect(page.locator("#selection-count")).toHaveText("1");
  release();
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
  await expect(page.locator("#selection-count")).toHaveText("0");
  await expect(page.locator("#page-status")).toHaveText("Page 2 of 3");
});

test("failed refresh hides old pagination and cannot leave stale selections actionable", async ({ page }) => {
  await inventory(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("checkbox", { name: /^Select page/ }).check();
  await page.route("**/api/servers?*", (route) => route.fulfill({ status: 503, json: { error: "Inventory unavailable." } }));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Inventory unavailable");
  await expect(page.getByRole("navigation", { name: "Server pages" })).toBeHidden();
  await expect(page.locator("#servers tr")).toHaveCount(0);
  await expect(page.locator("#selection-count")).toHaveText("0");
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /^Select all/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Review disable backups request" })).toBeDisabled();
});

test("page selection retains other pages, shows mixed state, and confirms every selected target", async ({ page }) => {
  await inventory(page);
  let submitted;
  await page.route("**/api/disable", (route) => {
    submitted = route.request().postDataJSON();
    return route.fulfill({
      json: { requestId: "cross-page", results: submitted.serverIds.map((serverId) => ({ serverId, success: true })) },
    });
  });
  const selectPage = page.getByRole("checkbox", { name: /^Select page/ });
  await selectPage.check();
  await expect(page.locator("#selection-status")).toHaveText("10 selected");
  await expect(selectPage).toHaveAccessibleDescription("10 selected");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(selectPage).not.toBeChecked();
  await expect(page.locator("#selection-status")).toHaveText("10 selected (10 off-page)");
  await selectPage.check();
  await expect(page.locator("#selection-count")).toHaveText("20");
  await selectPage.uncheck();
  await expect(page.locator("#selection-count")).toHaveText("10");
  await page.getByRole("checkbox", { name: "Select server-11", exact: true }).check();
  await expect(selectPage).toBeChecked({ indeterminate: true });
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(selectPage).toBeChecked();
  await expect(page.locator("#selection-status")).toHaveText("11 selected (1 off-page)");
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.locator("#confirm-targets li")).toHaveCount(11);
  await expect(page.locator("#confirm-targets")).toContainText("server-11");
  await expect(page.locator("#confirm-server-details li")).toHaveCount(11);
  await expect(page.locator("#confirm-count")).toHaveText("11 servers");
  await page.getByRole("button", { name: "Disable backups", exact: true }).click();
  await expect(page.locator("#result-state")).toHaveText("Request completed");
  expect(submitted.serverIds).toEqual(Array.from({ length: 11 }, (_, index) => index + 1));
  expect(submitted.confirmation).toBe("DISABLE BACKUPS");
  await expect(page.locator("#selection-count")).toHaveText("0");
});

test("search resets pagination without losing selection and clear selection spans every page", async ({ page }) => {
  await inventory(page);
  await page.getByRole("checkbox", { name: "Select server-1", exact: true }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("checkbox", { name: "Select server-11", exact: true }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  const search = page.getByRole("searchbox", { name: "Find a server" });
  await search.fill("server-2");
  await expect(page.locator("#servers tr")).toHaveCount(5);
  await expect(page.locator("#inventory-status")).toHaveText("1-5 of 5");
  await expect(page.getByRole("navigation", { name: "Server pages" })).toBeHidden();
  await expect(page.locator("#selection-status")).toHaveText("2 selected (2 off-page)");
  await page.getByRole("checkbox", { name: /^Select page/ }).check();
  await expect(page.locator("#selection-count")).toHaveText("7");
  await search.fill("no-matching-server");
  await expect(page.locator("#inventory-status")).toHaveText("0-0 of 0");
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).toBeDisabled();
  await expect(page.locator("#selection-count")).toHaveText("7");
  await search.fill("");
  await expect(page.locator("#page-status")).toHaveText("Page 1 of 3");
  await page.getByRole("button", { name: "Clear selection", exact: true }).click();
  await expect(page.locator("#selection-count")).toHaveText("0");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("#servers input:checked")).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).not.toBeChecked();
});

test("page and individual selection both work beyond 50", async ({ page }) => {
  await inventory(page, 61);
  const selectPage = page.getByRole("checkbox", { name: /^Select page/ });
  const next = page.getByRole("button", { name: "Next", exact: true });
  for (let index = 0; index < 5; index++) {
    await selectPage.check();
    await next.click();
  }
  await expect(page.locator("#selection-count")).toHaveText("50");
  await expect(selectPage).toBeEnabled();
  await page.getByRole("checkbox", { name: "Select server-51", exact: true }).check();
  await expect(page.locator("#selection-count")).toHaveText("51");
  await page.getByRole("checkbox", { name: "Select server-52", exact: true }).check();
  await expect(page.locator("#selection-count")).toHaveText("52");
  await page.getByRole("checkbox", { name: "Select server-51", exact: true }).uncheck();
  await expect(page.getByRole("checkbox", { name: "Select server-52", exact: true })).toBeEnabled();
  await selectPage.check();
  await expect(page.locator("#selection-count")).toHaveText("60");
  await selectPage.uncheck();
  await expect(page.locator("#selection-count")).toHaveText("50");
  await page.getByRole("checkbox", { name: "Select server-52", exact: true }).check();
  await next.click();
  await expect(selectPage).toBeEnabled();
  await selectPage.check();
  await expect(page.locator("#selection-count")).toHaveText("52");
  await expect(selectPage).toBeEnabled();
  await selectPage.uncheck();
  await expect(page.locator("#selection-count")).toHaveText("51");
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(selectPage).toBeChecked();
  await selectPage.uncheck();
  await expect(page.locator("#selection-count")).toHaveText("41");
});

test("Refresh resets the page and all selections", async ({ page }) => {
  await inventory(page);
  await page.getByRole("checkbox", { name: /^Select page/ }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.locator("#selection-count")).toHaveText("0");
  await expect(page.locator("#servers tr")).toHaveCount(10);
  await expect(page.locator("#inventory-status")).toHaveText("1-10 of 23");
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).not.toBeChecked();
});

test("read-only users can browse pages without selecting or changing timing", async ({ page }) => {
  await inventory(page, 23, { canDisable: false, mode: "live" });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("#page-status")).toHaveText("Page 2 of 3");
  await expect(page.getByRole("checkbox", { name: /^Select page/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /^Select all/ })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "Select server-11", exact: true })).toBeDisabled();
  await page.locator("#timing-options summary").click();
  await expect(page.getByRole("spinbutton")).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "Until manually re-enabled", exact: true })).toBeDisabled();
});

test("pagination and a full-page confirmation fit a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await inventory(page);
  await page.getByRole("checkbox", { name: /^Select page/ }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator("#selection-status")).toHaveText("10 selected (10 off-page)");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  const dialog = page.getByRole("dialog");
  const bounds = await dialog.boundingBox();
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(844);
  await expect(page.locator("#confirm-targets li")).toHaveCount(10);
  await expect(dialog.locator("input")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Disable backups", exact: true })).toBeInViewport();
});

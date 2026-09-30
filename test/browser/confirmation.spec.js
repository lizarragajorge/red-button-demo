import { test, expect } from "@playwright/test";
import { mockApp } from "./fixtures.js";

for (const minutes of ["", "0", "1441", "1.5"]) {
  test(`invalid timing "${minutes}" blocks confirmation and exposes the timing field`, async ({ page }) => {
    await mockApp(page);
    let mutations = 0;
    await page.route("**/api/disable", (route) => { mutations++; return route.abort(); });
    await page.goto("/");
    await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
    await page.locator("#timing-options summary").click();
    const delay = page.getByRole("spinbutton", { name: "Duration (minutes)", exact: true });
    await delay.fill(minutes);
    await page.locator("#timing-options summary").click();
    await page.getByRole("button", { name: "Review disable backups request" }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(delay).toBeVisible();
    await expect(delay).toBeFocused();
    await expect(page.locator("#timing-label")).toHaveText("Choose 1-1,440 whole minutes");
    expect(mutations).toBe(0);
    await delay.fill("30");
    await page.getByRole("button", { name: "Review disable backups request" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.locator("#dialog-title")).toHaveText("Disable backups for 30 minutes?");
  });
}

for (const minutes of [1, 1440, null]) {
  test(`confirmation submits the reviewed ${minutes ?? "indefinite"} timing once`, async ({ page }) => {
    await mockApp(page, { mode: "live" });
    const submissions = [];
    await page.route("**/api/disable", (route) => {
      submissions.push(route.request().postDataJSON());
      return route.fulfill({ json: { requestId: "timing", results: [{ serverId: 101, success: true }] } });
    });
    await page.goto("/");
    await page.getByRole("checkbox", { name: "Select Demo CommServe", exact: true }).check();
    await page.locator("#timing-options summary").click();
    if (minutes === null) await page.getByRole("checkbox", { name: "Until manually re-enabled", exact: true }).check();
    else await page.getByRole("spinbutton").fill(String(minutes));
    await page.getByRole("button", { name: "Review disable backups request" }).click();
    await expect(page.locator("#confirm-mode")).toHaveText("LIVE");
    await expect(page.locator("#confirm-mode")).toHaveClass("mode live");
    await expect(page.locator("#confirm-count")).toBeHidden();
    await expect(page.locator("#confirm-targets")).toHaveText("Demo CommServe");
    await expect(page.locator("#confirm-server-details")).toBeHidden();
    await expect(page.locator("#dialog-title")).toHaveText(minutes === null
      ? "Disable backups until manually re-enabled?"
      : `Disable backups for ${minutes} ${minutes === 1 ? "minute" : "minutes"}?`);
    expect(submissions).toHaveLength(0);
    const before = Math.floor(Date.now() / 1000);
    await page.getByRole("button", { name: "Disable backups", exact: true }).click();
    await expect(page.locator("#result-state")).toHaveText("Request completed");
    expect(submissions).toHaveLength(1);
    expect(submissions[0]).toMatchObject({ serverIds: [101], confirmation: "DISABLE BACKUPS" });
    if (minutes === null) expect(submissions[0].options).toEqual({});
    else {
      expect(submissions[0].options.enableAfterADelay).toBeGreaterThanOrEqual(before + minutes * 60);
      expect(submissions[0].options.enableAfterADelay).toBeLessThanOrEqual(Math.floor(Date.now() / 1000) + minutes * 60);
    }

    // A closed form cannot replay the confirmed operation.
    await page.locator("#confirm-form").evaluate((form) => form.requestSubmit());
    expect(submissions).toHaveLength(1);
  });
}

test("server details are optional, safe to render, and collapsed for each review", async ({ page }) => {
  await mockApp(page);
  let mutations = 0;
  await page.route("**/api/disable", (route) => { mutations++; return route.abort(); });
  await page.goto("/");
  await expect(page.locator("#timing-label")).toHaveText("Duration: 60 minutes");
  await page.getByRole("button", { name: "Select all (2)", exact: true }).click();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  const dialog = page.getByRole("dialog", { name: "Disable backups for 60 minutes?", exact: true });
  await expect(dialog).toHaveAccessibleDescription("DEMO 2 servers");
  await expect(page.locator("#confirm-count")).toHaveText("2 servers");
  await expect(page.locator("#confirm-targets li")).toHaveText(["Demo CommServe", "Finance <script>alert(1)</script>"]);
  expect(await dialog.innerText()).not.toMatch(/demo\.invalid|ID 10[12]|Request re-enable|Running jobs/);
  await page.locator("#server-details summary").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#confirm-server-details")).toBeVisible();
  await expect(page.locator("#confirm-server-details li")).toHaveText([
    "Demo CommServe / commserve.demo.invalid / ID 101",
    "Finance <script>alert(1)</script> / finance.demo.invalid / ID 102",
  ]);
  await expect(dialog.locator("script")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("checkbox", { name: "Select Finance <script>alert(1)</script>", exact: true }).uncheck();
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  await expect(page.locator("#confirm-count")).toBeHidden();
  await expect(page.locator("#confirm-server-details")).toBeHidden();
  await expect(page.locator("#confirm-server-details li")).toHaveCount(1);
  await expect(dialog).toHaveAccessibleDescription("DEMO 1 server");
  await page.keyboard.press("Escape");
  expect(mutations).toBe(0);
});

test("manual duration and expanded details fit a mobile confirmation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApp(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Select all (2)", exact: true }).click();
  await page.locator("#timing-options summary").click();
  await page.getByRole("checkbox", { name: "Until manually re-enabled", exact: true }).check();
  await expect(page.locator("#timing-label")).toHaveText("Duration: until manually re-enabled");
  await page.getByRole("button", { name: "Review disable backups request" }).click();
  const dialog = page.getByRole("dialog", { name: "Disable backups until manually re-enabled?", exact: true });
  await page.locator("#server-details summary").click();
  await expect(page.getByRole("button", { name: "Disable backups", exact: true })).toBeInViewport();
  await expect(page.locator("#confirm-mode")).toBeInViewport();
  const bounds = await dialog.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(844);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});

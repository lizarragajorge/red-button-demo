import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { once } from "node:events";

let server;
let origin;
let output = "";

test.beforeAll(async () => {
  const listener = createServer();
  listener.listen(0, "127.0.0.1");
  await once(listener, "listening");
  const port = listener.address().port;
  await new Promise((resolve) => listener.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const python = existsSync(".venv/bin/python") ? ".venv/bin/python" : "python";
  server = spawn(python, ["-m", "server"], {
    env: {
      ...process.env, PYTHONDONTWRITEBYTECODE: "1", PORT: String(port),
      APP_ENV: "test", PUBLIC_ORIGIN: `http://localhost:${port}`,
      ENTRA_TENANT_ID: "", ENTRA_API_CLIENT_ID: "", ENTRA_SPA_CLIENT_ID: "",
      ENTRA_MULTI_TENANT: "false", ENTRA_ALLOWED_TENANT_IDS: "",
      EXECUTION_MODE: "sync", COMMVAULT_MODE: "stub", ENABLE_LIVE_OPERATIONS: "false",
      STORAGE_ACCOUNT_NAME: "", AZURE_STORAGE_CONNECTION_STRING: "",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", (data) => { output = (output + data).slice(-4000); });
  server.stderr.on("data", (data) => { output = (output + data).slice(-4000); });
  await expect.poll(async () => {
    if (server.exitCode !== null) throw new Error(`Callback test server exited: ${output}`);
    try {
      return (await fetch(`${origin}/api/health`)).status;
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
      return 0;
    }
  }, { timeout: 15000, message: "The isolated callback test server must become ready" }).toBe(200);
});

test.afterAll(async () => {
  if (server && server.exitCode === null) {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
  }
});

test("real browser reproduces the old CSP block and accepts only the dedicated same-origin callback after the fix", async ({ page }) => {
  const violations = [];
  page.on("console", (message) => {
    if (message.type() === "error") violations.push(message.text());
  });
  await page.route(`${origin}/`, async (route) => {
    const response = await route.fetch();
    const headers = response.headers();
    headers["content-security-policy"] = headers["content-security-policy"].replace("frame-src 'self'", "frame-src");
    await route.fulfill({ response, headers });
  });
  const addFrame = () => page.evaluate(() => {
    const iframe = document.createElement("iframe");
    iframe.id = "silent-callback-test";
    iframe.src = "/auth/silent#code=synthetic-code&state=synthetic-state";
    document.body.append(iframe);
  });
  await page.goto(`${origin}/`);
  await addFrame();
  await expect.poll(() => violations.some((message) => message.includes("frame-src"))).toBe(true);
  await page.unroute(`${origin}/`);
  violations.length = 0;
  await page.reload();
  await addFrame();
  await expect.poll(() => page.locator("#silent-callback-test").evaluate((iframe) => iframe.contentDocument?.title))
    .toBe("Microsoft sign-in callback");
  expect(await page.locator("#silent-callback-test").evaluate((iframe) => iframe.contentWindow.location.hash))
    .toBe("#code=synthetic-code&state=synthetic-state");
  expect(violations.some((message) => message.includes("Content Security Policy"))).toBe(false);
  const dashboard = await page.request.get(`${origin}/`);
  expect(dashboard.headers()["x-frame-options"]).toBe("DENY");
  expect(dashboard.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
});

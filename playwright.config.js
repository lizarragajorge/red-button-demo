import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./test/browser",
  use: {
    baseURL: "http://localhost:5173",
    browserName: "chromium",
    ...(process.env.PLAYWRIGHT_CHROME_PATH ? {
      launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH },
    } : {}),
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});

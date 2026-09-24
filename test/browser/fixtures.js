export const publicConfig = {
  mode: "stub", executionMode: "sync", identityConfigured: true, liveOperationsEnabled: false,
  displayName: "Red Button", supportUrl: "",
  tenantId: "11111111-1111-4111-8111-111111111111",
  clientId: "33333333-3333-4333-8333-333333333333",
  scope: "api://22222222-2222-4222-8222-222222222222/access_as_user",
  redirectUri: "http://localhost:5173/",
};

export const servers = [
  { id: 101, name: "commserve", displayName: "Demo CommServe", hostName: "commserve.demo.invalid", isInfrastructure: true },
  { id: 102, name: "finance", displayName: "Finance <script>alert(1)</script>", hostName: "finance.demo.invalid", isInfrastructure: false },
];

export async function mockApp(page, {
  configured = true, canDisable = true, mode = "stub", signedIn = true,
  displayName = "Red Button", supportUrl = "", executionMode = "sync", accountId = "fixture-user",
  inventory = { updatedAt: new Date().toISOString(), stale: false, refreshError: null },
} = {}) {
  const account = signedIn ? { name: "Demo operator", username: "operator@example.invalid", homeAccountId: accountId } : null;
  // Replace MSAL only at Vite's test boundary; production has no auth bypass.
  await page.route("**/node_modules/.vite/deps/@azure_msal-browser.js*", (route) => route.fulfill({
    contentType: "application/javascript",
    body: `
      export class InteractionRequiredAuthError extends Error {}
      export class PublicClientApplication {
        async initialize() {}
        async handleRedirectPromise() { return null; }
        getActiveAccount() { return ${JSON.stringify(account)}; }
        getAllAccounts() { return []; }
        setActiveAccount() {}
        async acquireTokenSilent() { return { accessToken: "browser-fixture-not-a-real-token" }; }
      }
    `,
  }));
  await page.route("**/api/config", (route) => route.fulfill({
    json: { ...publicConfig, mode, identityConfigured: configured, displayName, supportUrl, executionMode },
  }));
  await page.route("**/api/me", (route) => route.fulfill({ json: { canDisable } }));
  await page.route("**/api/servers?*", (route) => {
    const infrastructure = new URL(route.request().url()).searchParams.get("showOnlyInfrastructureMachines") === "1";
    const filtered = infrastructure ? servers.slice(0, 1) : servers;
    return route.fulfill({
      json: { totalServers: filtered.length, servers: filtered, ...(executionMode === "queued" ? { inventory } : {}) },
    });
  });
}

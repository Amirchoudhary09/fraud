// End-to-end tests: starts the real backend (mock mode, throwaway data dir) and the Next.js app,
// then drives Chromium through the main flows.  Run: npx playwright install chromium && npm run test:e2e
import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const API_PORT = 8799;
const WEB_PORT = 3799;
const IDP_PORT = 3899;
const python = process.env.E2E_PYTHON
  ?? (process.platform === "win32" ? "..\\backend\\.venv\\Scripts\\python.exe" : "../backend/.venv/bin/python");
const dataDir = process.env.E2E_DATA_DIR ?? mkdtempSync(join(tmpdir(), "ie-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one shared backend: the first test creates the super admin
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `node e2e/fake-idp.mjs`,
      url: `http://127.0.0.1:${IDP_PORT}/health`,
      env: { IDP_PORT: String(IDP_PORT) },
      reuseExistingServer: false,
    },
    {
      command: `${python} -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: {
        MOCK_MODE: "1", DATA_DIR: dataDir, JWT_SECRET: "e2e-secret-0123456789-0123456789-0123456789",
        OIDC_ISSUER: `http://127.0.0.1:${IDP_PORT}`, OIDC_CLIENT_ID: "e2e-client", OIDC_CLIENT_SECRET: "e2e-secret",
        OIDC_REDIRECT_URI: `http://127.0.0.1:${WEB_PORT}/bff/oidc/callback`, OIDC_PROVIDER_NAME: "Corp SSO",
        OIDC_ALLOWED_DOMAINS: "corp.test", OIDC_REQUIRE_MFA: "1",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx next dev --port ${WEB_PORT} --hostname 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/login`,
      env: { BACKEND_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});

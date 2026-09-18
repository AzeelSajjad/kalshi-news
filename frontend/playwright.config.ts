// frontend/playwright.config.ts
import { defineConfig } from "@playwright/test";

const BACKEND_URL = "http://127.0.0.1:9999";
const APP_URL = "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: APP_URL },
  webServer: [
    {
      // A deterministic stand-in for the real backend. The feed page fetches
      // it server-side, so page.route() in the test can't intercept those
      // requests -- this has to be a real process the Next server can reach.
      command: "node e2e/stub-backend.mjs",
      url: `${BACKEND_URL}/api/feed`,
      reuseExistingServer: false,
      env: { PORT: "9999" },
    },
    {
      command: "npm run start",
      url: APP_URL,
      reuseExistingServer: false,
      env: { BACKEND_API_URL: BACKEND_URL },
    },
  ],
});

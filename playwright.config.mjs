import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8081";

export default defineConfig({
  forbidOnly: Boolean(process.env.CI),
  fullyParallel: false,
  reporter: "line",
  testDir: "tests/e2e",
  timeout: 30_000,
  use: {
    baseURL,
    screenshot: "only-on-failure",
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    ...(process.env.PLAYWRIGHT_BASE_URL
      ? []
      : [
          {
            command: "uv run python -m scripts.serve_showcase",
            reuseExistingServer: !process.env.CI,
            timeout: 30_000,
            url: `${baseURL}/health/live`,
          },
        ]),
    // The offline demo that `make demo` opens, on its own port.
    {
      command: "uv run python -m agentic_context_service.demo --no-browser --port 8091",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      url: "http://127.0.0.1:8091/health/live",
    },
  ],
});

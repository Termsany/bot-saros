import { defineConfig, devices } from "@playwright/test"

// The site in a real browser (development-plan 3.3). CI runs the production build (`npm run build` first);
// locally the dev server. The tests never reach the internet: e2e/fixtures.ts answers or blocks every outside request.
const PORT = 3100
// A Supabase project and an API that don't exist: the tests answer both (e2e/fixtures.ts), so a signed-in admin can be
// faked offline. The same values are set for the CI build (.github/workflows/ci.yml, job e2e): NEXT_PUBLIC_* are
// built into the pages.
export const E2E_ENV = {
  NEXT_PUBLIC_SUPABASE_URL: "https://e2e-project.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "e2e-anon-key-not-a-secret",
  NEXT_PUBLIC_API_URL: "http://localhost:8799",
}

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${PORT}`, locale: "ar-EG", timezoneId: "Africa/Cairo", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: process.env.CI ? `npm run start -- -p ${PORT}` : `npm run dev -- -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: E2E_ENV,
  },
})

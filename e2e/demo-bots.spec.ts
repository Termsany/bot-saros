import { adminTest as test, expect, type ApiCall } from "./fixtures"

// "My Binance Demo bots" (/settings/live): a user's own Demo keys, consent and bots, in English and Arabic.
// A signed-in user against a fake API — nothing reaches the real one, and no key is typed.

const api = async (c: ApiCall) => {
  if (c.path === "/api/user/me") return { admin: false, email: "user@example.com" }
  if (c.path === "/api/user/keys/status") return { binance: { configured: true, paper: true } }
  if (c.path === "/api/user/live/status") return { enabled: true, exchange: "binance", environment: "demo", leverage: 2, risk_per_trade_pct: 0.25, max_aggregate_risk_pct: 1 }
  if (c.path === "/api/user/bots") return {
    rules: { max_strategies: 2, strategies: ["trend_daily", "momentum_ls"] },
    desired: { enabled: true, strategies: ["momentum_ls"], capital_usdt: 1000, capital_margin_override_usdt: 20 },
    provision: { state: "waiting_approval" },
    bots: { momentum_ls: { running: false, positions: [{ symbol: "AGT/USDT", side: "short", entry: 0.052, pnl: 1.5 }] } },
  }
  return undefined
}

test("the Demo bots page in English after the English choice, Arabic after the switch", async ({ page, api: a }) => {
  a.handler = api
  await page.context().addCookies([{ name: "raqm-lang", value: "en", url: "http://localhost:3100" }])
  await page.goto("/settings/live")
  const html = page.locator("html")
  await expect(html).toHaveAttribute("lang", "en")
  await expect(html).toHaveAttribute("dir", "ltr")
  await expect(page.getByRole("heading", { name: "My Binance Demo bots" })).toBeVisible()
  await expect(page.getByText("1 · Exchange keys")).toBeVisible()
  await expect(page.getByText("Waiting for approval").first()).toBeVisible()            // the provisioner's answer
  await expect(page.getByRole("button", { name: "✓ Momentum L/S" })).toBeVisible()       // strategy names in English
  await expect(page.getByText("AGT/USDT")).toBeVisible()
  await expect(page.getByRole("button", { name: "Close", exact: true })).toBeVisible()
  await expect(page.getByText("Saved · Paper")).toBeVisible()
  await page.getByTestId("app-lang-switch").filter({ visible: true }).first().click()
  await expect(html).toHaveAttribute("lang", "ar")
  await expect(page.getByRole("heading", { name: "بوتاتي على Binance (Demo)" })).toBeVisible()
  await expect(page.getByText("مستنية الموافقة").first()).toBeVisible()
  await expect(page.getByRole("button", { name: "✓ مومنتم لونج/شورت" })).toBeVisible()
})

import { adminTest as test, expect, type ApiCall } from "./fixtures"
import { CONSENT_TEXT } from "../lib/liveConsent"

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
  await expect(page).toHaveTitle("My Binance Demo bots — RAQM")
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

test("real money: the user types an amount and a margin, sees the risk, and the consent carries those numbers", async ({ page, api: a }) => {
  // owner, 2026-11-05 (docs/users-real-money-plan.md): each user's own capital and margin, the level shown and accepted
  a.handler = async (c: ApiCall) => {
    if (c.path === "/api/user/bots/risk") {
      const q = new URLSearchParams(c.query), cap = Number(q.get("capital")), m = Number(q.get("margin")), one = m * 0.8
      return { one_stop_usdt: one, per_trade_pct: +(one / cap * 100).toFixed(2), legs: 10, worst_usdt: one * 10,
               aggregate_pct: +(one * 10 / cap * 100).toFixed(2), level: "medium", ok: true, why: null }
    }
    if (c.path === "/api/user/live/status") return { enabled: false }
    if (c.path === "/api/user/live/enable") return { ok: true }
    return api(c)
  }
  await page.goto("/settings/live")
  await page.getByRole("tab", { name: "فلوس حقيقية" }).click()
  await expect(page.getByText("2 · المبلغ والمارجن")).toBeVisible()
  await page.getByLabel(/راس المال/).first().fill("1000")
  await page.getByLabel("المارجن لكل صفقة ($)").first().fill("20")
  const risk = page.getByTestId("live-risk")
  await expect(risk).toContainText("−$16")                                       // one stop: 20 × 2 × 40%
  await expect(risk).toContainText("−$160")                                      // the worst week: all 10 legs at their stops
  await page.getByPlaceholder("اكتب نص الموافقة بالكامل هنا").fill(CONSENT_TEXT)
  await expect(page.getByText(/بوافق على خطورة متوسطة: أسوأ أسبوع ممكن يخسّرني \$160/)).toBeVisible()
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "وافق على الفلوس الحقيقية" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/user/live/enable").length).toBe(1)
  const sent = a.calls.find(c => c.path === "/api/user/live/enable")!.body
  expect([sent.environment, sent.capital_usdt, sent.margin_usdt]).toEqual(["live", 1000, 20])
  await expect(page.getByText("4 · البوت بتاعك (فلوس حقيقية)")).toBeVisible()
})

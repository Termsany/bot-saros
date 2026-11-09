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
  await page.getByRole("checkbox", { name: /بوافق على/ }).check()
  await page.getByRole("button", { name: "وافق على الفلوس الحقيقية" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/user/live/enable").length).toBe(1)
  const sent = a.calls.find(c => c.path === "/api/user/live/enable")!.body
  expect([sent.environment, sent.capital_usdt, sent.margin_usdt]).toEqual(["live", 1000, 20])
  await expect(page.getByText("4 · البوت بتاعك (فلوس حقيقية)")).toBeVisible()
})

test("real money: the reserve decides whether the whole basket fits, and it goes with the bot", async ({ page, api: a }) => {
  // owner, 2026-11-07: $300 at $24 needs a 20% reserve (300 × 80% ÷ 24 = 10); at the default 40% only 7 fit
  a.handler = async (c: ApiCall) => {
    if (c.path === "/api/user/bots/risk") {
      const q = new URLSearchParams(c.query), cap = Number(q.get("capital")), m = Number(q.get("margin")), res = Number(q.get("reserve"))
      const one = m * 0.8, maxOpen = Math.floor(cap * (1 - res / 100) / m + 1e-9), maxMargin = Math.floor(cap * (1 - res / 100) / 10 * 100) / 100
      const fits = maxOpen >= 10
      return { one_stop_usdt: one, per_trade_pct: +(one / cap * 100).toFixed(2), legs: 10, worst_usdt: one * 10,
               aggregate_pct: +(one * 10 / cap * 100).toFixed(2), level: "very_high", reserve_pct: res, max_open: maxOpen, fits,
               max_margin: maxMargin, ok: fits, why: fits ? null : `the basket of 10 doesn't fit: with a ${res}% reserve the margin can be at most $${maxMargin}` }
    }
    if (c.path === "/api/user/live/status") return { enabled: true, environment: "live", capital_usdt: 300, margin_usdt: 24 }
    if (c.path === "/api/user/bots" && c.method === "POST") return { ok: true }
    return api(c)
  }
  await page.goto("/settings/live")
  await expect(page.getByLabel(/راس المال/).first()).toHaveValue("300")
  await expect(page.getByText(/at most \$18/).first()).toBeVisible()              // 40%: refused before anything is saved
  await page.getByTestId("live-reserve").fill("20")
  await expect(page.getByTestId("live-fits")).toHaveText("بيدخل 10 صفقة من 10 في السلة")
  await expect(page.getByTestId("live-risk")).toContainText("−$192")              // all 10 stops at $24
  page.once("dialog", d => { expect(d.message()).toContain("احتياطي 20%"); d.accept() })
  await page.getByRole("button", { name: "شغّل momentum بفلوس حقيقية" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/user/bots" && c.method === "POST").length).toBe(1)
  const sent = a.calls.find(c => c.path === "/api/user/bots" && c.method === "POST")!.body
  expect([sent.env, sent.capital_usdt, sent.capital_margin_override_usdt, sent.capital_reserve_pct]).toEqual(["live", 300, 24, 20])
})

test("real money: momentum, RSI-2 + the BTC filter or both — the risk, the consent and the bot carry the choice", async ({ page, api: a }) => {
  // owner, 2026-11-07: RSI-2 with the BTC filter next to momentum for real money (research §28)
  let status: any = { enabled: false }
  a.handler = async (c: ApiCall) => {
    if (c.path === "/api/user/bots/risk") {
      const q = new URLSearchParams(c.query), cap = Number(q.get("capital")), m = Number(q.get("margin"))
      const legs = 10 * (q.get("strategies") || "momentum_ls").split(",").length, one = m * 0.8
      return { one_stop_usdt: one, per_trade_pct: +(one / cap * 100).toFixed(2), legs, worst_usdt: one * legs,
               aggregate_pct: +(one * legs / cap * 100).toFixed(2), level: "high", reserve_pct: 40, max_open: legs, fits: true, max_margin: 60, ok: true, why: null }
    }
    if (c.path === "/api/user/live/status") return status
    if (c.path === "/api/user/live/enable") { status = { enabled: true, environment: "live", capital_usdt: 2000, margin_usdt: 20, strategies: c.body.strategies }; return { ok: true } }
    if (c.path === "/api/user/bots" && c.method === "POST") return { ok: true }
    return api(c)
  }
  await page.goto("/settings/live")
  await page.getByRole("tab", { name: "فلوس حقيقية" }).click()
  const strats = page.getByTestId("live-strategies")
  await expect(strats.getByRole("checkbox", { name: /Momentum/ })).toHaveAttribute("aria-checked", "true")
  await page.getByLabel(/راس المال/).first().fill("2000")
  await page.getByLabel("المارجن لكل صفقة ($)").first().fill("20")
  await expect(page.getByTestId("live-risk")).toContainText("−$160")                // momentum alone: 10 stops
  await strats.getByRole("checkbox", { name: /RSI-2 \+ فلتر BTC/ }).click()
  await expect(page.getByTestId("live-risk")).toContainText("−$320")                // both: 20 stops
  expect(a.calls.filter(c => c.path === "/api/user/bots/risk").at(-1)!.query).toContain("strategies=momentum_ls%2Crsi2_pullback")
  await strats.getByRole("checkbox", { name: /Momentum/ }).click()                  // RSI-2 alone
  await expect(page.getByTestId("live-risk")).toContainText("−$160")
  await strats.getByRole("checkbox", { name: /RSI-2/ }).click()                     // the last one stays: at least one
  await expect(strats.getByRole("checkbox", { name: /RSI-2/ })).toHaveAttribute("aria-checked", "true")
  await strats.getByRole("checkbox", { name: /Momentum/ }).click()
  await page.getByPlaceholder("اكتب نص الموافقة بالكامل هنا").fill(CONSENT_TEXT)
  await page.getByRole("checkbox", { name: /بوافق على/ }).check()
  await page.getByRole("button", { name: "وافق على الفلوس الحقيقية" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/user/live/enable").length).toBe(1)
  expect(a.calls.find(c => c.path === "/api/user/live/enable")!.body.strategies).toEqual(["momentum_ls", "rsi2_pullback"])
  page.once("dialog", d => { expect(d.message()).toContain("momentum + RSI-2"); d.accept() })
  await page.getByRole("button", { name: "شغّل momentum + RSI-2 بفلوس حقيقية" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/user/bots" && c.method === "POST").length).toBe(1)
  expect(a.calls.find(c => c.path === "/api/user/bots" && c.method === "POST")!.body.strategies).toEqual(["momentum_ls", "rsi2_pullback"])
})

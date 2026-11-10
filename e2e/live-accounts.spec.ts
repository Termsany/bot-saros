import { adminTest as test, expect, type ApiCall } from "./fixtures"

// The dashboard per real account (docs/trend-daily-live-plan.md §2): a strategy on its own Binance sub-account has its
// own capital, limits, yes/no and kill switch. A signed-in admin against a fake API — nothing reaches the real one.

const capital = (cap: number) => ({ plan: { max_open: 11, margin: 26 }, capital_usdt: cap, capital_reserve_pct: 40, capital_margin_pct: 1,
  capital_min_margin_usdt: 5, capital_margin_override_usdt: 26, equity_last: cap, risk_per_trade_pct: 4.5, max_aggregate_risk_pct: 45 })
const ACCOUNTS = [{ name: "", strategies: ["momentum_ls"] }, { name: "trend", strategies: ["trend_daily"] }]

function api(tripped: Record<string, boolean> = {}){
  return async (c: ApiCall) => {
    if (c.path === "/api/user/me") return { admin: true, email: "admin@example.com" }
    if (c.path === "/api/live/status") return { running: true, strategies: {} }
    if (c.path === "/api/live/strategies" && c.method === "GET") {
      const q = new URLSearchParams(c.query), acct = q.get("acct") || ""
      if (q.get("env") === "demo") return { env: "demo", acct: "", accounts: [], enabled: true, capital: capital(5000), strategies: [] }
      const ids = acct ? ["trend_daily"] : ["momentum_ls"]
      return { env: "live", acct, accounts: ACCOUNTS, enabled: true, capital: capital(acct ? 1000 : 500), account: acct || "main", record: null,
               kill_switch: { tripped: !!tripped[acct], reason: tripped[acct] ? "portfolio drawdown 51.42% >= limit 45.0%" : null },
               strategies: ids.map(id => ({ id, on: false, running: false, env: "live", positions: 0, entry_block: "", review: [] })) }
    }
    if (c.path === "/api/live/strategies" && c.method === "POST") return { ok: true, strategies: c.body?.strategies ?? [] }
    if (c.path === "/api/live/capital") return { ok: true, plan: null, limits_check: null }
    if (c.path === "/api/admin/risk/kill-switch") return { ok: true, acct: c.body?.acct, state: { tripped: false } }
    return undefined
  }
}

test("the account picker shows each Binance account with its strategies, and each one loads its own", async ({ page, api: a }) => {
  a.handler = api()
  await page.goto("/admin?tab=real")
  const picker = page.getByTestId("account-picker")
  await expect(picker).toBeVisible()
  await expect(page.getByRole("switch", { name: "مومنتم لونج/شورت تشتغل" })).toBeVisible()
  await picker.getByRole("button", { name: /trend/ }).click()
  await expect(page.getByText("بتغيّر الحساب الحقيقي 'trend' — فلوس حقيقية")).toBeVisible()
  await expect(page.getByRole("switch", { name: "ترند يومي تشتغل" })).toBeVisible()
  await expect(page.getByRole("switch", { name: "مومنتم لونج/شورت تشتغل" })).toHaveCount(0)
  await expect.poll(() => a.calls.some(c => c.path === "/api/live/strategies" && new URLSearchParams(c.query).get("acct") === "trend")).toBe(true)
})

test("a save on a sub-account goes to that account under its own name", async ({ page, api: a }) => {
  a.handler = api()
  await page.goto("/admin?tab=real")
  await page.getByTestId("account-picker").getByRole("button", { name: /trend/ }).click()
  await page.getByRole("switch", { name: "ترند يومي تشتغل" }).click()
  page.once("dialog", d => { expect(d.message()).toContain("الحساب الحقيقي 'trend'"); d.accept() })
  await page.getByRole("button", { name: "احفظ التغييرات" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/live/strategies" && c.method === "POST").length).toBe(1)
  const body = a.calls.find(c => c.path === "/api/live/strategies" && c.method === "POST")!.body
  expect([body.acct, body.account, body.strategies]).toEqual(["trend", "trend", ["trend_daily"]])
})

test("the capital save names the sub-account and sends it", async ({ page, api: a }) => {
  a.handler = api()
  await page.goto("/admin?tab=real")
  await page.getByTestId("account-picker").getByRole("button", { name: /trend/ }).click()
  await expect(page.getByText("راس المال (حقيقي · trend)")).toBeVisible()
  await page.getByLabel("راس المال (USDT)").fill("1200")
  page.once("dialog", d => { expect(d.message()).toContain("الحساب الحقيقي 'trend'"); d.accept() })
  await page.getByRole("button", { name: "احفظ راس المال" }).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/live/capital").length).toBe(1)
  expect(a.calls.find(c => c.path === "/api/live/capital")!.body.acct).toBe("trend")
})

test("each account's kill switch is its own: a tripped one shows its reason and resets only that account", async ({ page, api: a }) => {
  a.handler = api({ trend: true })
  await page.goto("/admin?tab=real")
  await expect(page.getByText("قفل الطوارئ (الأساسي)")).toBeVisible()
  await expect(page.getByTestId("kill-switch")).toHaveText("شغّل قفل الطوارئ")
  await page.getByTestId("account-picker").getByRole("button", { name: /trend/ }).click()
  await expect(page.getByText("portfolio drawdown 51.42% >= limit 45.0%")).toBeVisible()
  page.once("dialog", d => { expect(d.message()).toContain("فك قفل الطوارئ؟"); d.accept() })
  await page.getByTestId("kill-switch").click()
  await expect.poll(() => a.calls.filter(c => c.path === "/api/admin/risk/kill-switch").length).toBe(1)
  const body = a.calls.find(c => c.path === "/api/admin/risk/kill-switch")!.body
  expect([body.action, body.acct]).toEqual(["reset", "trend"])
})

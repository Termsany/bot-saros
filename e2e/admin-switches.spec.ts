import { adminTest as test, expect, type ApiCall } from "./fixtures"

// The admin's strategy switches on the real-money and Demo accounts (roadmap A6, development-plan 3.3): the page
// that turns real-money strategies on and off. A signed-in admin against a fake API — nothing reaches the real one.

const IDS = ["trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend"]
const capital = { plan: { max_open: 20, margin: 26 }, capital_usdt: 500, capital_reserve_pct: 40, capital_margin_pct: 1, capital_min_margin_usdt: 5,
  capital_margin_override_usdt: 26, equity_last: 500, risk_per_trade_pct: 4.5, max_aggregate_risk_pct: 45 }
const strategies = (env: "live" | "demo", on: string[], account = "main") => ({
  env, enabled: true, capital, account: env === "live" ? account : null, record: null,
  strategies: IDS.map(id => ({ id, on: on.includes(id), running: on.includes(id), env, positions: 0, entry_block: "", review: [] })),
})
const DEMO_ON = IDS.filter(id => id !== "momentum_ls")

function api(opts: { liveOn?: string[], account?: string, liveDelayMs?: number } = {}){
  return async (c: ApiCall) => {
    if (c.path === "/api/user/me") return { admin: true, email: "admin@example.com" }
    if (c.path === "/api/live/status") return { running: true, strategies: {} }
    if (c.path === "/api/live/strategies" && c.method === "GET") {
      const env = new URLSearchParams(c.query).get("env") === "demo" ? "demo" : "live"
      if (env === "live" && opts.liveDelayMs) await new Promise(r => setTimeout(r, opts.liveDelayMs))
      return env === "demo" ? strategies("demo", DEMO_ON) : strategies("live", opts.liveOn ?? ["momentum_ls"], opts.account ?? "main")
    }
    if (c.path === "/api/live/strategies" && c.method === "POST") return { ok: true, strategies: c.body?.strategies ?? [] }
    return undefined
  }
}
const saves = (calls: ApiCall[]) => calls.filter(c => c.path === "/api/live/strategies" && c.method === "POST").map(c => c.body)
const toggle = (page: any, name: string) => page.getByRole("switch", { name: `${name} تشتغل` })

test("it opens on the real-money account, marked in red with its name", async ({ page, api: a }) => {
  a.handler = api()
  await page.goto("/admin?tab=real")
  await expect(page.getByText('بتغيّر الحساب الحقيقي "main" — فلوس حقيقية')).toBeVisible()
  await expect(page.getByRole("heading", { name: "الاستراتيجيات على الحساب الحقيقي" })).toBeVisible()
  await expect(toggle(page, "مومنتم لونج/شورت")).toHaveAttribute("aria-checked", "true")
  await expect(toggle(page, "ترند يومي")).toHaveAttribute("aria-checked", "false")
})

test("turning the real bot off says which account and what stops; cancel sends nothing", async ({ page, api: a }) => {
  a.handler = api()
  await page.goto("/admin?tab=real")
  await toggle(page, "مومنتم لونج/شورت").click()
  const asked: string[] = []
  page.once("dialog", d => { asked.push(d.message()); d.dismiss() })
  await page.getByRole("button", { name: "احفظ التغييرات" }).click()
  await expect.poll(() => asked.length).toBe(1)
  expect(asked[0]).toContain('الحساب الحقيقي "main" (فلوس حقيقية)')
  expect(asked[0]).toContain("هتبطّل تدخل صفقات جديدة")
  expect(asked[0]).toContain("مومنتم لونج/شورت")
  expect(asked[0]).toContain("بعد الحفظ شغالين: ولا واحدة")
  expect(saves(a.calls)).toEqual([])                                        // cancelled: nothing sent
  page.once("dialog", d => d.accept())
  await page.getByRole("button", { name: "احفظ التغييرات" }).click()
  await expect.poll(() => saves(a.calls)).toEqual([{ env: "live", account: "main", strategies: [] }])
  await expect(page.getByText("✅ اتحفظ")).toBeVisible()
})

test("the Demo tab is marked apart, and its save goes to the Demo account only", async ({ page, api: a }) => {
  a.handler = api()
  await page.goto("/admin?tab=real")
  await expect(page.getByText(/بتغيّر الحساب الحقيقي/)).toBeVisible()
  await page.getByRole("button", { name: "Demo · فلوس وهمية" }).click()
  await expect(page.getByText("بتغيّر حساب الـ Demo — فلوس وهمية، وده بيأثر على قياس الـ Demo")).toBeVisible()
  await expect(page.getByText(/بتغيّر الحساب الحقيقي/)).toHaveCount(0)
  await toggle(page, "ترند النسبة بين العملات").click()
  const asked: string[] = []
  page.once("dialog", d => { asked.push(d.message()); d.accept() })
  await page.getByRole("button", { name: "احفظ التغييرات" }).click()
  await expect.poll(() => saves(a.calls).length).toBe(1)
  expect(asked[0]).toContain("حساب الـ Demo (فلوس وهمية)")
  expect(asked[0]).toContain("هيقف قياسها على الـ Demo")
  const sent = saves(a.calls)[0]                                            // (the API ignores the account name on Demo)
  expect([sent.env, sent.strategies]).toEqual(["demo", DEMO_ON.filter(id => id !== "ratio_trend")])
})

test("a late answer for the real account never fills the Demo tab", async ({ page, api: a }) => {
  a.handler = api({ liveDelayMs: 2500 })
  await page.goto("/admin?tab=real")
  await page.getByRole("button", { name: "Demo · فلوس وهمية" }).click()
  await expect(page.getByText(/بتغيّر حساب الـ Demo/)).toBeVisible()
  await page.waitForTimeout(3500)                                           // the real account's answer has arrived
  await expect(page.getByText(/بتغيّر حساب الـ Demo/)).toBeVisible()
  await expect(toggle(page, "مومنتم لونج/شورت")).toHaveAttribute("aria-checked", "false")   // Demo's, not the real one's
  await expect(toggle(page, "ترند يومي")).toHaveAttribute("aria-checked", "true")
})

test("the 15-second refresh never wipes a switch the admin hasn't saved", async ({ page, api: a }) => {
  test.setTimeout(60_000)
  a.handler = api()
  await page.goto("/admin?tab=real")
  await toggle(page, "ترند يومي").click()
  await expect(toggle(page, "ترند يومي")).toHaveAttribute("aria-checked", "true")
  const gets = () => a.calls.filter(c => c.path === "/api/live/strategies" && c.method === "GET").length
  const before = gets()
  await expect.poll(gets, { timeout: 20_000 }).toBeGreaterThan(before)      // a refresh came back with it off
  await expect(toggle(page, "ترند يومي")).toHaveAttribute("aria-checked", "true")
})

test("the real account can't be saved with strategies on and no account name", async ({ page, api: a }) => {
  a.handler = api({ account: "" })
  await page.goto("/admin?tab=real")
  await toggle(page, "ترند يومي").click()
  await expect(page.getByRole("button", { name: "احفظ التغييرات" })).toBeDisabled()
  await page.getByLabel(/اسم الحساب/).fill("main")
  await expect(page.getByRole("button", { name: "احفظ التغييرات" })).toBeEnabled()
})

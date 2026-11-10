import { test, expect } from "./fixtures"

// The three portfolios of research §31 on the paper bots' page (owner, 2026-11-09): the sum of the momentum, crowd and
// RSI-2 + BTC paper bots, every trade at $100 of margin, counting the trades opened from 2026-11-09 (a fixed date: the
// bots' "started" moves at every restart).

const S = Date.parse("2026-11-09T00:00:00Z")
const at = (h: number) => new Date(S + h * 3_600_000).toISOString()
type Trade = [opened: number, closed: number, pnl: number]
const bot = (margin: number, trades: Trade[], positions: unknown[] = []) => ({
  updated: new Date().toISOString(), mode: "paper", leverage: 2, margin, started: new Date().toISOString(),   // just restarted
  stats: { closed: trades.length, wins: 0, losses: 0, realized: 0, unrealized: 0, open: positions.length },
  positions, history: trades.map(([o, c, pnl]) => ({ symbol: "ADA/USDT", side: "long", entry: 1, exit: 1, pnl, reason: "x", opened: at(o), time: at(c) })),
})
const leg = (opened: number, extra: object) => ({ symbol: "SOL/USDT", id: "SOLUSDT", side: "long", entry: 1, price: 1.1, qty: 100, sl: 0.6, opened: at(opened), ...extra })
const FILES: Record<string, unknown> = {
  // an old basket's trade (opened before the 9th) closing after it is left out, and so is its still-open leg;
  // the open leg from the 9th: +$10 at $50 margin = +$20 at $100
  momentum: bot(100, [[-72, 2, -50], [1, 3, 30], [4, 5, -10]], [leg(-72, { margin: 100 }), leg(1, { margin: 50 })]),
  retail_fade: bot(20, [[6, 7, 4], [6, 8, -2]]),        // $20 margin: x5 -> +20, -10
  rsi2_btc: bot(100, [[9, 10, 10]]),
}

test("the paper page sums the three portfolios at $100 a coin from the trades opened on the 9th", async ({ page }) => {
  for (const [name, body] of Object.entries(FILES))
    await page.route(`http://paperbot.test/${name}.json*`, route =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }))
  await page.goto("http://paperbot.test/#view=pf")                           // the Portfolios tab
  const sec = page.locator("#pfSec")
  await expect(sec).toBeVisible()
  await expect(sec.getByRole("heading", { name: "المحافظ الثلاثة — تجربة Paper" })).toBeVisible()
  const rows = sec.locator("#pfRows tr")
  // momentum + crowd: +30 -10 +20 -10 = +30 realized, worst fall 10, open +20, total +50, one leg open
  await expect(rows.nth(0)).toContainText("مومنتم + عكس الأغلبية")
  await expect(rows.nth(0)).toContainText("50%")
  await expect(rows.nth(0)).toContainText("+$30.00")
  await expect(rows.nth(0)).toContainText("+$20.00")
  await expect(rows.nth(0)).toContainText("+$50.00")
  await expect(rows.nth(0)).toContainText("−$10.00")
  await expect(rows.nth(0)).toContainText("$100")
  // all three: and RSI-2's +10
  await expect(rows.nth(2)).toContainText("60%")
  await expect(rows.nth(2)).toContainText("+$40.00")
  await expect(sec.locator("#pfSince")).toContainText("09 Nov")
  await page.getByTestId("paper-lang").click()
  await expect(sec.getByRole("heading", { name: "The three portfolios — Paper test" })).toBeVisible()
  await expect(rows.nth(2)).toContainText("All three")
})

test("a portfolio whose bot has no file yet says so", async ({ page }) => {
  await page.route("http://paperbot.test/momentum.json*", route =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(FILES.momentum) }))
  await page.goto("http://paperbot.test/#view=pf")                           // the Portfolios tab
  const rows = page.locator("#pfSec #pfRows tr")
  await expect(rows.nth(0)).toContainText("مستني ملف عكس الأغلبية")
  await expect(rows.nth(2)).toContainText("مستني ملف عكس الأغلبية وRSI-2 + BTC")
})

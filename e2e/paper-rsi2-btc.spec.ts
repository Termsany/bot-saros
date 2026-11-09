import { test, expect } from "./fixtures"

// The second RSI-2 paper bot, with the BTC filter, on the paper bots' page (owner, 2026-11-07; research §28).

const RB = (above: boolean) => ({
  updated: new Date().toISOString(), mode: "paper", leverage: 2, margin: 100, rules: { btc_ma: 200 },
  stats: { closed: 3, wins: 2, losses: 1, realized: 4.2, unrealized: 0, open: 1 },
  btc_filter: { ma: 200, close: 98000, avg: 91000, above },
  watch: [{ symbol: "SOL/USDT", rsi2: 7.5, above_200: true, price: 150 }],
  positions: [{ symbol: "LINK/USDT", id: "LINKUSDT", side: "long", entry: 15, price: 15.3, qty: 13.3, margin: 100, sl: 9,
                pnl: 4, pnl_pct: 4, opened: "2026-11-07T00:00:00+00:00", exit_at: "2026-11-17T00:00:00+00:00" }],
  history: [{ symbol: "ADA/USDT", side: "long", entry: 0.5, exit: 0.52, pnl: 8, reason: "x", time: "2026-11-06T00:00:00+00:00" }],
})

test("the paper page hides the RSI-2 + BTC filter bot without its file", async ({ page }) => {
  await page.goto("http://paperbot.test/")
  await expect(page.getByRole("heading", { name: "بوت الترند اليومي — مباشر" })).toBeVisible()
  await expect(page.locator("#rbSec")).toBeHidden()
})

test("the paper page shows the RSI-2 + BTC filter bot and its filter state", async ({ page }) => {
  let above = true
  await page.route("http://paperbot.test/rsi2_btc.json*", route =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RB(above)) }))
  await page.goto("http://paperbot.test/")
  const sec = page.locator("#rbSec")
  await expect(sec).toBeVisible()
  await expect(sec.getByRole("heading", { name: /RSI-2 \+ فلتر BTC/ })).toBeVisible()
  await expect(sec.locator("#rbWatch")).toContainText("الدخول مفتوح")
  await expect(sec.locator("#rbPositions")).toContainText("LINK")
  await expect(sec.locator("#rbHistory")).toContainText("ADA")
  await expect(page.locator("#r2Sec")).toBeHidden()                            // the first RSI-2 bot has no file here
  await page.getByTestId("paper-lang").click()
  await expect(sec.getByRole("heading", { name: /RSI-2 \+ BTC filter/ })).toBeVisible()
  above = false
  await expect(sec.locator("#rbWatch")).toContainText("below its 200-day average", { timeout: 20000 })
})

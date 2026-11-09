import { test, expect } from "./fixtures"

// The against-the-crowd paper bot on the paper bots' page (owner, 2026-11-07; research §29): hidden until its file exists.

const RF = () => ({
  updated: new Date().toISOString(), mode: "paper", leverage: 2, margin: 20, next_rebalance: "2026-11-11T00:00:00+00:00",
  stats: { closed: 2, wins: 1, losses: 1, realized: 1.5, unrealized: 0, open: 2 },
  positions: [{ symbol: "SOL/USDT", id: "SOLUSDT", side: "long", entry: 150, price: 151, qty: 0.27, margin: 20, sl: 90, pnl: 0.27, pnl_pct: 1.3, ratio: 0.85, opened: "2026-11-07T00:00:00+00:00" },
              { symbol: "XRP/USDT", id: "XRPUSDT", side: "short", entry: 2.4, price: 2.38, qty: 16.7, margin: 20, sl: 3.36, pnl: 0.33, pnl_pct: 1.7, ratio: 3.61, opened: "2026-11-07T00:00:00+00:00" }],
  ranking: [], history: [{ symbol: "ADA/USDT", side: "long", entry: 0.5, exit: 0.52, pnl: 1.5, reason: "x", time: "2026-11-06T00:00:00+00:00" }],
})

test("the paper page hides the against-the-crowd bot without its file", async ({ page }) => {
  await page.goto("http://paperbot.test/")
  await expect(page.getByRole("heading", { name: "بوت الترند اليومي — مباشر" })).toBeVisible()
  await expect(page.locator("#rfSec")).toBeHidden()
})

test("the paper page shows the against-the-crowd bot with each coin's long/short ratio", async ({ page }) => {
  await page.route("http://paperbot.test/retail_fade.json*", route =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RF()) }))
  await page.goto("http://paperbot.test/")
  const sec = page.locator("#rfSec")
  await expect(sec).toBeVisible()
  await expect(sec.getByRole("heading", { name: /عكس الأغلبية/ })).toBeVisible()
  await expect(sec.locator("#rfPositions")).toContainText("3.61")
  await expect(sec.locator("#rfPositions")).toContainText("SOL")
  await expect(sec.locator("#rfHistory")).toContainText("ADA")
  await page.getByTestId("paper-lang").click()
  await expect(sec.getByRole("heading", { name: /Against the crowd/ })).toBeVisible()
})

import { test, expect } from "./fixtures"

// The 20% trail ratio paper bot (owner, 2026-11-10; research §35): its own section under the no-BTC one, hidden until
// its file exists.

const RT = () => ({
  updated: new Date().toISOString(), risk: "high", mode: "paper", leverage: 2, margin: 40, members: ["SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK"],
  next_members: "2026-11-14T00:00:00+00:00", stats: { closed: 1, wins: 1, losses: 0, realized: 3.1, unrealized: 0, open: 1 },
  pairs: [{ pair: "SOL/USDT:USDT|XRP/USDT:USDT", pnl: 1.2, margin: 80, opened: "2026-11-10T00:00:00+00:00", peak: 2.0,
            long: { symbol: "SOL/USDT", id: "SOLUSDT", side: "long", entry: 150, price: 151, qty: 0.53, pnl: 0.5 },
            short: { symbol: "XRP/USDT", id: "XRPUSDT", side: "short", entry: 2.4, price: 2.38, qty: 33, pnl: 0.7 } }],
  history: [{ pair: "DOGE / ADA", pnl: 3.1, reason: "trailing 20%", peak: 9.4, time: "2026-11-10T00:00:00+00:00" }],
})

test("the paper page hides the trail ratio bot without its file", async ({ page }) => {
  await page.goto("http://paperbot.test/")
  await expect(page.getByRole("heading", { name: "بوت الترند اليومي — مباشر" })).toBeVisible()
  await expect(page.locator("#ratioTrSec")).toBeHidden()
})

test("the paper page shows the trail ratio bot from ratio_trail.json, apart from the no-BTC one", async ({ page }) => {
  await page.route("http://paperbot.test/ratio_trail.json*", route =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RT()) }))
  await page.goto("http://paperbot.test/")
  const sec = page.locator("#ratioTrSec")
  await expect(sec).toBeVisible()
  await expect(sec.getByRole("heading", { name: /trailing 20%/ })).toBeVisible()
  await expect(sec.locator("#rtMembers")).toContainText("LINK")
  await expect(sec.locator("#rtPairs")).toContainText("SOL")
  await expect(sec.locator("#rtHistory")).toContainText("DOGE / ADA")
  await expect(sec.locator("#rtHistory")).toContainText("trailing 20%")
  await expect(page.locator("#ratioNbSec")).toBeHidden()                      // the no-BTC bot has no file here
  await page.getByTestId("paper-lang").click()
  await expect(sec.getByRole("heading", { name: /Ratio trend without BTC\/ETH \+ 20% trailing/ })).toBeVisible()
})

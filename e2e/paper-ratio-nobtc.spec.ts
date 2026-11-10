import { test, expect } from "./fixtures"

// The second ratio paper bot on the paper bots' page (owner, 2026-11-07; research §25): hidden until its file exists.

const RN = () => ({
  updated: new Date().toISOString(), risk: "high", mode: "paper", leverage: 2, margin: 40, members: ["SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK"],
  next_members: "2026-11-14T00:00:00+00:00", stats: { closed: 1, wins: 1, losses: 0, realized: 2.5, unrealized: 0, open: 1 },
  pairs: [{ pair: "SOL/USDT:USDT|XRP/USDT:USDT", pnl: 1.2, margin: 80, opened: "2026-11-07T00:00:00+00:00",
            long: { symbol: "SOL/USDT", id: "SOLUSDT", side: "long", entry: 150, price: 151, qty: 0.53, pnl: 0.5 },
            short: { symbol: "XRP/USDT", id: "XRPUSDT", side: "short", entry: 2.4, price: 2.38, qty: 33, pnl: 0.7 } }],
  history: [{ pair: "BNB / ADA", pnl: 2.5, reason: "x", time: "2026-11-06T00:00:00+00:00" }],
})

test("the paper page hides the no-BTC ratio bot without its file", async ({ page }) => {
  await page.goto("http://paperbot.test/")
  await expect(page.getByRole("heading", { name: "بوتات الـ Paper" })).toBeVisible()
  await expect(page.getByTestId("row-ratio_nobtc")).toHaveCount(0)                     // no file, no row
  await expect(page.locator("#ratioNbSec")).toBeHidden()
})

test("the paper page shows the no-BTC ratio bot from ratio_nobtc.json, apart from the first one", async ({ page }) => {
  await page.route("http://paperbot.test/ratio_nobtc.json*", route =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RN()) }))
  await page.goto("http://paperbot.test/")
  await page.getByTestId("row-ratio_nobtc").click()                                // its section opens in the side panel
  const sec = page.locator("#ratioNbSec")
  await expect(sec).toBeVisible()
  await expect(sec.getByRole("heading", { name: /Ratio trend من غير BTC\/ETH/ })).toBeVisible()
  await expect(sec.locator("#rnMembers")).toContainText("LINK")
  await expect(sec.locator("#rnMembers")).not.toContainText("BTC")
  await expect(sec.locator("#rnPairs")).toContainText("SOL")
  await expect(sec.locator("#rnHistory")).toContainText("BNB / ADA")
  await expect(page.locator("#ratioSec")).toBeHidden()                         // the first ratio bot has no file here
  await page.getByTestId("drawer-close").click()
  await page.getByTestId("paper-lang").click()
  await page.getByTestId("row-ratio_nobtc").click()
  await expect(sec.getByRole("heading", { name: /Ratio trend without BTC\/ETH/ })).toBeVisible()
})

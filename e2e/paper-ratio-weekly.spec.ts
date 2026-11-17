import { test, expect } from "./fixtures"

// The weekly ratio paper bot (owner, 2026-11-17; research §41): the no-BTC ratio trend switching only on Monday, its own
// section and an A/B row against the daily no-BTC bot, hidden until its file exists.

const RK = () => ({
  updated: new Date().toISOString(), risk: "high", mode: "paper", leverage: 2, margin: 40, members: ["SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK"],
  next_members: "2026-11-30T00:00:00+00:00", next_switch: "2026-11-30T00:00:00+00:00",
  stats: { closed: 1, wins: 1, losses: 0, realized: 2.4, unrealized: 0, open: 1 },
  pairs: [{ pair: "SOL/USDT:USDT|XRP/USDT:USDT", pnl: 1.2, margin: 80, opened: "2026-11-23T00:00:00+00:00",
            long: { symbol: "SOL/USDT", id: "SOLUSDT", side: "long", entry: 150, price: 151, qty: 0.53, pnl: 0.5 },
            short: { symbol: "XRP/USDT", id: "XRPUSDT", side: "short", entry: 2.4, price: 2.38, qty: 33, pnl: 0.7 } }],
  history: [{ pair: "DOGE / ADA", pnl: 2.4, reason: "الترند اتقلب", time: "2026-11-23T00:00:00+00:00" }],
})

test("the paper page hides the weekly ratio bot without its file", async ({ page }) => {
  await page.goto("http://paperbot.test/")
  await expect(page.getByRole("heading", { name: "بوتات الـ Paper" })).toBeVisible()
  await expect(page.getByTestId("row-ratio_weekly")).toHaveCount(0)                    // no file, no row
  await expect(page.locator("#ratioWkSec")).toBeHidden()
})

test("the paper page shows the weekly ratio bot from ratio_weekly.json, with its next switch", async ({ page }) => {
  await page.route("http://paperbot.test/ratio_weekly.json*", route =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RK()) }))
  await page.goto("http://paperbot.test/")
  await page.getByTestId("row-ratio_weekly").click()                               // its section opens in the side panel
  const sec = page.locator("#ratioWkSec")
  await expect(sec).toBeVisible()
  await expect(sec.getByRole("heading", { name: /تبديل أسبوعي/ })).toBeVisible()
  await expect(sec.locator("#rkMembers")).toContainText("LINK")
  await expect(sec.locator("#rkPairs")).toContainText("SOL")
  await expect(sec.locator("#rkHistory")).toContainText("DOGE / ADA")
  await expect(sec.locator("#rkNext")).toContainText("التبديل الجاي")
  await expect(page.locator("#ratioNbSec")).toBeHidden()                     // the daily no-BTC bot has no file here
  await page.getByTestId("drawer-close").click()
  await page.getByTestId("paper-lang").click()
  await page.getByTestId("row-ratio_weekly").click()
  await expect(sec.getByRole("heading", { name: /Ratio trend without BTC\/ETH · weekly switch/ })).toBeVisible()
  await expect(sec.locator("#rkNext")).toContainText("next switch")
})

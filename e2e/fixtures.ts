import { test as base, expect, type Page } from "@playwright/test"
import { readFileSync } from "node:fs"
import path from "node:path"

/** Sample data the pages read, so a test sees the same thing every run and never the real bots. */
const now = () => new Date().toISOString()

export const PAPER = (live: string) => ({
  updated: now(), stats: { realized: 3.5, unrealized: -1.25, closed: 2, wins: 1, losses: 1 },
  positions: live === "ratio" ? [] : [{ symbol: "SOL/USDT", side: "long", entry: 150, price: 152, pnl: 1.3, sl: 90 }],
  pairs: [], history: [{ symbol: "BNB/USDT", side: "long", entry: 700, exit: 707, pnl: 1.0, reason: "test", time: now() }],
})

export const REAL = () => ({
  updated: now(),
  bots: [{
    strategy: "momentum_ls", updated: now(), running: true, leverage: 2, next_rebalance: "2026-11-09T00:00:00+00:00",
    positions: [
      { symbol: "AGT/USDT", side: "short", entry: 0.05207, price: 0.0436, qty: 998, contract_size: 1, sl: 0.0729, pnl: 8.4, loss_at_sl: -20.86, opened: now() },
      { symbol: "AIN/USDT", side: "long", entry: 0.2727, price: 0.28, qty: 190, contract_size: 1, sl: 0.1633, pnl: 1.4, loss_at_sl: -20.8, opened: now() },
    ],
    history: [{ symbol: "IDOL/USDT", side: "long", entry: 0.0181, exit: 0.0204, qty: 4417, pnl: 9.96, pnl_pct: 12.6, reason: "تبديل أسبوعي", time: now() }],
  }],
})

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
const REALBOT_HTML = readFileSync(path.join(__dirname, "..", "deploy", "vps", "realbot", "index.html"), "utf-8")

/** Answers what the pages need, blocks every other outside request (Binance, Supabase, the API, fonts). */
async function offline(page: Page){
  await page.route("**/*", route => {
    const url = new URL(route.request().url())
    if (url.hostname === "localhost") {
      if (url.pathname === "/api/realbot") return route.fulfill(json(REAL()))
      return route.continue()
    }
    if (url.hostname === "bot.da3m.io") return route.fulfill(json(PAPER(url.pathname.replace(/^\/|\.json$/g, ""))))
    if (url.hostname === "realbot.test") {
      if (url.pathname === "/live.json") return route.fulfill(json(REAL()))
      return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: REALBOT_HTML })
    }
    return route.abort()
  })
}

export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => { await offline(page); await use(page) },
})
export { expect }

/** No sideways scrolling: the page is never wider than the screen. */
export async function expectNoSideScroll(page: Page){
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(scroll, "page wider than the screen").toBeLessThanOrEqual(width)
}

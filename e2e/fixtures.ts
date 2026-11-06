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

/** bot.da3m.io's own page (deploy/vps/page/index.html), served at paperbot.test: the trend bot and momentum, the rest absent. */
const PAPER_PAGE: Record<string, () => unknown> = {
  status: () => ({ updated: now(), started: now(), mode: "paper", leverage: 2, margin: 100, universe_size: 10, poll_seconds: 60,
    stats: { realized: 3.5, closed: 2, wins: 1, losses: 1, open: 1 },
    positions: [{ symbol: "SOL/USDT", side: "long", entry: 150, price: 152, qty: 1, margin: 50, sl: 90, opened: now() },
                { symbol: "ENA/USDT", side: "long", entry: 0.2, price: 0.21, qty: 100, margin: null, sl: 0.12, opened: now() }],   // contract size unknown
    signals: [{ symbol: "SOL/USDT", price: 152, on: true, in_list: true }, { symbol: "BTC/USDT", price: 70000, on: false, in_list: true }],
    history: [{ symbol: "BNB/USDT", entry: 700, exit: 707, pnl: 1.0, reason: "الترند وقف", time: now() }] }),
  momentum: () => ({ updated: now(), next_rebalance: "2026-11-09T00:00:00+00:00", stats: { realized: -2, closed: 1, wins: 0, losses: 1 },
    positions: [{ symbol: "AGT/USDT", id: "AGTUSDT", side: "short", ret: -30, entry: 0.05, price: 0.045, qty: 1000, margin: 25, sl: 0.07 }],
    history: [{ symbol: "IDOL/USDT", side: "long", entry: 0.0181, exit: 0.0204, pnl: -2, reason: "تبديل أسبوعي", time: now() },
              { symbol: "AIN/USDT", side: "short", entry: 0.25, exit: 0.0346, pnl: -1, reason: "وقف 0.0346", time: now() }] }),
}

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
const REALBOT_HTML = readFileSync(path.join(__dirname, "..", "deploy", "vps", "realbot", "index.html"), "utf-8")
const PAPER_HTML = readFileSync(path.join(__dirname, "..", "deploy", "vps", "page", "index.html"), "utf-8")

/** A fake API for a test: (method, path, body) → a JSON answer, or undefined for a 404, or an ApiStatus for another
 *  status (e.g. a 409 the page must ask about). Every call is recorded. */
export class ApiStatus { constructor(public status: number, public body: unknown) {} }
export type ApiCall = { method: string, path: string, query: string, body: any }
export type ApiHandler = (call: ApiCall) => unknown | Promise<unknown>
const SITE_PORT = "3100"     // playwright.config.ts: the site; any other localhost port is the (fake) API

/** Answers what the pages need, blocks every other outside request (Binance, Supabase, the API, fonts). */
async function offline(page: Page, api?: { handler: ApiHandler, calls: ApiCall[] }){
  await page.route("**/*", async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.hostname === "localhost" && url.port === SITE_PORT) {
      if (url.pathname === "/api/realbot") return route.fulfill(json(REAL()))
      return route.continue()
    }
    // the signed-in user, for Supabase's /auth/v1/user (the session itself comes from storage: signInAsAdmin)
    if (api && url.pathname === "/auth/v1/user") return route.fulfill(json(ADMIN_USER))
    if (api && url.pathname.startsWith("/api/")) {
      if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS })
      const call = { method: req.method(), path: url.pathname, query: url.search, body: req.postDataJSON?.() ?? null }
      api.calls.push(call)
      const answer = await api.handler(call)
      if (answer instanceof ApiStatus) return route.fulfill({ status: answer.status, headers: CORS, contentType: "application/json", body: JSON.stringify(answer.body) })
      return answer === undefined ? route.fulfill({ status: 404, headers: CORS, contentType: "application/json", body: "{}" })
        : route.fulfill({ status: 200, headers: CORS, contentType: "application/json", body: JSON.stringify(answer) })
    }
    if (url.hostname === "demo.da3m.io") return route.fulfill(json(PAPER(url.pathname.replace(/^\/|\.json$/g, ""))))
    if (url.hostname === "realbot.test") {
      if (url.pathname === "/live.json") return route.fulfill(json(REAL()))
      return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: REALBOT_HTML })
    }
    if (url.hostname === "paperbot.test") {
      const file = url.pathname.replace(/^\/|\.json$/g, "")
      if (url.pathname.endsWith(".json")) return PAPER_PAGE[file] ? route.fulfill(json(PAPER_PAGE[file]())) : route.fulfill({ status: 404, body: "" })
      return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: PAPER_HTML })
    }
    return route.abort()
  })
}

export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => { await offline(page); await use(page) },
})

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type", "access-control-allow-methods": "GET, POST, PATCH" }
export const ADMIN_USER = { id: "00000000-0000-4000-8000-0000000000ad", email: "admin@example.com", aud: "authenticated", role: "authenticated",
  email_confirmed_at: "2026-01-01T00:00:00Z", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" }

/** A Supabase session in the browser's storage (any project's key), so the site sends a bearer token; nothing checks
 *  it but the fake API. Never a real token. */
async function signInAsAdmin(page: Page){
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url")
  const exp = Math.floor(Date.now() / 1000) + 3600
  const token = `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: ADMIN_USER.id, email: ADMIN_USER.email, exp, role: "authenticated" })}.e2e`
  const session = { access_token: token, refresh_token: "e2e-refresh", token_type: "bearer", expires_in: 3600, expires_at: exp, user: ADMIN_USER }
  await page.addInitScript(raw => {
    const get = Storage.prototype.getItem
    Storage.prototype.getItem = function(key: string){
      return /^sb-.*-auth-token$/.test(key) ? (get.call(this, key) ?? raw) : get.call(this, key)
    }
  }, JSON.stringify(session))
}

/** The admin signed in, against a fake API: `api.handler` answers, `api.calls` records what the page sent. */
export const adminTest = base.extend<{ page: Page, api: { handler: ApiHandler, calls: ApiCall[] } }>({
  api: async ({}, use) => { await use({ handler: () => undefined, calls: [] }) },
  page: async ({ page, api }, use) => { await signInAsAdmin(page); await offline(page, api); await use(page) },
})
export { expect }

/** No sideways scrolling: the page is never wider than the screen. */
export async function expectNoSideScroll(page: Page){
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(scroll, "page wider than the screen").toBeLessThanOrEqual(width)
}

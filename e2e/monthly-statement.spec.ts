import { adminTest as test, expect, expectNoSideScroll } from "./fixtures"

// The monthly statement (owner, 2026-11-08): the month's closed trades per bot and in total, real money and Demo
// apart, another month from the list, and the trades as a CSV file.

const sum = (o: object) => ({ trades: 0, wins: 0, losses: 0, unknown: 0, net_usdt: 0, funding_usdt: null, best_usdt: null, worst_usdt: null, ...o })
const NOV = {
  month: "2026-11", env: "live", months: ["2026-11", "2026-10"],
  total: sum({ trades: 2, wins: 1, losses: 1, net_usdt: 1.5, funding_usdt: -0.05, best_usdt: 3.5, worst_usdt: -2 }),
  strategies: { momentum_ls: { env: "live", ...sum({ trades: 2, wins: 1, losses: 1, net_usdt: 1.5 }) } },
  trades: [
    { strategy: "momentum_ls", env: "live", symbol: "SOL/USDT", side: "short", opened: "2026-11-09T00:20:00Z", time: "2026-11-16T00:20:00Z", entry: 100, exit: 102, qty: 1, pnl: -2, funding_pnl: 0.05, reason: "rebalance" },
    { strategy: "momentum_ls", env: "live", symbol: "BTC/USDT", side: "long", opened: "2026-11-02T00:20:00Z", time: "2026-11-09T00:20:00Z", entry: 1, exit: 2, qty: 1, pnl: 3.5, funding_pnl: -0.1, reason: "rebalance" },
  ],
}
const OCT = { ...NOV, month: "2026-10", total: sum({ trades: 1, wins: 1, net_usdt: 9 }), strategies: { momentum_ls: { env: "live", ...sum({ trades: 1, wins: 1, net_usdt: 9 }) } },
  trades: [{ ...NOV.trades[1], time: "2026-10-31T00:20:00Z", pnl: 9 }] }

test("the statement shows the month, switches month and money, and downloads a CSV", async ({ page, api }) => {
  api.handler = c => {
    if (c.path !== "/api/user/statement") return undefined
    const q = new URLSearchParams(c.query)
    if (q.get("env") === "demo") return { ...NOV, env: "demo", months: [], total: sum({}), strategies: {}, trades: [] }
    return q.get("month") === "2026-10" ? OCT : NOV
  }
  await page.goto("/settings/statement")
  await expect(page.getByRole("heading", { name: "كشف الحساب الشهري" })).toBeVisible()
  await expect(page.getByTestId("statement-total")).toContainText("+1.50$")
  await expect(page.getByTestId("statement-trade")).toHaveCount(2)
  await expect(page.getByTestId("statement-bots")).toContainText("2 صفقة")
  await expectNoSideScroll(page)

  const download = page.waitForEvent("download")
  await page.getByTestId("statement-csv").click()
  const file = await download
  expect(file.suggestedFilename()).toBe("raqm-statement-live-2026-11.csv")
  const text = require("fs").readFileSync(await file.path(), "utf-8")
  expect(text).toContain("time,opened,strategy,env,symbol,side,entry,exit,qty,pnl,funding_pnl,reason")
  expect(text).toContain("SOL/USDT,short,100,102,1,-2,0.05,rebalance")

  await page.getByTestId("statement-month").selectOption("2026-10")
  await expect(page.getByTestId("statement-total")).toContainText("+9.00$")
  expect(api.calls.some(c => c.path === "/api/user/statement" && c.query.includes("month=2026-10"))).toBe(true)

  await page.getByTestId("statement-env-demo").click()
  await expect(page.getByText("مفيش صفقات مقفولة في الشهر ده")).toBeVisible()
})

import { adminTest as test, expect, type ApiCall } from "./fixtures"

// The owner's switch for real money for invited users (owner, 2026-11-07: from the site, no server command). A
// signed-in admin against a fake API — nothing reaches the real one.

function api(state: { on: boolean }){
  return async (c: ApiCall) => {
    if (c.path === "/api/user/me") return { admin: true, email: "admin@example.com" }
    if (c.path === "/api/live/status") return { running: true, strategies: {} }
    if (c.path === "/api/live/strategies") return { env: "live", acct: "", accounts: [], enabled: true, capital: {}, strategies: [] }
    if (c.path === "/api/admin/users-live" && c.method === "GET")
      return { on: state.on, by: state.on ? "admin@example.com" : null, at: state.on ? "2026-11-07T09:00:00+00:00" : null }
    if (c.path === "/api/admin/users-live" && c.method === "POST") { state.on = c.body.on; return { ok: true, on: state.on } }
    if (c.path === "/api/admin/user-bots") return { max_users: 4, approved: 0, users: [
      { user_id: "e8a3ec73-a62c-42c1-afa1-90a96e3aa75d", email: "second@example.com", approved: false, bots: {},
        provision: { state: "waiting_approval" }, desired: { env: "live", strategies: ["momentum_ls"], capital_usdt: 405, capital_margin_override_usdt: 36 } }] }
    return undefined
  }
}

test("the owner opens real money for invited users after a warning, and can close it again", async ({ page, api: a }) => {
  const state = { on: false }
  a.handler = api(state)
  await page.goto("/admin?tab=real")
  await expect(page.getByText("فلوس حقيقية للمستخدمين المدعوين")).toBeVisible()
  await expect(page.getByText("مقفولة", { exact: true })).toBeVisible()
  page.once("dialog", d => d.dismiss())                                           // cancel: nothing sent
  await page.getByTestId("users-live-switch").click()
  expect(a.calls.filter(c => c.path === "/api/admin/users-live" && c.method === "POST")).toHaveLength(0)
  page.once("dialog", d => { expect(d.message()).toContain("هيبدأ يتداول بفلوسه الحقيقية"); d.accept() })
  await page.getByTestId("users-live-switch").click()
  await expect(page.getByText("مفتوحة", { exact: true })).toBeVisible()
  expect(a.calls.find(c => c.path === "/api/admin/users-live" && c.method === "POST")!.body).toEqual({ on: true, confirm: true })
  page.once("dialog", d => { expect(d.message()).toContain("هيبطّلوا يفتحوا سلات جديدة"); d.accept() })
  await page.getByTestId("users-live-switch").click()
  await expect(page.getByText("مقفولة", { exact: true })).toBeVisible()
})

test("the users' table names each account by its email and says when it's real money", async ({ page, api: a }) => {
  a.handler = api({ on: false })
  await page.goto("/admin?tab=real")
  const who = page.getByTestId("user-bots-who")
  await expect(who).toContainText("second@example.com")
  await expect(who).toContainText("e8a3ec73")
  await expect(page.getByText("حقيقية · 405$ / 36$")).toBeVisible()
  await expect(page.getByText("بوتات المستخدمين", { exact: true })).toBeVisible()
})

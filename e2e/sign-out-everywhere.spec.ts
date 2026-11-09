import { adminTest as test, expect } from "./fixtures"

// Security plan item 9 (owner, 2026-11-08): "sign out of every device" — the sidebar on a computer, the account
// menu on a phone — Supabase's global logout, after asking.

async function signOutAllButton(page: import("@playwright/test").Page){
  const shown = page.getByTestId("sign-out-everywhere").filter({ visible: true })
  const menu = page.getByRole("button", { name: "حسابك" })
  if (!(await shown.count()) && await menu.isVisible()) await menu.click()   // a phone: it's in the account menu
  return shown
}

test("signing out of every device asks first, then ends every session", async ({ page, api: a }) => {
  await page.goto("/settings/live")
  await expect(page.getByRole("heading", { name: /بوتاتي على Binance/ })).toBeVisible()
  const item = await signOutAllButton(page)
  await expect(item).toContainText("اخرج من كل الأجهزة")
  page.once("dialog", d => d.dismiss())                                           // "no": nothing happens
  await item.click()
  await page.waitForTimeout(300)
  expect(a.calls.filter(c => c.path === "/auth/v1/logout")).toHaveLength(0)
  page.once("dialog", d => { expect(d.message()).toContain("كل الأجهزة"); d.accept() })
  await (await signOutAllButton(page)).click()
  await expect.poll(() => a.calls.filter(c => c.path === "/auth/v1/logout").map(c => c.query)).toEqual(["?scope=global"])
  await expect(page).toHaveURL(/\/(ar)?$/)
})

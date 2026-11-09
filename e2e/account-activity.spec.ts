import { adminTest as test, expect, expectNoSideScroll } from "./fixtures"

// Security plan item 10 (owner, 2026-11-08): the account's own sign-ins and sensitive changes, newest first, with a
// way out if something wasn't them.

const ITEMS = [
  { at: "2026-11-08T10:00:00+00:00", kind: "session", what: "دخول جديد", ip: "203.0.113.7", device: "Chrome · Windows", details: null },
  { at: "2026-11-08T09:00:00+00:00", kind: "real_money", what: "وافق على فلوس حقيقية", ip: null, device: null, details: { capital: 300 } },
  { at: "2026-11-07T20:00:00+00:00", kind: "admin", what: "Kill switch trip (ok)", ip: null, device: null, details: null },
]

test("the activity page lists the account's own sign-ins and changes", async ({ page, api }) => {
  api.handler = c => c.path === "/api/user/activity" ? { items: ITEMS, keep_days: 180 } : undefined
  await page.goto("/settings/activity")
  await expect(page.getByRole("heading", { name: "نشاط الحساب" })).toBeVisible()
  const items = page.getByTestId("activity-item")
  await expect(items).toHaveCount(3)
  await expect(items.nth(0)).toContainText("Chrome · Windows")
  await expect(items.nth(0)).toContainText("203.0.113.7")
  await expect(items.nth(1)).toContainText("capital: 300")
  await expect(items.nth(2)).toContainText("أدمن")
  await expect(page.getByTestId("activity-sign-out-everywhere")).toBeVisible()
  await expectNoSideScroll(page)
})

test("an empty or failed activity page says so", async ({ page, api }) => {
  api.handler = c => c.path === "/api/user/activity" ? { items: [], keep_days: 180 } : undefined
  await page.goto("/settings/activity")
  await expect(page.getByText("لسه مفيش نشاط متسجل")).toBeVisible()
  api.handler = () => undefined                                                     // a 404 from the API
  await page.reload()
  await expect(page.getByText("مقدرناش نجيب النشاط")).toBeVisible()
})

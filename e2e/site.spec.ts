import { test, expect, expectNoSideScroll } from "./fixtures"

// What the owner found by hand in 2026-11-03/04 — the plans' promises, the terms, the real-money card, the realbot
// page on a phone — checked on every PR, on a desktop and a phone screen.

test("the plans say what they unlock, and link the terms", async ({ page }) => {
  await page.goto("/")
  const plans = page.locator("#pricing")
  await expect(plans.getByText("لسه مابتشغّلش بوتات على حسابك في Binance")).toBeVisible()
  for (const name of ["Free", "Starter", "Pro", "Elite"]) await expect(plans.getByText(name, { exact: true }).first()).toBeVisible()
  await expect(plans.getByText("بوتين")).toHaveCount(0)                       // the old wording promised bots on the account
  await expectNoSideScroll(page)
  await plans.getByRole("link", { name: "الشروط والمخاطر" }).click()
  await expect(page).toHaveURL(/\/terms$/)
  await expect(page.getByRole("heading", { name: "الشروط والمخاطر" })).toBeVisible()
})

test("the terms state the cancellation and refund policy", async ({ page }) => {
  await page.goto("/terms")
  await expect(page.getByRole("heading", { level: 2 })).toHaveCount(8)
  await expect(page.getByText("مفيش استرجاع فلوس", { exact: false }).first()).toBeVisible()
  await expect(page.getByText("إدارة الاشتراك / الإلغاء", { exact: false })).toBeVisible()
  await expectNoSideScroll(page)
})

test("the dashboard shows the real-money bot first, the paper bots apart", async ({ page }) => {
  await page.goto("/dashboard")
  await expect(page.getByText("LIVE · فلوس حقيقية")).toBeVisible()
  await expect(page.getByText("AGT", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("التبديل الجاي (البوت الحقيقي)")).toBeVisible()
  await expect(page.getByText("+9.96").first()).toBeVisible()                  // realized, from the closed trade
  await expect(page.getByRole("heading", { name: "بوتات التجربة" })).toBeVisible()
  // the real card comes before the paper section
  const realY = (await page.getByText("LIVE · فلوس حقيقية").boundingBox())!.y
  const paperY = (await page.getByRole("heading", { name: "بوتات التجربة" }).boundingBox())!.y
  expect(realY).toBeLessThan(paperY)
  await expectNoSideScroll(page)
})

test("realbot.da3m.io shows the positions, as cards on a phone", async ({ page, isMobile }) => {
  await page.goto("http://realbot.test/")
  await expect(page.getByText("AGT/USDT").first()).toBeVisible()
  await expect(page.getByText("التبديل الجاي")).toBeVisible()
  await expect(page.getByText("IDOL/USDT").first()).toBeVisible()             // closed trades
  await expectNoSideScroll(page)
  const header = page.locator("thead").first()
  if (isMobile) {
    await expect(header).toBeHidden()                                         // rows are cards, each value labelled
    await expect(page.locator('td[data-l="الدخول"]').first()).toBeVisible()
  } else {
    await expect(header).toBeVisible()
  }
})

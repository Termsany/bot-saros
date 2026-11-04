import { test, expect, expectNoSideScroll } from "./fixtures"

// What the owner found by hand in 2026-11-03/04 — the plans' promises, the terms, the real-money card, the realbot
// page on a phone — checked on every PR, on a desktop and a phone screen.

test("the plans say what they unlock, and link the terms — English on /", async ({ page }) => {
  await page.goto("/")
  await expect(page.locator("html")).toHaveAttribute("lang", "en")
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr")
  const plans = page.locator("#pricing")
  await expect(plans.getByText("They don't run bots on your Binance account yet")).toBeVisible()
  for (const name of ["Free", "Starter", "Pro", "Elite"]) await expect(plans.getByText(name, { exact: true }).first()).toBeVisible()
  await expectNoSideScroll(page)
  await plans.getByRole("link", { name: "Terms & risks (Arabic)" }).click()
  await expect(page).toHaveURL(/\/terms$/)
  await expect(page.getByRole("heading", { name: "الشروط والمخاطر" })).toBeVisible()
})

test("the Arabic landing is right to left and says the same", async ({ page }) => {
  await page.goto("/ar")
  await expect(page.locator("html")).toHaveAttribute("lang", "ar")
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl")
  const plans = page.locator("#pricing")
  await expect(plans.getByText("لسه مابتشغّلش بوتات على حسابك في Binance")).toBeVisible()
  await expect(plans.getByText("بوتين")).toHaveCount(0)                       // the old wording promised bots on the account
  await expectNoSideScroll(page)
  await page.getByTestId("lang-switch").click()                              // EN
  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator("html")).toHaveAttribute("lang", "en")
})

test("the hero's live card shows the real basket, and the theme switch flips light and dark", async ({ page }) => {
  await page.goto("/")
  const card = page.getByTestId("live-card")
  await expect(card.getByText("AGT/USDT", { exact: true })).toBeVisible()     // from /api/realbot (e2e/fixtures.ts REAL)
  await expect(card.getByText("Next rebalance", { exact: false })).toBeVisible()
  await expect(page.getByTestId("real-vs-backtest").getByText("after 30 trades (1/30)").first()).toBeVisible()
  const html = page.locator("html")
  const before = await html.getAttribute("data-theme")
  await page.getByRole("button", { name: /Switch to (light|dark)/ }).click()
  await expect(html).toHaveAttribute("data-theme", before === "light" ? "dark" : "light")
  await page.reload()                                                         // remembered
  await expect(html).toHaveAttribute("data-theme", before === "light" ? "dark" : "light")
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
  await expect(page.getByText("AGT/USDT", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("التبديل الجاي (البوت الحقيقي)")).toBeVisible()
  await expect(page.getByText("+9.96").first()).toBeVisible()                  // realized, from the closed trade
  await expect(page.getByRole("heading", { name: "بوتات التجربة" })).toBeVisible()
  // the real card comes before the paper section
  const realY = (await page.getByText("LIVE · فلوس حقيقية").boundingBox())!.y
  const paperY = (await page.getByRole("heading", { name: "بوتات التجربة" }).boundingBox())!.y
  expect(realY).toBeLessThan(paperY)
  await expectNoSideScroll(page)
})

test("the dashboard in English after the English landing, with the light theme", async ({ page }) => {
  await page.goto("/")                                                        // the English landing remembers the language
  await page.goto("/dashboard")
  await expect(page.locator("html")).toHaveAttribute("lang", "en")
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr")
  await expect(page.getByText("LIVE · real money").first()).toBeVisible()
  await expect(page.getByText("Next rebalance (real bot)")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Paper bots" })).toBeVisible()
  await expect(page.locator('a[href="/settings/live"]').first()).toContainText("My Binance Demo bots")
  await expectNoSideScroll(page)
  const html = page.locator("html")
  const before = await html.getAttribute("data-theme")
  await page.getByRole("button", { name: /Switch to (light|dark)/ }).first().click()
  await expect(html).toHaveAttribute("data-theme", before === "light" ? "dark" : "light")
  await page.getByTestId("app-lang-switch").first().click()                  // back to Arabic, remembered
  await expect(html).toHaveAttribute("lang", "ar")
  await expect(page.getByRole("heading", { name: "بوتات التجربة" })).toBeVisible()
})

test("a page not built for the light theme stays dark", async ({ page }) => {
  await page.goto("/")
  await page.evaluate(() => localStorage.setItem("raqm-theme", "light"))
  await page.goto("/terms")
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", "light")
  await expect(page.locator("html")).toHaveAttribute("lang", "ar")
})

test("one place for keys: the old keys page is out of the menus", async ({ page }) => {
  await page.goto("/dashboard")
  await expect(page.locator('a[href="/settings/live"]').first()).toBeAttached()
  await expect(page.locator('a[href="/settings/live"]').first()).toContainText("بوتاتي على Binance (Demo)")
  await expect(page.locator('a[href="/settings/keys"]')).toHaveCount(0)        // 2026-11-04: it fed nothing
  await expect(page.getByText("مفاتيح المنصات")).toHaveCount(0)
  await page.goto("/settings/keys")                                            // an old link explains where keys are
  await expect(page.getByText("الصفحة دي اتشالت")).toBeVisible()
  await expect(page.locator("input")).toHaveCount(0)
})

test("realbot.da3m.io shows the positions, as cards on a phone", async ({ page, isMobile }) => {
  await page.goto("http://realbot.test/")
  await expect(page.getByText("AGT/USDT").first()).toBeVisible()
  await expect(page.getByText("التبديل الجاي")).toBeVisible()
  await expect(page.getByText("IDOL/USDT").first()).toBeVisible()             // closed trades
  // the summary (plan 7.1): the whole run next to the backtest, a warning while the sample is small, one row a month
  await expect(page.getByRole("heading", { name: "الملخص من أول ما اشتغل" })).toBeVisible()
  await expect(page.getByText("1 صفقة مقفولة", { exact: false })).toBeVisible()
  await expect(page.getByText("الباكتست 1.19")).toBeVisible()
  await expect(page.getByText("لسه 1 صفقة من 30", { exact: false })).toBeVisible()
  await expect(page.locator('td[data-l="الصافي $"]').first()).toContainText("+$9.96")
  await expectNoSideScroll(page)
  const header = page.locator("thead").first()
  if (isMobile) {
    await expect(header).toBeHidden()                                         // rows are cards, each value labelled
    await expect(page.locator('td[data-l="الدخول"]').first()).toBeVisible()
  } else {
    await expect(header).toBeVisible()
  }
})

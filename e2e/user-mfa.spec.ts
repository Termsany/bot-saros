import { adminTest as test, expect, ADMIN_USER, type ApiCall } from "./fixtures"

// 2FA for a user's real money (owner, 2026-11-07): the card on /settings/live. A fake Supabase and a fake API.

function jwt(aal: string){
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url")
  const exp = Math.floor(Date.now() / 1000) + 3600
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: ADMIN_USER.id, email: ADMIN_USER.email, exp, role: "authenticated", aal, amr: [{ method: "totp", timestamp: exp - 3600 }] })}.e2e`
}

const api = async (c: ApiCall) => {
  if (c.path === "/api/user/me") return { admin: false }
  if (c.path === "/api/user/keys/status") return { binance: { configured: true, paper: true } }
  if (c.path === "/api/user/live/status") return { enabled: false }
  if (c.path === "/api/user/bots") return { rules: { max_strategies: 2, strategies: ["momentum_ls"] }, desired: null, bots: {} }
  return undefined
}

test("real money: the page sets up 2FA before anything real can change", async ({ page, api: a }) => {
  a.handler = api
  const s = { factors: [] as any[], verified: 0 }
  const ok = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
  await page.route(/\/auth\/v1\/(user|factors.*)$/, async route => {
    const p = new URL(route.request().url()).pathname
    if (p.endsWith("/user")) return route.fulfill(ok({ ...ADMIN_USER, factors: s.factors }))
    if (p.endsWith("/factors")) {
      s.factors = [{ id: "f-u", factor_type: "totp", status: "unverified", friendly_name: "RAQM", created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z" }]
      return route.fulfill(ok({ id: "f-u", type: "totp", friendly_name: "RAQM", totp: { qr_code: "<svg xmlns='http://www.w3.org/2000/svg'/>", secret: "JBSWY3DPEHPK3PXP", uri: "otpauth://totp/x" } }))
    }
    if (p.endsWith("/challenge")) return route.fulfill(ok({ id: "c-1", type: "totp", expires_at: Math.floor(Date.now() / 1000) + 300 }))
    if (p.endsWith("/verify")) {
      s.verified++; s.factors = s.factors.map(f => ({ ...f, status: "verified" }))
      return route.fulfill(ok({ access_token: jwt("aal2"), refresh_token: "e2e-refresh-2", token_type: "bearer", expires_in: 3600, user: { ...ADMIN_USER, factors: s.factors } }))
    }
    return route.abort()
  })
  await page.goto("/settings/live")
  await expect(page.getByTestId("user-mfa-start")).toHaveCount(0)                 // Demo: no 2FA asked
  await page.getByTestId("money-switch").getByRole("tab").nth(1).click()
  await expect(page.getByText("مطلوب للفلوس الحقيقية")).toBeVisible()
  await page.getByTestId("user-mfa-start").click()
  await expect(page.getByTestId("user-mfa-secret")).toHaveText("JBSWY3DPEHPK3PXP")
  await page.getByTestId("user-mfa-code").fill("123456")
  await page.getByRole("button", { name: "تأكيد وتفعيل" }).click()
  await expect(page.getByText("شغّال", { exact: true })).toBeVisible()
  expect(s.verified).toBe(1)
})

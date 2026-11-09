import { adminTest as test, expect, ADMIN_USER, type ApiCall } from "./fixtures"
import type { Page } from "@playwright/test"

// 2FA for the admin (owner, 2026-11-07). A fake Supabase and a fake API — nothing reaches the real ones.

const FACTOR = { id: "f-1", factor_type: "totp", status: "verified", friendly_name: "RAQM admin", created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z" }

function jwt(aal: string){
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url")
  const exp = Math.floor(Date.now() / 1000) + 3600
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: ADMIN_USER.id, email: ADMIN_USER.email, exp, role: "authenticated", aal })}.e2e`
}

/** Supabase's MFA endpoints: the user (with or without the authenticator), enroll, challenge, verify. */
async function fakeMfa(page: Page, s: { factors: any[], verified: string[] }){
  const ok = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
  await page.route(/\/auth\/v1\/(user|factors.*)$/, async route => {
    const p = new URL(route.request().url()).pathname
    if (p.endsWith("/user")) return route.fulfill(ok({ ...ADMIN_USER, factors: s.factors }))
    if (p.endsWith("/factors")) {
      s.factors = [{ ...FACTOR, id: "f-new", status: "unverified" }]
      return route.fulfill(ok({ id: "f-new", type: "totp", friendly_name: "RAQM admin", totp: { qr_code: "<svg xmlns='http://www.w3.org/2000/svg'/>", secret: "JBSWY3DPEHPK3PXP", uri: "otpauth://totp/x" } }))
    }
    if (p.endsWith("/challenge")) return route.fulfill(ok({ id: "c-1", type: "totp", expires_at: Math.floor(Date.now() / 1000) + 300 }))
    if (p.endsWith("/verify")) {
      const code = route.request().postDataJSON().code
      if (code !== "123456") return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ code: "mfa_verification_failed", msg: "Invalid TOTP code entered" }) })
      s.verified.push(p.split("/").at(-2)!)
      s.factors = s.factors.map(f => ({ ...f, status: "verified" }))
      return route.fulfill(ok({ access_token: jwt("aal2"), refresh_token: "e2e-refresh-2", token_type: "bearer", expires_in: 3600, user: { ...ADMIN_USER, factors: s.factors } }))
    }
    return route.abort()
  })
}

function api(s: { verified: string[], enrolled: () => boolean }){
  return async (c: ApiCall) => {
    if (c.path === "/api/user/me") return { admin: true, mfa: { enrolled: s.enrolled(), aal: s.verified.length ? "aal2" : "aal1", required: false } }
    return undefined
  }
}

test("with an authenticator, the admin page asks for the code before it opens", async ({ page, api: a }) => {
  const s = { factors: [FACTOR], verified: [] as string[] }
  await fakeMfa(page, s)
  a.handler = api({ verified: s.verified, enrolled: () => true })
  await page.goto("/admin")
  await expect(page.getByTestId("mfa-gate")).toBeVisible()
  await expect(page.getByText("مركز تحكم الإدارة")).toHaveCount(0)
  await page.getByTestId("mfa-code").fill("000000")
  await page.getByRole("button", { name: "ادخل" }).click()
  await expect(page.getByText("الكود غلط أو خلص وقته")).toBeVisible()
  await page.getByTestId("mfa-code").fill("123456")
  await page.getByRole("button", { name: "ادخل" }).click()
  await expect(page.getByText("مركز تحكم الإدارة")).toBeVisible()
  expect(s.verified).toEqual(["f-1"])
})

test("without an authenticator, the admin page offers to set one up", async ({ page, api: a }) => {
  const s = { factors: [] as any[], verified: [] as string[] }
  await fakeMfa(page, s)
  a.handler = api({ verified: s.verified, enrolled: () => s.factors.some(f => f.status === "verified") })
  await page.goto("/admin")
  await expect(page.getByText("مركز تحكم الإدارة")).toBeVisible()
  await page.getByTestId("mfa-start").click()
  await expect(page.getByTestId("mfa-secret")).toHaveText("JBSWY3DPEHPK3PXP")
  await page.getByTestId("mfa-code").fill("123456")
  await page.getByRole("button", { name: "تأكيد وتفعيل" }).click()
  await expect(page.getByTestId("mfa-start")).toHaveCount(0)
  await expect(page.getByTestId("mfa-enroll")).toHaveCount(0)
  expect(s.verified).toEqual(["f-new"])
})

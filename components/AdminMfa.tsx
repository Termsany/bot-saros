"use client"
import { useState } from "react"
import { ShieldCheck } from "lucide-react"
import { supabase } from "@/lib/supabase"
import { Card, CardHeader, Pill, btn, field } from "@/components/ui"

/** 2FA for the admin (owner, 2026-11-07): Supabase TOTP. Once an authenticator is set, the API refuses every admin
 *  call from a session that didn't pass the code (app/auth.py check_admin_mfa) — these screens only ask for it. */

export type MfaState = { enrolled: boolean, aal: string, required: boolean }

const digits = (v: string) => v.replace(/\D/g, "").slice(0, 6)

async function verifiedFactor(): Promise<string | null> {
  const { data, error } = await supabase.auth.mfa.listFactors()
  if (error) throw error
  return (data?.totp || []).find((f: any) => f.status === "verified")?.id || null
}

/** The code screen before the admin page, for a session signed in with the password only. */
export function AdminMfaGate({ onPassed }: { onPassed: () => void }) {
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  async function verify(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("")
    try {
      const factorId = await verifiedFactor()
      if (!factorId) throw new Error("مفيش تطبيق متسجّل على الحساب ده")
      const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId, code })
      if (error) throw error
      onPassed()
    } catch (e: any) { setErr(/invalid|code/i.test(e?.message || "") ? "الكود غلط أو خلص وقته — جرّب الكود الجديد" : (e?.message || "ما اتأكدش")); setCode("") }
    finally { setBusy(false) }
  }
  return (
    <form onSubmit={verify} className="max-w-md rounded-2xl border border-line bg-surface p-6 text-center" data-testid="mfa-gate">
      <ShieldCheck className="mx-auto text-corona" size={28} />
      <h1 className="mt-4 text-xl font-black">اكتب كود التطبيق</h1>
      <p className="mt-2 text-sm text-muted">صفحة الإدارة محتاجة الكود اللي من 6 أرقام في تطبيق الـ 2FA (Google Authenticator أو غيره).</p>
      <input value={code} onChange={e => setCode(digits(e.target.value))} inputMode="numeric" autoComplete="one-time-code" autoFocus
        aria-label="كود التطبيق" data-testid="mfa-code" dir="ltr" className={`${field} mt-4 text-center font-mono text-lg tracking-[0.4em]`} placeholder="••••••" />
      {err && <p className="mt-2 text-[13px] text-loss">{err}</p>}
      <button type="submit" disabled={busy || code.length !== 6} className={`${btn.primary} mt-4 w-full justify-center`}>{busy ? "بيتأكد…" : "ادخل"}</button>
    </form>
  )
}

/** On the admin page: set up the authenticator, or say it's on. */
export function AdminMfaSetup({ mfa, onDone }: { mfa: MfaState, onDone: () => void }) {
  const [enroll, setEnroll] = useState<{ id: string, qr: string, secret: string } | null>(null)
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  if (mfa.enrolled) return (
    <Card>
      <CardHeader title="التحقق بخطوتين (2FA)" action={<Pill tone="profit">شغّال</Pill>}
        sub={mfa.required ? "مطلوب دايماً على حساب الإدارة" : "أي دخول للإدارة بالباسورد لوحده بيتطلب منه الكود"} />
    </Card>
  )
  async function start() {
    setBusy(true); setErr("")
    try {
      const { data: list } = await supabase.auth.mfa.listFactors()   // an earlier setup left unfinished
      for (const f of (list?.all || []).filter((f: any) => f.status === "unverified")) await supabase.auth.mfa.unenroll({ factorId: f.id })
      const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp", friendlyName: `RAQM admin ${new Date().toISOString().slice(0, 10)}` })
      if (error) throw error
      setEnroll({ id: data.id, qr: data.totp.qr_code, secret: data.totp.secret })
    } catch (e: any) { setErr(e?.message || "ما اتعملش") } finally { setBusy(false) }
  }
  async function confirm(e: React.FormEvent) {
    e.preventDefault(); if (!enroll) return
    setBusy(true); setErr("")
    try {
      const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId: enroll.id, code })
      if (error) throw error
      setEnroll(null); onDone()
    } catch (e: any) { setErr("الكود غلط أو خلص وقته — اكتب الكود الجديد من التطبيق"); setCode("") } finally { setBusy(false) }
  }
  return (
    <Card className="border-corona/45">
      <CardHeader title="التحقق بخطوتين (2FA)" action={<Pill tone="corona">مش متفعّل</Pill>}
        sub="من غيره، أي حد يعرف الباسورد يقدر يفتح الفلوس الحقيقية. بعد ما تفعّله، الإدارة بتطلب كود من التطبيق." />
      {err && <p className="mb-2 text-[13px] text-loss">{err}</p>}
      {!enroll ? (
        <button onClick={start} disabled={busy} data-testid="mfa-start" className={btn.primary}>فعّل الـ 2FA</button>
      ) : (
        <form onSubmit={confirm} className="space-y-3" data-testid="mfa-enroll">
          <p className="text-[13px] text-muted">1. افتح Google Authenticator (أو أي تطبيق 2FA) وامسح الكود ده، أو اكتب المفتاح بإيدك.</p>
          <img src={enroll.qr} alt="QR code للتطبيق" width={176} height={176} className="rounded-lg bg-white p-2" />
          <p className="font-mono text-[12px] text-faint break-all" dir="ltr" data-testid="mfa-secret">{enroll.secret}</p>
          <p className="text-[13px] text-muted">2. اكتب الكود اللي ظهر في التطبيق:</p>
          <input value={code} onChange={e => setCode(digits(e.target.value))} inputMode="numeric" autoComplete="one-time-code"
            aria-label="كود التطبيق" data-testid="mfa-code" dir="ltr" className={`${field} max-w-[200px] text-center font-mono tracking-[0.3em]`} placeholder="••••••" />
          <div className="flex gap-2">
            <button type="submit" disabled={busy || code.length !== 6} className={btn.primary}>{busy ? "بيتأكد…" : "تأكيد وتفعيل"}</button>
            <button type="button" onClick={() => setEnroll(null)} className={btn.secondary}>إلغاء</button>
          </div>
        </form>
      )}
    </Card>
  )
}

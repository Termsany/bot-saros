"use client"
import { useEffect, useState } from "react"
import { ShieldCheck } from "lucide-react"
import { supabase } from "@/lib/supabase"
import { Card, CardHeader, Pill, btn, field } from "@/components/ui"

/** 2FA for a user's real money (owner, 2026-11-07). The API refuses real-money changes from a session that didn't pass
 *  the code (app/auth.py check_real_money_mfa); this card sets the authenticator up, or asks for the code once per
 *  sign-in. Turning a bot off never needs it. */

const T = {
  ar: {
    title: "التحقق بخطوتين (2FA)", on: "شغّال", off: "مطلوب للفلوس الحقيقية", need: "محتاج الكود",
    sub: "الفلوس الحقيقية محتاجة كود من تطبيق على موبايلك (Google Authenticator أو غيره)، علشان اللي يعرف الباسورد بس ما يقدرش يغيّر مفاتيحك أو أرقامك.",
    subOn: "الجلسة دي عدّت الكود. الإيقاف عمره ما بيحتاج كود.",
    subNeed: "اكتب الكود اللي من 6 أرقام في التطبيق علشان تقدر تغيّر حاجة في الفلوس الحقيقية.",
    start: "فعّل الـ 2FA", scan: "1. امسح الكود ده بالتطبيق، أو اكتب المفتاح بإيدك. احفظ المفتاح في مكان آمن.",
    type: "2. اكتب الكود اللي ظهر في التطبيق:", confirm: "تأكيد وتفعيل", cancel: "إلغاء", enter: "تأكيد الكود", checking: "بيتأكد…",
    bad: "الكود غلط أو خلص وقته — اكتب الكود الجديد", failed: "ما اتعملش", code: "كود التطبيق",
  },
  en: {
    title: "Two-step verification (2FA)", on: "On", off: "Needed for real money", need: "Code needed",
    sub: "Real money needs a code from an app on your phone (Google Authenticator or similar), so someone with only your password can't change your keys or numbers.",
    subOn: "This session passed the code. Stopping never needs one.",
    subNeed: "Enter the 6-digit code from the app to change anything about real money.",
    start: "Turn on 2FA", scan: "1. Scan this with the app, or type the key in. Keep the key somewhere safe.",
    type: "2. Type the code the app shows:", confirm: "Confirm and turn on", cancel: "Cancel", enter: "Confirm code", checking: "Checking…",
    bad: "Wrong or expired code — type the new one", failed: "Didn't work", code: "App code",
  },
}

const digits = (v: string) => v.replace(/\D/g, "").slice(0, 6)

export function UserMfa({ locale = "ar" }: { locale?: "ar" | "en" | string }) {
  const t = T[locale === "en" ? "en" : "ar"]
  const [lvl, setLvl] = useState<{ current: string, next: string } | null>(null)
  const [enroll, setEnroll] = useState<{ id: string, qr: string, secret: string } | null>(null)
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const load = async () => {
    if (!supabase) return
    const { data } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    if (data) setLvl({ current: data.currentLevel || "aal1", next: data.nextLevel || "aal1" })
  }
  useEffect(() => { void load() }, [])
  if (!lvl) return null
  const enrolled = lvl.next === "aal2", passed = lvl.current === "aal2"

  async function start() {
    setBusy(true); setErr("")
    try {
      const { data: list } = await supabase.auth.mfa.listFactors()        // an earlier setup left unfinished
      for (const f of (list?.all || []).filter((f: any) => f.status === "unverified")) await supabase.auth.mfa.unenroll({ factorId: f.id })
      const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp", friendlyName: `RAQM ${new Date().toISOString().slice(0, 10)}` })
      if (error) throw error
      setEnroll({ id: data.id, qr: data.totp.qr_code, secret: data.totp.secret })
    } catch (e: any) { setErr(e?.message || t.failed) } finally { setBusy(false) }
  }
  async function verify(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("")
    try {
      let factorId = enroll?.id
      if (!factorId) {
        const { data, error } = await supabase.auth.mfa.listFactors()
        if (error) throw error
        factorId = data?.totp?.[0]?.id
      }
      if (!factorId) throw new Error(t.failed)
      const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId, code })
      if (error) throw error
      setEnroll(null); setCode(""); await load()
    } catch { setErr(t.bad); setCode("") } finally { setBusy(false) }
  }
  const codeInput = (
    <input value={code} onChange={e => setCode(digits(e.target.value))} inputMode="numeric" autoComplete="one-time-code"
      aria-label={t.code} data-testid="user-mfa-code" dir="ltr" className={`${field} max-w-[200px] text-center font-mono tracking-[0.3em]`} placeholder="••••••" />
  )
  return (
    <Card className={passed ? "border-profit/40" : "border-loss/40"}>
      <CardHeader title={<span className="inline-flex items-center gap-2"><ShieldCheck size={16} className={passed ? "text-profit" : "text-loss"} />{t.title}</span>}
        action={<Pill tone={passed ? "profit" : enrolled ? "corona" : "loss"}>{passed ? t.on : enrolled ? t.need : t.off}</Pill>}
        sub={passed ? t.subOn : enrolled ? t.subNeed : t.sub} />
      {err && <p className="mb-2 text-[13px] text-loss">{err}</p>}
      {passed ? null : enrolled ? (
        <form onSubmit={verify} className="flex flex-wrap items-center gap-2" data-testid="user-mfa-gate">
          {codeInput}
          <button type="submit" disabled={busy || code.length !== 6} className={btn.primary}>{busy ? t.checking : t.enter}</button>
        </form>
      ) : !enroll ? (
        <button onClick={start} disabled={busy} data-testid="user-mfa-start" className={btn.primary}>{t.start}</button>
      ) : (
        <form onSubmit={verify} className="space-y-3" data-testid="user-mfa-enroll">
          <p className="text-[13px] text-muted">{t.scan}</p>
          <img src={enroll.qr} alt="QR" width={176} height={176} className="rounded-lg bg-white p-2" />
          <p className="break-all font-mono text-[12px] text-faint" dir="ltr" data-testid="user-mfa-secret">{enroll.secret}</p>
          <p className="text-[13px] text-muted">{t.type}</p>
          {codeInput}
          <div className="flex gap-2">
            <button type="submit" disabled={busy || code.length !== 6} className={btn.primary}>{busy ? t.checking : t.confirm}</button>
            <button type="button" onClick={() => setEnroll(null)} className={btn.secondary}>{t.cancel}</button>
          </div>
        </form>
      )}
    </Card>
  )
}

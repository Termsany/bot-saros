"use client"

import { useEffect, useState } from "react"
import { LIVE_BOTS } from "@/lib/strategies"
import { Logo } from "@/components/Logo"
import { supabase, isSupabaseConfigured } from "@/lib/supabase"

type AuthMode = "login" | "signup" | "reset" | "recovery"

const SAFE_AUTH_MESSAGE = "تعذر إتمام العملية الآن. راجع البيانات وحاول مرة أخرى."
const SAFE_CONFIG_MESSAGE = "الخدمة غير متاحة مؤقتًا. حاول مرة أخرى لاحقًا."

/** Where to go after signing in: ?next=, a path on this site only (an invitation page, say) — never another origin. */
function nextPath(): string | null {
  const next = new URLSearchParams(window.location.search).get("next") || ""
  return /^\/(?!\/)[A-Za-z0-9/_-]*$/.test(next) ? next : null
}

function safeAuthMessage(mode: AuthMode) {
  if (mode === "signup") return "تعذر إنشاء الحساب. راجع البيانات وحاول مرة أخرى."
  if (mode === "reset") return "تعذر إرسال رابط الاستعادة. راجع البريد وحاول مرة أخرى."
  if (mode === "recovery") return "تعذر تحديث كلمة المرور. حاول مرة أخرى عبر رابط استعادة جديد."
  return SAFE_AUTH_MESSAGE
}

export default function AuthPage() {
  const [mode, setMode] = useState<AuthMode>("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [msg, setMsg] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // SECURITY: recovery mode must never be derived from a hand-parsed URL
    // query/hash string (e.g. "?type=recovery") — that value is fully
    // attacker-controlled and can be used to trick an already-logged-in
    // victim into resubmitting their password via updateUser() with no
    // genuine recovery session behind it. supabase-js already parses the
    // real recovery hash tokens itself (detectSessionInUrl) and emits the
    // PASSWORD_RECOVERY auth event only when it establishes a verified
    // recovery session, so that event is the sole trigger for recovery UI.
    // an invitation link sends people here with their email and the page to come back to
    const q = new URLSearchParams(window.location.search)
    if (q.get("email")) setEmail(q.get("email") || "")
    if (q.get("mode") === "signup") setMode("signup")
    if (!supabase || !isSupabaseConfigured) return

    const { data } = supabase.auth.onAuthStateChange((event: string) => {
      if (event === "PASSWORD_RECOVERY") setMode("recovery")
      // signed in by the email-confirmation link that carried ?next=
      else if (event === "SIGNED_IN" && nextPath()) window.location.assign(nextPath()!)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  function changeMode(next: AuthMode) {
    setMode(next)
    setMsg("")
  }

  async function submit() {
    if (mode === "recovery" && (!newPassword || !confirmPassword)) {
      setMsg("أدخل كلمة المرور الجديدة وتأكيدها.")
      return
    }
    if (mode === "recovery" && newPassword !== confirmPassword) {
      setMsg("كلمتا المرور غير متطابقتين.")
      return
    }
    if (mode === "recovery" && newPassword.length < 8) {
      setMsg("يجب أن تتكون كلمة المرور الجديدة من 8 أحرف على الأقل.")
      return
    }
    if ((mode === "reset" && !email.trim()) || (mode !== "reset" && mode !== "recovery" && (!email.trim() || !password))) {
      setMsg("أدخل البريد وكلمة المرور المطلوبة.")
      return
    }
    if (!isSupabaseConfigured || !supabase) {
      setMsg(SAFE_CONFIG_MESSAGE)
      return
    }

    setLoading(true)
    setMsg("")
    try {
      if (mode === "recovery") {
        const { error } = await supabase.auth.updateUser({ password: newPassword })
        if (error) throw error
        window.history.replaceState({}, document.title, `${window.location.origin}/auth`)
        setMsg("تم تحديث كلمة المرور بنجاح. يمكنك تسجيل الدخول الآن.")
        window.setTimeout(() => window.location.assign("/auth"), 800)
      } else if (mode === "reset") {
        const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
          redirectTo: `${window.location.origin}/auth`,
        })
        if (error) throw error
        setMsg("تم إرسال رابط استعادة كلمة المرور إلى بريدك.")
      } else if (mode === "signup") {
        const next = nextPath()
        const { error } = await supabase.auth.signUp({ email: email.trim(), password,
          ...(next ? { options: { emailRedirectTo: `${window.location.origin}/auth?next=${encodeURIComponent(next)}` } } : {}) })
        if (error) throw error
        setMsg("تم إنشاء الحساب. تفقد بريدك الإلكتروني للتأكيد.")
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
        if (error) throw error
        setMsg("تم تسجيل الدخول ✅")
        window.setTimeout(() => window.location.assign(nextPath() || "/"), 800)
      }
    } catch {
      setMsg(safeAuthMessage(mode))
    } finally {
      setLoading(false)
    }
  }

  const title = mode === "login" ? "أهلاً بيك تاني" : mode === "signup" ? "اعمل حسابك" : mode === "recovery" ? "كلمة سر جديدة" : "استعادة كلمة السر"
  const sub = mode === "login" ? "ادخل عشان تشوف بوتاتك وصفقاتك" : mode === "signup" ? "ابدأ مجانًا بفلوس وهمية" : mode === "recovery" ? "اختار كلمة سر جديدة لحسابك" : "هنبعتلك رابط على بريدك"
  const action = mode === "login" ? "دخول" : mode === "signup" ? "اعمل الحساب" : mode === "recovery" ? "حدّث كلمة السر" : "ابعت الرابط"
  const input = "w-full rounded-xl border border-line bg-void px-3.5 py-2.5 text-sm outline-none transition focus:border-corona/60"

  return (
    <div dir="rtl" className="grid min-h-screen bg-void text-ink lg:grid-cols-2">
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-[400px] space-y-5">
          <a href="/" className="inline-flex"><Logo size="sm" /></a>
          <div>
            <h1 className="text-[32px] font-extrabold leading-tight">{title}</h1>
            <p className="mt-1 text-[13px] text-muted">{sub}</p>
          </div>
          {mode !== "recovery" && <div className="flex gap-1 rounded-xl border border-line bg-surface p-1">
            {(["login", "signup"] as const).map(m => (
              <button key={m} onClick={() => changeMode(m)} className={`flex-1 rounded-[9px] py-2 text-sm transition ${mode === m || (m === "login" && mode === "reset") ? "bg-surface2 font-semibold text-ink" : "text-muted hover:text-ink"}`}>{m === "login" ? "دخول" : "حساب جديد"}</button>
            ))}
          </div>}
          {mode !== "recovery" && <label className="block"><span className="mb-1.5 block text-[12px] font-semibold text-muted">البريد الإلكتروني</span>
            <input dir="ltr" value={email} onChange={e => setEmail(e.target.value)} type="email" autoComplete="email" placeholder="name@example.com" className={input} /></label>}
          {mode === "recovery" ? <>
            <label className="block"><span className="mb-1.5 block text-[12px] font-semibold text-muted">كلمة السر الجديدة</span>
              <input dir="ltr" value={newPassword} onChange={e => setNewPassword(e.target.value)} type="password" autoComplete="new-password" className={input} /></label>
            <label className="block"><span className="mb-1.5 block text-[12px] font-semibold text-muted">أكّد كلمة السر</span>
              <input dir="ltr" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} type="password" autoComplete="new-password" className={input} /></label>
          </> : mode !== "reset" && <label className="block"><span className="mb-1.5 block text-[12px] font-semibold text-muted">كلمة السر</span>
            <input dir="ltr" value={password} onChange={e => setPassword(e.target.value)} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} className={input} /></label>}
          {mode === "login" && <button onClick={() => changeMode("reset")} className="text-[13px] text-corona">نسيت كلمة السر؟</button>}
          {(mode === "reset" || mode === "recovery") && <button onClick={() => changeMode("login")} className="text-[13px] text-muted hover:text-ink">← ارجع لتسجيل الدخول</button>}
          <button onClick={submit} disabled={loading} className="w-full rounded-xl bg-corona py-3 text-sm font-semibold text-void transition hover:bg-corona-soft disabled:opacity-50">{loading ? "لحظة…" : action}</button>
          {msg && <div role="status" aria-live="polite" className="rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[13px] text-ink">{msg}</div>}
          <p className="text-center text-[12px] leading-5 text-faint">بالدخول انت موافق على الشروط وسياسة الخصوصية. التداول بالرافعة فيه مخاطرة عالية.</p>
        </div>
      </div>

      <aside className="hidden flex-col justify-center gap-7 overflow-hidden border-r border-line bg-surface px-16 py-16 lg:flex">
        <span className="self-start rounded-full border border-corona/40 bg-corona/10 px-3 py-0.5 text-[12px] font-semibold text-corona">Demo شغال 24/7 على Binance</span>
        <h2 className="text-[56px] font-black leading-[1.12] tracking-tight">تداول بالأرقام،<br/>مش بالإحساس.</h2>
        <p className="max-w-[520px] text-[15px] leading-7 text-muted">{LIVE_BOTS.length} استراتيجيات اتجربت على كل عقود Binance من 2019، بالرسوم والـ funding الحقيقي. وكل صفقة بتوصلك على تليجرام.</p>
        <div className="flex gap-10">
          {[["24/7", "مراقبة"], [String(LIVE_BOTS.length), "استراتيجيات"], ["2019", "داتا من سنة"]].map(([v, l]) => (
            <div key={l}><div className="font-mono text-[22px] font-bold text-corona">{v}</div><div className="text-[12px] text-muted">{l}</div></div>
          ))}
        </div>
        <div className="max-w-[460px] rounded-[18px] border border-line bg-void p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2"><span className="text-[28px] font-extrabold">AIN</span><span className="rounded-full border border-profit/40 bg-profit/10 px-2 py-0.5 text-[11px] font-semibold text-profit">LONG x2</span></div>
            <span className="text-[11px] text-faint">مثال على تنبيه تليجرام</span>
          </div>
          <div className="mt-2 font-mono text-[34px] font-bold text-profit" dir="ltr" style={{ textAlign: "right" }}>+$153.20</div>
          <div className="mt-2 flex gap-6 text-[12px]">
            {[["الدخول", "0.14394"], ["الخروج", "0.25483"], ["المدة", "7d"]].map(([l, v]) => <div key={l}><div className="text-faint">{l}</div><div className="font-mono">{v}</div></div>)}
          </div>
        </div>
      </aside>
    </div>
  )
}

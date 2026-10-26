"use client"

import { useState } from "react"
import { BRAND } from "@/lib/brand"
import { Logo } from "@/components/Logo"
import { supabase, isSupabaseConfigured } from "@/lib/supabase"

type AuthMode = "login" | "signup" | "reset"

const SAFE_AUTH_MESSAGE = "تعذر إتمام العملية الآن. راجع البيانات وحاول مرة أخرى."
const SAFE_CONFIG_MESSAGE = "الخدمة غير متاحة مؤقتًا. حاول مرة أخرى لاحقًا."

function safeAuthMessage(mode: AuthMode) {
  if (mode === "signup") return "تعذر إنشاء الحساب. راجع البيانات وحاول مرة أخرى."
  if (mode === "reset") return "تعذر إرسال رابط الاستعادة. راجع البريد وحاول مرة أخرى."
  return SAFE_AUTH_MESSAGE
}

export default function AuthPage() {
  const [mode, setMode] = useState<AuthMode>("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [msg, setMsg] = useState("")
  const [loading, setLoading] = useState(false)

  function changeMode(next: AuthMode) {
    setMode(next)
    setMsg("")
  }

  async function submit() {
    if (!isSupabaseConfigured || !supabase) {
      setMsg(SAFE_CONFIG_MESSAGE)
      return
    }
    if (!email.trim() || (mode !== "reset" && !password)) {
      setMsg("أدخل البريد وكلمة المرور المطلوبة.")
      return
    }

    setLoading(true)
    setMsg("")
    try {
      if (mode === "reset") {
        const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
          redirectTo: `${window.location.origin}/auth`,
        })
        if (error) throw error
        setMsg("تم إرسال رابط استعادة كلمة المرور إلى بريدك.")
      } else if (mode === "signup") {
        const { error } = await supabase.auth.signUp({ email: email.trim(), password })
        if (error) throw error
        setMsg("تم إنشاء الحساب. تفقد بريدك الإلكتروني للتأكيد.")
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
        if (error) throw error
        setMsg("تم تسجيل الدخول ✅")
        window.setTimeout(() => window.location.assign("/"), 800)
      }
    } catch {
      setMsg(safeAuthMessage(mode))
    } finally {
      setLoading(false)
    }
  }

  const title = mode === "login" ? "تسجيل دخول" : mode === "signup" ? "إنشاء حساب" : "استعادة كلمة المرور"
  const action = mode === "login" ? "دخول" : mode === "signup" ? "إنشاء" : "إرسال الرابط"

  return (
    <div dir="rtl" className="min-h-screen bg-void text-ink grid place-items-center p-4">
      <div className="w-full max-w-[360px] rounded-2xl border border-line bg-surface p-6 shadow-xl shadow-black/30">
        <div className="flex justify-center mb-3"><Logo size="lg" /></div>
        <h1 className="text-base font-black text-center">{BRAND.nameAr} {BRAND.name} — {title}</h1>
        <p className="text-xs text-muted mt-1 text-center">دخول آمن إلى حسابك</p>
        <div className="flex gap-2 mt-3">
          <button onClick={() => changeMode("login")} className={`flex-1 py-1.5 rounded-xl text-xs font-bold ${mode === "login" ? "bg-corona text-void" : "bg-surface2 border border-line"}`}>دخول</button>
          <button onClick={() => changeMode("signup")} className={`flex-1 py-1.5 rounded-xl text-xs font-bold ${mode === "signup" ? "bg-corona text-void" : "bg-surface2 border border-line"}`}>حساب جديد</button>
        </div>
        <input dir="ltr" value={email} onChange={e => setEmail(e.target.value)} type="email" autoComplete="email" placeholder="البريد الإلكتروني" className="w-full mt-3 bg-surface border border-line rounded-xl px-3 py-2 text-sm" />
        {mode !== "reset" && <input dir="ltr" value={password} onChange={e => setPassword(e.target.value)} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="كلمة المرور" className="w-full mt-2 bg-surface border border-line rounded-xl px-3 py-2 text-sm" />}
        <button onClick={submit} disabled={loading} className="w-full mt-3 py-2 rounded-xl bg-corona text-void text-sm font-bold disabled:opacity-50">{loading ? "جاري..." : action}</button>
        {mode === "login" && <button onClick={() => changeMode("reset")} className="w-full mt-2 text-xs text-muted">نسيت كلمة المرور؟</button>}
        {mode === "reset" && <button onClick={() => changeMode("login")} className="w-full mt-2 text-xs text-muted">العودة لتسجيل الدخول</button>}
        {msg && <div role="status" aria-live="polite" className="mt-2 text-xs text-umbra bg-surface2 border border-line rounded-xl px-3 py-2">{msg}</div>}
        <a href="/" className="block text-center text-xs text-muted mt-3">العودة للرئيسية</a>
      </div>
    </div>
  )
}

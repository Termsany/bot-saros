"use client"
import { useState } from "react"
import { Logo } from "@/components/Logo"
import { supabase, isSupabaseConfigured } from "@/lib/supabase"

export default function AuthPage(){
  const [mode, setMode] = useState<"login"|"signup">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [msg, setMsg] = useState("")
  const [loading, setLoading] = useState(false)

  async function submit(){
    if(!isSupabaseConfigured){ setMsg("Supabase غير مربوط"); return }
    setLoading(true); setMsg("")
    try{
      if(mode==="signup"){
        const { error } = await supabase.auth.signUp({ email, password })
        if(error) throw error
        setMsg("تم إنشاء الحساب — تفقد الإيميل للتأكيد")
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if(error) throw error
        setMsg("تم تسجيل الدخول ✅")
        setTimeout(()=> location.href="/", 800)
      }
    }catch(e:any){ setMsg(e.message||"خطأ") }
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-[#070B12] text-[#E6EEF8] grid place-items-center p-4">
      <div className="w-full max-w-[360px] rounded-2xl border border-[#1c2632] bg-[#0c131c] p-6 shadow-xl shadow-black/30">
        <div className="flex justify-center mb-3"><Logo size="lg" /></div>
        <h1 className="text-base font-black text-center">Bot Saros — {mode==="login"?"تسجيل دخول":"إنشاء حساب"}</h1>
        <p className="text-xs text-[#8A9AB0] mt-1">Supabase Auth — مربوط على https://peefsudacgowngwvnouk.supabase.co</p>
        <div className="flex gap-2 mt-3">
          <button onClick={()=>setMode("login")} className={`flex-1 py-1.5 rounded-xl text-xs font-bold ${mode==="login"?"bg-[#00D395] text-[#062016]":"bg-[#1A2332] border border-[#1E2A3A]"}`}>دخول</button>
          <button onClick={()=>setMode("signup")} className={`flex-1 py-1.5 rounded-xl text-xs font-bold ${mode==="signup"?"bg-[#00D395] text-[#062016]":"bg-[#1A2332] border border-[#1E2A3A]"}`}>حساب جديد</button>
        </div>
        <input value={email} onChange={e=>setEmail(e.target.value)} placeholder="الإيميل" className="w-full mt-3 bg-[#0E141D] border border-[#1E2A3A] rounded-xl px-3 py-2 text-sm" />
        <input value={password} onChange={e=>setPassword(e.target.value)} type="password" placeholder="كلمة المرور" className="w-full mt-2 bg-[#0E141D] border border-[#1E2A3A] rounded-xl px-3 py-2 text-sm" />
        <button onClick={submit} disabled={loading} className="w-full mt-3 py-2 rounded-xl bg-[#00D395] text-[#062016] text-sm font-bold disabled:opacity-50">{loading?"جاري...":mode==="login"?"دخول":"إنشاء"}</button>
        {msg && <div className="mt-2 text-xs text-[#C27AFF] bg-[#1A2332] border border-[#1E2A3A] rounded-xl px-3 py-2">{msg}</div>}
        <a href="/" className="block text-center text-xs text-[#8A9AB0] mt-3">العودة للرئيسية</a>
      </div>
    </div>
  )
}

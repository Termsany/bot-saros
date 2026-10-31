"use client"
import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { Check, Gift, Link2, Timer } from "lucide-react"
import { Logo } from "@/components/Logo"
import { btn } from "@/components/ui"
import { signOut, useAccount } from "@/components/AccountMenu"
import { authHeaders } from "@/lib/supabase"

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const NAME: Record<string, string> = { starter: "Starter", pro: "Pro", elite: "Elite" }
const ICON = { gift: Gift, trial: Timer, paid: Link2 }

type Invite = { state: string, tier: string, kind: "gift" | "trial" | "paid", days: number | null, price_usd: number, email_hint: string, offer: string }

/** An invitation link: what it offers, then sign in (or sign up) with the invited email and take it —
 *  a gift turns on at once, a trial or a paid plan goes to Stripe. */
export default function InvitePage(){
  const { token } = useParams<{ token: string }>()
  const acc = useAccount()
  const [inv, setInv] = useState<Invite | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [done, setDone] = useState<{ tier: string, expires_at: string } | null>(null)

  useEffect(() => {
    fetch(`${API}/api/invites/${encodeURIComponent(token)}`, { cache: "no-store" })
      .then(r => r.ok ? r.json() : null).then(setInv).catch(() => setInv(null))
  }, [token])

  const here = `/invite/${token}`
  const emailOk = acc.state === "in" && inv && acc.email[0]?.toLowerCase() === inv.email_hint[0] && acc.email.toLowerCase().endsWith(inv.email_hint.split("@")[1])

  async function take(){
    if (!inv) return
    setBusy(true); setErr("")
    try {
      const h = await authHeaders({ "Content-Type": "application/json" })
      if (inv.kind === "gift") {
        const r = await fetch(`${API}/api/invites/${token}/accept`, { method: "POST", headers: h })
        const j = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(r.status === 403 ? "الدعوة دي لإيميل تاني، أو لسه ما أكدتش إيميلك" : r.status === 409 ? "الدعوة دي مابقتش شغالة" : "حصلت مشكلة — حاول تاني")
        setDone({ tier: j.tier, expires_at: j.expires_at })
      } else {
        const r = await fetch("/api/stripe/checkout", { method: "POST", headers: h, body: JSON.stringify({ invite: token }) })
        const j = await r.json().catch(() => ({}))
        if (j.url) { window.location.href = j.url; return }
        throw new Error(j.error || "تعذر فتح صفحة الدفع")
      }
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  const Icon = inv ? ICON[inv.kind] : Gift
  const cta = inv?.kind === "gift" ? "فعّل الباقة" : inv?.kind === "trial" ? "ابدأ التجربة المجانية" : "اشترك دلوقتي"

  return (
    <main dir="rtl" className="grid min-h-screen place-items-center bg-void px-4 py-10 text-ink">
      <div className="w-full max-w-[460px] space-y-5">
        <a href="/" className="inline-flex"><Logo size="sm"/></a>
        <section className="rounded-2xl border border-line bg-surface p-6">
          {inv === undefined ? <p className="py-10 text-center text-[14px] text-faint">بيحمّل…</p>
          : inv === null ? <>
              <h1 className="text-[24px] font-extrabold">الدعوة مش موجودة</h1>
              <p className="mt-2 text-[14px] text-muted">اتأكد إن الرابط كامل، أو اطلب دعوة جديدة.</p>
              <a href="/" className={`${btn.secondary} mt-5 w-full`}>الصفحة الرئيسية</a>
            </>
          : done ? <>
              <span className="grid h-12 w-12 place-items-center rounded-full bg-profit/15 text-profit"><Check size={24}/></span>
              <h1 className="mt-4 text-[24px] font-extrabold">باقة {NAME[done.tier] || done.tier} شغالة</h1>
              <p className="mt-2 text-[14px] text-muted">لحد {new Date(done.expires_at).toLocaleDateString("ar-EG", { day: "numeric", month: "long", year: "numeric" })}. بعدها حسابك بيرجع للباقة المجانية لوحده.</p>
              <a href="/dashboard" className={`${btn.primary} mt-5 w-full`}>افتح لوحة التحكم</a>
            </>
          : <>
              <span className="grid h-12 w-12 place-items-center rounded-xl bg-corona/15 text-corona"><Icon size={24}/></span>
              <p className="mt-4 text-[13px] font-semibold text-corona">اتدعيت لمنصة رقم</p>
              <h1 className="mt-1 text-[26px] font-extrabold leading-snug">{inv.offer}</h1>
              <p className="mt-2 text-[14px] leading-7 text-muted">
                {inv.kind === "gift" ? "من غير دفع ومن غير كارت. لما المدة تخلص حسابك بيرجع للباقة المجانية لوحده."
                  : inv.kind === "trial" ? `هتدخل بيانات الكارت على Stripe، ومش هيتخصم منك حاجة قبل ${inv.days} يوم. تقدر تلغي قبلها.`
                  : "الدفع على Stripe، والاشتراك شهري وتقدر تلغيه في أي وقت."}
              </p>
              <div className="mt-4 rounded-xl bg-surface2 px-3.5 py-2.5 text-[13px] text-muted">الدعوة للإيميل <b className="font-mono text-ink" dir="ltr">{inv.email_hint}</b></div>

              {inv.state !== "pending" ? (
                <div className="mt-5 rounded-xl border border-line bg-surface2 px-4 py-3 text-[14px] text-muted">
                  {inv.state === "accepted" ? "الدعوة دي اتقبلت بالفعل." : inv.state === "revoked" ? "الدعوة دي اتلغت." : "الرابط ده خلص. اطلب دعوة جديدة."}
                </div>
              ) : acc.state === "loading" ? null
              : acc.state === "out" ? (
                <div className="mt-5 space-y-2">
                  <a href={`/auth?mode=signup&next=${encodeURIComponent(here)}`} className={`${btn.primary} w-full`}>اعمل حساب بالإيميل ده</a>
                  <a href={`/auth?next=${encodeURIComponent(here)}`} className={`${btn.secondary} w-full`}>عندي حساب — دخول</a>
                </div>
              ) : !emailOk ? (
                <div className="mt-5 space-y-3">
                  <div className="rounded-xl border border-corona/30 bg-corona/10 px-4 py-3 text-[13px] text-corona">انت داخل بـ <b dir="ltr">{acc.email}</b>، والدعوة لإيميل تاني. اخرج وادخل بالإيميل المدعو.</div>
                  <button onClick={signOut} className={`${btn.secondary} w-full`}>تسجيل الخروج</button>
                </div>
              ) : (
                <div className="mt-5">
                  <button onClick={take} disabled={busy} className={`${btn.primary} w-full py-3`}>{busy ? "لحظة…" : cta}</button>
                  <p className="mt-2 text-center text-[12px] text-faint">داخل بـ <span dir="ltr">{acc.email}</span></p>
                </div>
              )}
              {err && <div className="mt-3 rounded-xl border border-loss/30 bg-loss/10 px-4 py-3 text-[13px] text-loss">{err}</div>}
            </>}
        </section>
        <p className="text-center text-[12px] leading-5 text-faint">التداول بالرافعة فيه مخاطرة عالية، والأداء السابق مش ضمان للنتايج.</p>
      </div>
    </main>
  )
}

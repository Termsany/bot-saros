"use client"
import { useEffect, useRef, useState } from "react"
import { Bot, ChevronDown, KeyRound, LayoutDashboard, LogOut, ShieldCheck } from "lucide-react"
import { Pill } from "@/components/ui"
import { apiIsAdmin } from "@/lib/api"
import { getMyTier, supabase } from "@/lib/supabase"

export type Account = { state: "loading" | "out" | "in", email: string, tier: string, isAdmin: boolean }

/** Who is signed in, kept current when they sign in or out in another tab. */
export function useAccount(): Account {
  const [acc, setAcc] = useState<Account>({ state: "loading", email: "", tier: "free", isAdmin: false })
  useEffect(() => {
    if (!supabase) { setAcc(a => ({ ...a, state: "out" })); return }
    let live = true
    const fill = async (email: string | undefined) => {
      if (!email) { if (live) setAcc({ state: "out", email: "", tier: "free", isAdmin: false }); return }
      if (live) setAcc(a => ({ ...a, state: "in", email }))
      const [tier, isAdmin] = await Promise.all([getMyTier().catch(() => "free"), apiIsAdmin()])
      if (live) setAcc({ state: "in", email, tier, isAdmin })
    }
    supabase.auth.getSession().then(({ data }: any) => fill(data.session?.user?.email))
    const { data } = supabase.auth.onAuthStateChange((_event: string, session: any) => { fill(session?.user?.email) })
    return () => { live = false; data.subscription.unsubscribe() }
  }, [])
  return acc
}

export async function signOut(){
  try { await supabase?.auth.signOut() } finally { window.location.href = "/" }
}

/** Avatar button + menu: the account's email and plan, the main account pages, and sign out. */
export function AccountMenu({ email, tier, isAdmin, compact = false }: { email: string, tier: string, isAdmin: boolean, compact?: boolean }){
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", onDown); document.addEventListener("keydown", onKey)
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey) }
  }, [open])
  const initial = (email.trim()[0] || "?").toUpperCase()
  const links = [
    { href: "/dashboard", label: "لوحة التحكم", icon: LayoutDashboard },
    { href: "/settings/keys", label: "مفاتيح المنصات", icon: KeyRound },
    { href: "/settings/live", label: "التداول الحقيقي", icon: Bot },
    ...(isAdmin ? [{ href: "/admin", label: "الإدارة", icon: ShieldCheck }] : []),
  ]
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(o => !o)} aria-expanded={open} aria-haspopup="menu" aria-label="حسابك"
        className="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-2.5 pr-1 text-sm transition hover:border-corona/40">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-corona/15 font-mono text-[13px] font-bold text-corona">{initial}</span>
        {!compact && <span className="hidden max-w-[160px] truncate text-[13px] text-muted md:block" dir="ltr">{email}</span>}
        <ChevronDown size={14} className={`text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div role="menu" className="absolute left-0 top-full z-40 mt-2 w-64 rounded-2xl border border-line bg-surface p-1.5 shadow-2xl">
          <div className="flex items-center gap-2.5 rounded-xl bg-surface2 px-3 py-2.5">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-corona/15 font-mono text-[14px] font-bold text-corona">{initial}</span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold" dir="ltr" style={{ textAlign: "right" }}>{email}</div>
              <Pill tone="corona" className="mt-1"><span className="font-mono uppercase">{tier}</span></Pill>
            </div>
          </div>
          <div className="my-1.5 space-y-0.5">
            {links.map(({ href, label, icon: Icon }) => (
              <a key={href} href={href} role="menuitem" className="flex items-center gap-2.5 rounded-[10px] px-3 py-2 text-[14px] text-muted transition hover:bg-surface2 hover:text-ink">
                <Icon size={17} strokeWidth={1.8} />{label}
              </a>
            ))}
          </div>
          <div className="border-t border-line pt-1.5">
            <button onClick={signOut} role="menuitem" className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2 text-[14px] text-loss transition hover:bg-loss/10">
              <LogOut size={17} strokeWidth={1.8} />تسجيل الخروج
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** The landing header's end: "دخول" + "افتح المنصة" for visitors; "لوحة التحكم" + the account menu once signed in. */
export function LandingNavAuth(){
  const acc = useAccount()
  if (acc.state === "loading") return <span className="h-9 w-[132px]" aria-hidden />
  if (acc.state === "out") return <>
    <a href="/auth" className="hidden px-3 text-sm text-muted hover:text-ink sm:block">دخول</a>
    <a href="/dashboard" className="rounded-xl bg-corona px-4 py-2 text-sm font-bold text-void transition hover:bg-corona-soft">افتح المنصة</a>
  </>
  return <>
    <a href="/dashboard" className="hidden rounded-xl bg-corona px-4 py-2 text-sm font-bold text-void transition hover:bg-corona-soft sm:block">لوحة التحكم</a>
    <span className="w-1.5" />
    <AccountMenu email={acc.email} tier={acc.tier} isAdmin={acc.isAdmin} />
  </>
}

/** Footer link: "دخول" for visitors, "لوحة التحكم" once signed in. */
export function FooterAuthLink(){
  const acc = useAccount()
  return acc.state === "in" ? <a href="/dashboard" className="hover:text-ink">لوحة التحكم</a> : <a href="/auth" className="hover:text-ink">دخول</a>
}

"use client"
import { useEffect, useState } from "react"
import { BRAND } from "@/lib/brand"
import { Logo } from "@/components/Logo"
import { Pill } from "@/components/ui"
import { AccountMenu, signOut } from "@/components/AccountMenu"
import { apiIsAdmin } from "@/lib/api"
import { getMyPlan, getUser, type MyPlan } from "@/lib/supabase"
import { Activity, Bot, CandlestickChart, House, KeyRound, LayoutDashboard, LogOut, ShieldCheck, Sparkles } from "lucide-react"

type NavItem = { href: string, label: string, icon: typeof House, adminOnly?: boolean }
const GROUPS: { label: string, items: NavItem[] }[] = [
  { label: "التداول", items: [
    { href: "/dashboard", label: "لوحة التحكم", icon: LayoutDashboard },
    { href: "/dashboard#live-bots", label: "البوتات مباشر", icon: Activity },
    { href: "/backtest", label: "Backtest", icon: CandlestickChart },
    { href: "/llm-lab", label: "مختبر AI", icon: Sparkles },
  ] },
  { label: "الحساب", items: [
    { href: "/settings/keys", label: "مفاتيح المنصات", icon: KeyRound },
    { href: "/settings/live", label: "التداول الحقيقي", icon: Bot },
    { href: "/admin", label: "الإدارة", icon: ShieldCheck, adminOnly: true },
  ] },
]

const PLAN_COPY: Record<string, string> = {
  free: "بوت الترند اليومي · Backtest 7 أيام",
  starter: "بوتين: ترند + مومنتم · Backtest 30 يوم",
  pro: "3 بوتات · Backtest 90 يوم · Futures",
  elite: "الـ 4 بوتات · Backtest بلا حدود",
}

function NavLink({ item, on }: { item: NavItem, on: boolean }){
  const Icon = item.icon
  return (
    <a href={item.href} aria-current={on ? "page" : undefined}
      className={`relative flex items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-[15px] font-semibold transition ${on ? "bg-surface2 text-ink" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
      {on && <i className="absolute left-2 top-1/2 h-[18px] w-[3px] -translate-y-1/2 rounded bg-corona"/>}
      <Icon size={20} strokeWidth={1.8} className={on ? "text-corona" : ""}/><span>{item.label}</span>
    </a>
  )
}

/** App layout for signed-in pages: RTL sidebar (right) + content + footer. `tier` is loaded here when a page doesn't pass it. */
export function AppShell({ active, tier: tierProp, engine, nextIn, children }: {
  active: string, tier?: string, engine?: { running: boolean }, nextIn?: number | null, children: React.ReactNode,
}){
  const [isAdmin, setIsAdmin] = useState(false)
  const [loadedTier, setLoadedTier] = useState<string | null>(null)
  const [gift, setGift] = useState<MyPlan["gift"]>(null)
  const [email, setEmail] = useState("")
  useEffect(() => {
    let live = true
    apiIsAdmin().then(v => { if (live) setIsAdmin(v) })
    getUser().then(u => { if (live) setEmail(u?.email || "") }).catch(() => {})
    getMyPlan().then(p => { if (live){ setGift(p.gift); if (tierProp === undefined) setLoadedTier(p.tier) } }).catch(() => {})
    return () => { live = false }
  }, [tierProp])
  const tier = tierProp ?? loadedTier ?? "free"
  const groups = GROUPS.map(g => ({ ...g, items: g.items.filter(i => !i.adminOnly || isAdmin) }))
  const all = groups.flatMap(g => g.items)

  return (
    <main className="min-h-screen bg-void text-ink lg:flex">
      {/* first child = right side in RTL */}
      <aside className="sticky top-0 hidden h-screen w-[264px] shrink-0 flex-col border-l border-line bg-surface px-5 pb-5 pt-6 lg:flex">
        <a href="/" className="mb-6 flex px-1"><Logo size="sm"/></a>
        <nav className="space-y-5">
          {groups.map(g => (
            <div key={g.label} className="space-y-1">
              <div className="px-3 text-[12px] font-semibold text-faint">{g.label}</div>
              {g.items.map(i => <NavLink key={i.href} item={i} on={i.href === active}/>)}
            </div>
          ))}
        </nav>
        <div className="mt-auto space-y-3">
          <div className="space-y-2.5 rounded-[14px] border border-line bg-surface2 p-4">
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-[14px] font-semibold" dir="ltr" style={{ textAlign: "right" }}>{email || "حسابك"}</span>
              <Pill tone="corona"><span className="font-mono uppercase">{tier}</span></Pill>
            </div>
            <p className="text-[12px] leading-5 text-muted">{PLAN_COPY[tier] || PLAN_COPY.free}</p>
            {gift && <div className="rounded-lg border border-signal/30 bg-signal/10 px-3 py-2 text-[12px] text-signal">
              باقة {gift.tier} هدية · فاضل <b className="font-mono">{Math.max(0, Math.ceil((new Date(gift.expires_at).getTime() - Date.now()) / 86_400_000))}</b> يوم
            </div>}
            {(tier !== "elite" || gift) && <a href="/#pricing" className="block rounded-lg bg-corona py-2 text-center text-xs font-bold text-void transition hover:bg-corona-soft">{gift ? "اشترك قبل ما الهدية تخلص" : "رقّي باقتك"}</a>}
            {engine && (
              <div className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs ${engine.running ? "bg-profit/10 text-profit" : "bg-line/60 text-muted"}`}>
                <span className="font-semibold">{engine.running ? "● المحرك شغال" : "○ المحرك واقف"}</span>
                <span className="font-mono tabular">{nextIn != null ? `00:${String(nextIn).padStart(2, "0")}` : "--:--"}</span>
              </div>
            )}
          </div>
          <NavLink item={{ href: "/", label: "الرئيسية", icon: House }} on={active === "/"}/>
          <button onClick={signOut} className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-[15px] font-semibold text-muted transition hover:bg-loss/10 hover:text-loss">
            <LogOut size={20} strokeWidth={1.8}/><span>تسجيل الخروج</span>
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-6 px-4 py-5 lg:px-8 lg:py-7">
        <div className="flex items-center justify-between gap-3 lg:hidden">
          <a href="/"><Logo size="sm"/></a>
          <div className="flex items-center gap-2">
            <Pill tone="corona"><span className="font-mono uppercase">{tier}</span></Pill>
            {email && <AccountMenu email={email} tier={tier} isAdmin={isAdmin} compact/>}
          </div>
        </div>
        <nav className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 lg:hidden">
          {all.map(i => (
            <a key={i.href} href={i.href} className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold ${i.href === active ? "border-corona/50 bg-corona/10 text-corona" : "border-line bg-surface text-muted"}`}>{i.label}</a>
          ))}
        </nav>
        {children}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 font-mono text-[10px] text-faint">
          <span>{BRAND.footer}</span>
          <span dir="ltr">{BRAND.domain}</span>
        </footer>
      </div>
    </main>
  )
}

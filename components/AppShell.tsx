"use client"
import { useEffect, useState } from "react"
import { BRAND } from "@/lib/brand"
import { Logo } from "@/components/Logo"
import { Pill } from "@/components/ui"
import { AccountMenu, signOut, signOutEverywhere } from "@/components/AccountMenu"
import { THEME_INIT, ThemeToggle } from "@/components/landing/ThemeToggle"
import { apiIsAdmin } from "@/lib/api"
import { authHeaders, getMyPlan, getUser, type MyPlan } from "@/lib/supabase"
import { setLanguage, useLocale, useT } from "@/lib/i18n/locale"
import { Activity, Bot, CandlestickChart, History, House, LayoutDashboard, LogOut, MonitorX, Receipt, ShieldCheck, Sparkles } from "lucide-react"

const T = {
  ar: {
    trading: "التداول", account: "الحساب", dashboard: "لوحة التحكم", live: "البوتات مباشر", backtest: "Backtest", lab: "مختبر AI",
    demo: "بوتاتي على Binance (Demo)", activity: "نشاط الحساب", statement: "كشف الحساب الشهري", admin: "الإدارة", home: "الرئيسية", signOut: "تسجيل الخروج", signOutAll: "اخرج من كل الأجهزة", you: "حسابك",
    plan: { free: "Backtest الترند اليومي · 7 أيام", starter: "Backtest الترند + المومنتم · 30 يوم", pro: "Backtest 3 استراتيجيات · 90 يوم", elite: "Backtest الـ 4 استراتيجيات · بلا حدود" } as Record<string, string>,
    gift: (t: string, d: number) => <>باقة {t} هدية · فاضل <b className="font-mono">{d}</b> يوم</>,
    upgrade: "رقّي باقتك", beforeGift: "اشترك قبل ما الهدية تخلص", manage: "إدارة الاشتراك / الإلغاء", opening: "بيفتح…", unavailable: "مش متاحة دلوقتي",
    engineOn: "● المحرك شغال", engineOff: "○ المحرك واقف", lang: "EN",
  },
  en: {
    trading: "Trading", account: "Account", dashboard: "Dashboard", live: "Live bots", backtest: "Backtest", lab: "AI lab",
    demo: "My Binance Demo bots", activity: "Account activity", statement: "Monthly statement", admin: "Admin", home: "Home", signOut: "Sign out", signOutAll: "Sign out of every device", you: "Your account",
    plan: { free: "Daily Trend backtest · 7 days", starter: "Trend + Momentum backtests · 30 days", pro: "3 strategies' backtests · 90 days", elite: "All 4 strategies' backtests · unlimited" } as Record<string, string>,
    gift: (t: string, d: number) => <>{t} plan, a gift · <b className="font-mono">{d}</b> days left</>,
    upgrade: "Upgrade your plan", beforeGift: "Subscribe before the gift ends", manage: "Manage / cancel subscription", opening: "Opening…", unavailable: "Not available right now",
    engineOn: "● Engine running", engineOff: "○ Engine stopped", lang: "عربي",
  },
}

type NavItem = { href: string, label: string, icon: typeof House, adminOnly?: boolean }

function NavLink({ item, on }: { item: NavItem, on: boolean }){
  const Icon = item.icon
  return (
    <a href={item.href} aria-current={on ? "page" : undefined}
      className={`relative flex items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-[15px] font-semibold transition ${on ? "bg-corona/10 text-corona" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
      {on && <i className="absolute end-2 top-1/2 h-[18px] w-[3px] -translate-y-1/2 rounded bg-corona"/>}
      <Icon size={20} strokeWidth={1.8}/><span>{item.label}</span>
    </a>
  )
}

/** A paid subscriber's way out (terms: cancel anytime): Stripe's own portal, for the customer on their profile. */
function ManageSubscription(){
  const t = useT(T)
  const [state, setState] = useState<"" | "loading" | string>("")
  async function open(){
    setState("loading")
    try{
      const r = await fetch("/api/stripe/portal", { method: "POST", headers: await authHeaders() })
      const j = await r.json().catch(() => ({}))
      if(r.ok && j.url){ window.location.href = j.url; return }
      setState(j.error || t.unavailable)
    }catch{ setState(t.unavailable) }
  }
  return (
    <div>
      <button onClick={open} disabled={state === "loading"} className="block w-full rounded-lg border border-line py-2 text-center text-xs font-semibold text-muted transition hover:text-ink disabled:opacity-60">
        {state === "loading" ? t.opening : t.manage}
      </button>
      {state && state !== "loading" && <p className="mt-1.5 text-[11px] leading-5 text-loss">{state}</p>}
    </div>
  )
}

/** App layout for signed-in pages: sidebar (the reading side's start) + content + footer. `tier` is loaded here when
 *  a page doesn't pass it. `themed`: the page is ready for the light theme and both languages, so the switches show
 *  (Figma "RAQM — Global Redesign 2026", 04 · Dashboard); other pages stay dark and Arabic until they are. */
export function AppShell({ active, tier: tierProp, engine, nextIn, themed = false, children }: {
  active: string, tier?: string, engine?: { running: boolean }, nextIn?: number | null, themed?: boolean, children: React.ReactNode,
}){
  const t = useT(T)
  const locale = useLocale()
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
  // a page not built for the light theme yet is always dark, whatever the visitor chose on a themed page
  useEffect(() => { if (!themed) delete document.documentElement.dataset.theme }, [themed])
  const tier = tierProp ?? loadedTier ?? "free"
  const groups: { label: string, items: NavItem[] }[] = [
    { label: t.trading, items: [
      { href: "/dashboard", label: t.dashboard, icon: LayoutDashboard },
      { href: "/dashboard#live-bots", label: t.live, icon: Activity },
      { href: "/backtest", label: t.backtest, icon: CandlestickChart },
      { href: "/llm-lab", label: t.lab, icon: Sparkles },
    ] },
    { label: t.account, items: [
      { href: "/settings/live", label: t.demo, icon: Bot },
      { href: "/settings/statement", label: t.statement, icon: Receipt },
      { href: "/settings/activity", label: t.activity, icon: History },
      { href: "/admin", label: t.admin, icon: ShieldCheck, adminOnly: true },
    ] },
  ].map(g => ({ ...g, items: g.items.filter(i => !i.adminOnly || isAdmin) }))
  const all = groups.flatMap(g => g.items)
  const switches = themed && (
    <div className="flex items-center gap-2">
      <ThemeToggle locale={locale}/>
      <button type="button" onClick={() => setLanguage(locale === "en" ? "ar" : "en")} data-testid="app-lang-switch"
        className="grid h-9 min-w-9 place-items-center rounded-[10px] border border-line bg-surface2 px-2.5 text-[12px] font-semibold text-muted transition hover:border-line2 hover:text-ink">{t.lang}</button>
    </div>
  )

  return (
    <main className="min-h-screen bg-void text-ink lg:flex">
      {themed && <script dangerouslySetInnerHTML={{ __html: THEME_INIT }}/>}
      <aside className="sticky top-0 hidden h-screen w-[264px] shrink-0 flex-col border-e border-line bg-surface px-5 pb-5 pt-6 lg:flex">
        <a href={locale === "en" ? "/" : "/ar"} className="mb-6 flex px-1"><Logo size="sm"/></a>
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
              <span className="min-w-0 flex-1 truncate text-[14px] font-semibold" dir="ltr" style={{ textAlign: locale === "en" ? "left" : "right" }}>{email || t.you}</span>
              <Pill tone="corona"><span className="font-mono uppercase">{tier}</span></Pill>
            </div>
            <p className="text-[12px] leading-5 text-muted">{t.plan[tier] || t.plan.free}</p>
            {gift && <div className="rounded-lg border border-signal/30 bg-signal/10 px-3 py-2 text-[12px] text-signal">
              {t.gift(gift.tier, Math.max(0, Math.ceil((new Date(gift.expires_at).getTime() - Date.now()) / 86_400_000)))}
            </div>}
            {(tier !== "elite" || gift) && <a href={locale === "en" ? "/#pricing" : "/ar#pricing"} className="block rounded-lg bg-corona py-2 text-center text-xs font-bold text-on-corona transition hover:bg-corona-soft">{gift ? t.beforeGift : t.upgrade}</a>}
            {tier !== "free" && !gift && <ManageSubscription/>}
            {engine && (
              <div className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs ${engine.running ? "bg-profit/10 text-profit" : "bg-line/60 text-muted"}`}>
                <span className="font-semibold">{engine.running ? t.engineOn : t.engineOff}</span>
                <span className="font-mono tabular">{nextIn != null ? `00:${String(nextIn).padStart(2, "0")}` : "--:--"}</span>
              </div>
            )}
          </div>
          <NavLink item={{ href: locale === "en" ? "/" : "/ar", label: t.home, icon: House }} on={active === "/"}/>
          <button onClick={signOut} className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-[15px] font-semibold text-muted transition hover:bg-loss/10 hover:text-loss">
            <LogOut size={20} strokeWidth={1.8}/><span>{t.signOut}</span>
          </button>
          <button onClick={signOutEverywhere} data-testid="sign-out-everywhere" className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2 text-[13px] text-faint transition hover:bg-loss/10 hover:text-loss">
            <MonitorX size={18} strokeWidth={1.8}/><span>{t.signOutAll}</span>
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-6 px-4 py-5 lg:px-8 lg:py-7">
        <div className="flex items-center justify-between gap-3 lg:hidden">
          <a href={locale === "en" ? "/" : "/ar"}><Logo size="sm"/></a>
          <div className="flex items-center gap-2">
            {switches}
            <Pill tone="corona"><span className="font-mono uppercase">{tier}</span></Pill>
            {email && <AccountMenu email={email} tier={tier} isAdmin={isAdmin} compact/>}
          </div>
        </div>
        <nav className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 lg:hidden">
          {all.map(i => (
            <a key={i.href} href={i.href} className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold ${i.href === active ? "border-corona/50 bg-corona/10 text-corona" : "border-line bg-surface text-muted"}`}>{i.label}</a>
          ))}
        </nav>
        {themed && <div className="hidden justify-end lg:flex">{switches}</div>}
        {children}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 font-mono text-[10px] text-faint">
          <span>{BRAND.footer}</span>
          <span dir="ltr">{BRAND.domain}</span>
        </footer>
      </div>
    </main>
  )
}

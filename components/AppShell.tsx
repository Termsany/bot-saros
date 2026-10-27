"use client"
import { useEffect, useState } from "react"
import { BRAND } from "@/lib/brand"
import { Logo } from "@/components/Logo"
import { apiIsAdmin } from "@/lib/api"
import { CandlestickChart, House, KeyRound, Layers, LayoutDashboard, ShieldCheck, Sparkles } from "lucide-react"

const NAV = [
  { href: "/dashboard", label: "لوحة التحكم", icon: LayoutDashboard },
  { href: "/backtest", label: "Backtest", icon: CandlestickChart },
  { href: "/dashboard#live-bots", label: "البوتات مباشر", icon: Layers },
  { href: "/llm-lab", label: "مختبر AI", icon: Sparkles },
  { href: "/settings/keys", label: "مفاتيح المنصات", icon: KeyRound },
  { href: "/admin", label: "الإدارة", icon: ShieldCheck, adminOnly: true },
  { href: "/", label: "الرئيسية", icon: House },
]

const PLAN_COPY: Record<string, string> = {
  free: "بوت الترند اليومي · Backtest 7 أيام",
  starter: "بوتين: ترند + مومنتم · Backtest 30 يوم",
  pro: "3 بوتات · Backtest 90 يوم · Futures",
  elite: "الـ 4 بوتات · Backtest بلا حدود",
}

/** App layout for signed-in pages: RTL sidebar (right) + content + footer. */
export function AppShell({ active, tier, engine, nextIn, children }: {
  active: string, tier: string, engine?: { running: boolean }, nextIn?: number | null, children: React.ReactNode,
}){
  const [isAdmin, setIsAdmin] = useState(false)
  const [adminChecked, setAdminChecked] = useState(false)

  useEffect(() => {
    let active = true
    apiIsAdmin().then(value => {
      if (!active) return
      setIsAdmin(value)
      setAdminChecked(true)
    })
    return () => { active = false }
  }, [])

  const visibleNav = NAV.filter(item => !item.adminOnly || (adminChecked && isAdmin))

  return (
    <main className="min-h-screen bg-void text-ink lg:flex">
      {/* first child = right side in RTL */}
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col justify-between border-l border-line bg-surface px-4 py-7 lg:flex">
        <div className="space-y-7">
          <a href="/" className="flex justify-end px-2"><Logo size="sm"/></a>
          <nav className="space-y-1">
            {visibleNav.map(({ href, label, icon: Icon })=>{
              const on = href === active
              return (
                <a key={href} href={href} aria-current={on ? "page" : undefined} className={`flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm transition ${on ? "bg-surface2 font-bold text-corona" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
                  <span>{label}</span><Icon size={18} strokeWidth={1.8}/>
                </a>
              )
            })}
          </nav>
        </div>
        <div className="space-y-3 rounded-2xl border border-umbra/40 bg-gradient-to-br from-[#1E1846] to-surface p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold">باقتك</span>
            <span className="rounded-full bg-corona px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-void">{tier}</span>
          </div>
          <p className="text-xs leading-5 text-muted">{PLAN_COPY[tier] || PLAN_COPY.free}</p>
          {tier!=="elite" && <a href="/#pricing" className="block rounded-lg bg-corona py-2 text-center text-xs font-bold text-void transition hover:bg-corona-soft">رقّي باقتك</a>}
          {engine && (
            <div className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs ${engine.running ? "bg-profit/10 text-profit" : "bg-line/60 text-muted"}`}>
              <span className="font-semibold">{engine.running ? "● المحرك يعمل" : "○ المحرك متوقف"}</span>
              <span className="font-mono tabular">{nextIn!=null ? `00:${String(nextIn).padStart(2,"0")}` : "--:--"}</span>
            </div>
          )}
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-5 p-4 lg:p-8">
        <div className="flex items-center justify-between lg:hidden">
          <a href="/"><Logo size="sm"/></a>
          <div className="hidden gap-3 text-xs text-muted min-[360px]:flex">
            {visibleNav.filter(n=> n.href!==active && ["/dashboard","/backtest","/admin","/"].includes(n.href)).map(n=> <a key={n.href} href={n.href}>{n.label}</a>)}
          </div>
        </div>
        {children}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 font-mono text-[10px] text-faint">
          <span>{BRAND.footer}</span>
          <span dir="ltr">{BRAND.domain}</span>
        </footer>
      </div>
    </main>
  )
}

// The landing page, English (/) and Arabic (/ar) — Figma "RAQM — Global Redesign 2026", page 03 · Landing.
// Server component: the words come from lib/i18n/landing.ts, the backtest numbers from lib/bot-stats.json, and the
// live parts (the real-money card, real vs backtest) read the real account in the browser.
import { ArrowUpRight, Check, Clock, LineChart, ShieldCheck } from "lucide-react"
import { Logo } from "@/components/Logo"
import { LandingNavAuth } from "@/components/AccountMenu"
import { REAL_PAGE } from "@/components/RealMoney"
import { BOT_PAGE, STATS_META, STRATEGIES, pfTone, sharpeTone } from "@/lib/strategies"
import { BRAND } from "@/lib/brand"
import { DIR, LANDING, OTHER, type Locale } from "@/lib/i18n/landing"
import { LiveRealCard } from "./LiveRealCard"
import { RealVsBacktest } from "./RealVsBacktest"
import { LandingPricing } from "./LandingPricing"
import { THEME_INIT, ThemeToggle } from "./ThemeToggle"

const TONE: Record<string, string> = { free: "border-corona/40 bg-corona/10 text-corona", starter: "border-signal/40 bg-signal/10 text-signal", pro: "border-umbra/40 bg-umbra/10 text-umbra", elite: "border-loss/40 bg-loss/10 text-loss" }

/** The backtest equity curve of a strategy (monthly, from lib/bot-stats.json) as a small line. */
function Spark({ points }: { points: [string, number][] }){
  const ys = points.map(p => p[1]); const min = Math.min(...ys), max = Math.max(...ys), w = 240, h = 52
  const d = ys.map((y, i) => `${i ? "L" : "M"}${(i / Math.max(1, ys.length - 1) * w).toFixed(1)} ${(h - 4 - (y - min) / Math.max(1e-9, max - min) * (h - 8)).toFixed(1)}`).join(" ")
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-[52px] w-full" aria-hidden>
      <path d={`${d} L${w} ${h} L0 ${h} Z`} className="fill-profit/10"/>
      <path d={d} className="stroke-profit" fill="none" strokeWidth="1.8" vectorEffect="non-scaling-stroke"/>
    </svg>
  )
}

function Section({ id, eyebrow, title, sub, children }: { id?: string; eyebrow: string; title: string; sub?: string; children: React.ReactNode }){
  return (
    <section id={id} className="mx-auto max-w-[1180px] scroll-mt-24 px-5 py-20 sm:py-24">
      <div className="max-w-[760px]">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-corona">{eyebrow}</div>
        <h2 className="mt-3 text-[32px] font-bold leading-tight sm:text-[44px]">{title}</h2>
        {sub && <p className="mt-3 text-[16px] leading-7 text-muted sm:text-[18px] sm:leading-8">{sub}</p>}
      </div>
      <div className="mt-10">{children}</div>
    </section>
  )
}

export function Landing({ locale, prices }: { locale: Locale; prices?: Record<string, number> }){
  const t = LANDING[locale]
  const other = OTHER[locale]
  return (
    <div lang={locale} dir={DIR[locale]} className="min-h-screen overflow-x-clip bg-void font-sans text-ink">
      <script dangerouslySetInnerHTML={{ __html: THEME_INIT }}/>
      {/* NAV */}
      <header className="sticky top-0 z-30 border-b border-line/70 bg-void/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between gap-3 px-5">
          <a href={locale === "ar" ? "/ar" : "/"} aria-label={BRAND.nameCaps}><Logo size="sm"/></a>
          <nav className="hidden items-center gap-7 text-[14px] text-muted lg:flex">
            <a href="#strategies" className="transition hover:text-ink">{t.nav.strategies}</a>
            <a href="#proof" className="transition hover:text-ink">{t.nav.proof}</a>
            <a href="#pricing" className="transition hover:text-ink">{t.nav.pricing}</a>
            <a href="/backtest" className="transition hover:text-ink">{t.nav.backtest}</a>
            <a href="#faq" className="transition hover:text-ink">{t.nav.faq}</a>
          </nav>
          <div className="flex shrink-0 items-center gap-2">
            <ThemeToggle locale={locale}/>
            <a href={other.href} hrefLang={locale === "en" ? "ar" : "en"} className="grid h-9 min-w-9 place-items-center rounded-[10px] border border-line bg-surface2 px-2.5 text-[12px] font-semibold text-muted transition hover:border-line2 hover:text-ink" data-testid="lang-switch">{other.label}</a>
            <LandingNavAuth labels={t.auth}/>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="relative">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[640px] bg-[radial-gradient(55%_60%_at_75%_0%,rgb(var(--c-umbra)/0.18),transparent_70%),radial-gradient(40%_50%_at_15%_10%,rgb(var(--c-corona)/0.12),transparent_70%)]"/>
        <div className="relative mx-auto grid max-w-[1180px] items-center gap-12 px-5 pb-16 pt-14 lg:grid-cols-[minmax(0,1fr)_520px] lg:pb-20 lg:pt-24">
          <div className="animate-fade-up">
            <span className="inline-flex items-center gap-2 rounded-full border border-loss/35 bg-loss/10 px-3 py-1 text-[12px] font-semibold text-loss">
              <i className="relative h-1.5 w-1.5 rounded-full bg-loss after:absolute after:inset-0 after:animate-ping after:rounded-full after:bg-loss"/>{t.hero.badge}
            </span>
            <h1 className={`mt-6 font-bold sm:text-[64px] ${locale === "ar" ? "text-[34px] leading-[1.3] sm:leading-[1.2]" : "text-[42px] leading-[1.05]"}`}>{t.hero.title[0]}<br/><span className="bg-gradient-to-r from-corona to-corona-soft bg-clip-text text-transparent rtl:bg-gradient-to-l">{t.hero.title[1]}</span></h1>
            <p className="mt-6 max-w-[560px] text-[17px] leading-8 text-muted sm:text-[18px]">{t.hero.sub}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-corona px-6 py-3.5 text-[15px] font-semibold text-on-corona shadow-[0_10px_30px_-10px_rgb(var(--c-corona)/.7)] transition hover:-translate-y-0.5 hover:bg-corona-soft">{t.hero.ctaStart}</a>
              <a href={REAL_PAGE} target="_blank" rel="noopener" className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface2 px-6 py-3.5 text-[15px] font-semibold transition hover:-translate-y-0.5 hover:border-line2 hover:bg-surface">{t.hero.ctaLive} <ArrowUpRight size={16} className="rtl:-scale-x-100"/></a>
            </div>
            <div className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-muted">
              {t.hero.trust.map(x => <span key={x} className="flex items-center gap-1.5"><Check size={15} className="text-profit"/>{x}</span>)}
            </div>
          </div>
          <div className="animate-fade-up [animation-delay:.12s]"><LiveRealCard locale={locale} href={REAL_PAGE}/></div>
        </div>
        <div className="relative mx-auto grid max-w-[1180px] grid-cols-2 gap-3 px-5 pb-6 md:grid-cols-4">
          {t.strip.map(([l, v, n]) => (
            <div key={l} className="rounded-[18px] border border-line bg-surface px-5 py-4">
              <div className="text-[12px] text-muted">{l}</div>
              <div className="mt-1.5 font-mono text-[24px] font-bold tabular" dir="ltr" style={{ textAlign: locale === "ar" ? "right" : "left" }}>{v}</div>
              <div className="mt-1 text-[11px] text-faint">{n}</div>
            </div>
          ))}
        </div>
      </section>

      {/* HOW IT WORKS */}
      <Section eyebrow={t.how.eyebrow} title={t.how.title} sub={t.how.sub}>
        <div className="grid gap-4 md:grid-cols-3">
          {t.how.steps.map(([title, body], i) => {
            const Icon = [LineChart, Clock, ShieldCheck][i]
            return (
              <div key={title} className="rounded-[20px] border border-line bg-surface p-6 transition duration-300 hover:-translate-y-1 hover:border-line2">
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-corona/10 text-corona"><Icon size={20} strokeWidth={1.8}/></span>
                <h3 className="mt-5 text-[19px] font-semibold">{title}</h3>
                <p className="mt-2 text-[15px] leading-7 text-muted">{body}</p>
              </div>
            )
          })}
        </div>
      </Section>

      {/* STRATEGIES — numbers from lib/bot-stats.json (research/bots_stats.py) */}
      <Section id="strategies" eyebrow={t.strat.eyebrow} title={t.strat.title} sub={t.strat.sub}>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {STRATEGIES.map(s => (
            <div key={s.id} className={`flex flex-col rounded-[20px] border bg-surface p-5 transition duration-300 hover:-translate-y-1 ${s.risk === "high" ? "border-loss/40" : "border-line hover:border-line2"}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="text-[18px] font-semibold leading-snug">{t.strat.names[s.id] || s.name}</div>
                <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${TONE[s.tier]}`}>{s.risk === "high" ? t.strat.high : s.tier[0].toUpperCase() + s.tier.slice(1)}</span>
              </div>
              <p className="mt-2 flex-1 text-[14px] leading-6 text-muted">{t.strat.desc[s.id] || s.desc}</p>
              <div className="mt-4"><Spark points={s.equity}/></div>
              <div className="mt-3 grid grid-cols-4 gap-1 border-t border-line pt-3">
                {[[t.strat.trades, s.trades.toLocaleString("en-US"), "text-ink"], [t.strat.win, `${s.winRate}%`, "text-ink"], [t.strat.pf, s.pf.toFixed(2), pfTone(s.pf)], [t.strat.sharpe, s.sharpeOut.toFixed(2), sharpeTone(s.sharpeOut)]].map(([l, v, c]) => (
                  <div key={l} className="min-w-0"><div className={`font-mono text-[14px] font-medium tabular ${c}`}>{v}</div><div className="truncate text-[10.5px] text-faint">{l}</div></div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 text-[12px] text-faint">
          <span>{t.strat.note(STATS_META.from.slice(0, 7), STATS_META.to.slice(0, 7), STATS_META.symbolsTested)}</span>
          <a href={BOT_PAGE} target="_blank" rel="noopener" className="inline-flex items-center gap-1 font-semibold text-corona hover:underline">{t.strat.watch} <ArrowUpRight size={14} className="rtl:-scale-x-100"/></a>
        </div>
      </Section>

      {/* REAL vs BACKTEST */}
      <Section id="proof" eyebrow={t.proof.eyebrow} title={t.proof.title} sub={t.proof.sub}>
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <RealVsBacktest locale={locale}/>
          <div className="rounded-[20px] border border-line bg-surface p-6">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-corona/40 bg-corona/10 px-2.5 py-0.5 text-[11px] font-semibold text-corona"><i className="h-1.5 w-1.5 rounded-full bg-corona"/>{t.proof.sideBadge}</span>
            <p className="mt-4 text-[15px] leading-7 text-muted">{t.proof.sideText}</p>
            <a href={REAL_PAGE} target="_blank" rel="noopener" className="mt-5 inline-flex items-center gap-2 rounded-xl border border-line bg-surface2 px-4 py-2.5 text-[14px] font-semibold transition hover:border-line2 hover:bg-surface">{t.proof.sideCta} <ArrowUpRight size={15} className="rtl:-scale-x-100"/></a>
          </div>
        </div>
      </Section>

      {/* PRICING */}
      <Section id="pricing" eyebrow={t.pricing.eyebrow} title={t.pricing.title} sub={t.pricing.sub}>
        <LandingPricing locale={locale} prices={prices}/>
      </Section>

      {/* FAQ */}
      <Section id="faq" eyebrow={t.faq.eyebrow} title={t.faq.title}>
        <div className="grid gap-3 md:grid-cols-2">
          {t.faq.items.map(([q, a]) => (
            <details key={q} className="group rounded-[18px] border border-line bg-surface px-5 py-4 transition open:border-line2 open:bg-surface2/40">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-[16px] font-semibold">{q}<span className="text-[20px] leading-none text-corona transition duration-300 group-open:rotate-45">+</span></summary>
              <p className="mt-3 text-[14px] leading-7 text-muted">{a}</p>
            </details>
          ))}
        </div>
      </Section>

      {/* CTA */}
      <section className="mx-auto max-w-[1180px] px-5 pb-20">
        <div className="flex flex-wrap items-center justify-between gap-6 rounded-[28px] border border-line2 bg-[linear-gradient(110deg,rgb(var(--c-umbra)/0.20),rgb(var(--c-surface))_55%,rgb(var(--c-corona)/0.16))] px-8 py-10 sm:px-12">
          <div>
            <h2 className="text-[28px] font-bold sm:text-[32px]">{t.cta.title}</h2>
            <p className="mt-2 text-[16px] text-muted">{t.cta.sub}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <a href={REAL_PAGE} target="_blank" rel="noopener" className="rounded-xl border border-line bg-surface2 px-6 py-3 text-[15px] font-semibold transition hover:border-line2 hover:bg-surface">{t.cta.live}</a>
            <a href="/dashboard" className="rounded-xl bg-corona px-6 py-3 text-[15px] font-semibold text-on-corona transition hover:bg-corona-soft">{t.cta.start}</a>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-[1180px] px-5 py-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Logo size="sm"/>
            <div className="flex flex-wrap gap-5 text-[14px] text-muted">
              <a href="/backtest" className="hover:text-ink">{t.footer.backtest}</a>
              <a href={REAL_PAGE} target="_blank" rel="noopener" className="hover:text-ink">{t.footer.live}</a>
              <a href="/terms" className="hover:text-ink">{t.footer.terms}</a>
              <a href={other.href} className="hover:text-ink">{other.label}</a>
            </div>
          </div>
          <p className="mt-6 max-w-[900px] text-[12px] leading-6 text-faint">{t.footer.risk}</p>
          <div className="mt-4 flex flex-wrap justify-between gap-2 font-mono text-[11px] text-faint"><span>© 2026 {BRAND.nameCaps}</span><span dir="ltr">{BRAND.domain}</span></div>
        </div>
      </footer>
    </div>
  )
}

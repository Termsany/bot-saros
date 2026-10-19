import { Pricing } from "@/components/Pricing"
import { HeroPreview } from "@/components/HeroPreview"
import { BRAND } from "@/lib/brand"
import { MOST_CONSISTENT, STATS_META, STRATEGIES, TIERS, pfTone } from "@/lib/strategies"
import { Logo } from "@/components/Logo"
import { ArrowUpRight, CandlestickChart, Check, Layers, LineChart, ShieldCheck, Zap } from "lucide-react"

// a plan unlocks the first `count` strategies (same rule as the backend)
const unlockTier = (i: number) => TIERS.find(t => t.count > i) || TIERS[TIERS.length-1]

const STEPS = [
  { icon: Layers, title: "اختار استراتيجيتك", body: "16 استراتيجية من التحليل الكلاسيكي لحد Smart Money وموجات Flat. شغّل واحدة أو اجمع كذا واحدة مع بعض." },
  { icon: CandlestickChart, title: "اختبرها على بيانات حقيقية", body: "Backtest على شموع Bybit وBinance للفترة اللي تختارها، بنفس قواعد البوت بالظبط. وشوف كل صفقة: دخلت فين، خرجت فين، وكسبت ولا خسرت." },
  { icon: LineChart, title: "تابعها لحظة بلحظة", body: "المحرك بيراقب السوق على مدار الساعة ويسجّل الصفقات على محفظة وهمية، وانت شايف الأرباح ونسبة الفوز في الداشبورد." },
]

const FAQ = [
  { q: "هل البوت بيضمن ربح؟", a: "لأ. الأرقام اللي في الموقع نتايج اختبارات على بيانات سابقة، والنتايج السابقة مش ضمان للمستقبل. تداول العملات الرقمية — خصوصاً بالرافعة — عالي المخاطرة وممكن تخسر جزء من رأس مالك أو كله." },
  { q: "لازم أحط فلوس حقيقية عشان أجرّب؟", a: "لأ. الـ Backtest والمحفظة التجريبية بفلوس وهمية 100%، والباقة المجانية مش محتاجة كارت." },
  { q: "الأرقام اللي في جدول الاستراتيجيات جاية منين؟", a: "من Backtest حقيقي بنفس محرك البوت: 4 عملات على فريمين، 2000 شمعة لكل واحدة، والربح محسوب بعد الرسوم. «كسبت في» معناها في كام مجموعة من الـ 8 الاستراتيجية خلصت كسبانة. ومعظم الاستراتيجيات قريبة من التعادل — عشان كده بنعرض الأرقام زي ما هي." },
  { q: "إيه الفرق بين الباقات؟", a: "كل باقة بتفتح عدد استراتيجيات أكبر ومدة Backtest أطول: المجانية 7 أيام، Starter ‏30 يوم، Pro ‏90 يوم، وElite بلا حدود مع كل الاستراتيجيات." },
  { q: "الدفع آمن؟", a: "الدفع كله عن طريق Stripe، وبيانات الكارت مش بتعدّي على سيرفراتنا أصلاً." },
]

export default function Page(){
  return (
    <main className="min-h-screen overflow-x-clip bg-void text-ink">
      <header className="sticky top-0 z-30 border-b border-line/70 bg-void/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between px-5">
          <Logo/>
          <nav className="flex items-center gap-1">
            <a href="#strategies" className="hidden px-3 text-sm text-muted hover:text-ink md:block">الاستراتيجيات</a>
            <a href="#pricing" className="hidden px-3 text-sm text-muted hover:text-ink md:block">الباقات</a>
            <a href="/backtest" className="hidden px-3 text-sm text-muted hover:text-ink md:block">Backtest</a>
            <a href="/auth" className="hidden px-3 text-sm text-muted hover:text-ink sm:block">دخول</a>
            <a href="/dashboard" className="rounded-xl bg-corona px-4 py-2 text-sm font-bold text-void transition hover:bg-corona-soft">افتح المنصة</a>
          </nav>
        </div>
      </header>

      {/* HERO */}
      <section className="relative">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[520px] bg-[radial-gradient(60%_60%_at_70%_0%,rgba(123,97,255,0.16),transparent_70%),radial-gradient(40%_50%_at_20%_10%,rgba(245,184,65,0.10),transparent_70%)]"/>
        <div className="relative mx-auto grid max-w-[1180px] items-center gap-12 px-5 pb-16 pt-14 lg:grid-cols-[minmax(0,1fr)_460px] lg:pt-20">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-corona"><Zap size={13}/> {BRAND.taglineAr}</span>
            <h1 className="mt-6 text-[40px] font-black leading-[1.15] sm:text-[56px]">تداول بالأرقام،<br/><span className="bg-gradient-to-l from-corona-soft to-corona bg-clip-text text-transparent">مش بالإحساس.</span></h1>
            <p className="mt-5 max-w-[540px] text-base leading-8 text-muted">رقم بوت تداول للعملات الرقمية: 16 استراتيجية مختبرة على بيانات حقيقية، صفقات LONG وSHORT بالرافعة، وتقدر تختبر أي استراتيجية مجاناً قبل ما تدفع جنيه.</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-corona px-6 py-3 text-sm font-bold text-void transition hover:bg-corona-soft"><Zap size={16}/> ابدأ مجاناً</a>
              <a href="/backtest" className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-6 py-3 text-sm font-semibold transition hover:bg-surface2">جرّب Backtest <ArrowUpRight size={15}/></a>
            </div>
            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted">
              <span className="flex items-center gap-1.5"><Check size={14} className="text-corona"/> بدون كارت للباقة المجانية</span>
              <span className="flex items-center gap-1.5"><Check size={14} className="text-corona"/> فلوس وهمية 100% للتجربة</span>
              <span className="flex items-center gap-1.5"><ShieldCheck size={14} className="text-corona"/> دفع آمن عن طريق Stripe</span>
            </div>
          </div>
          <HeroPreview/>
        </div>
      </section>

      {/* STATS */}
      <section className="border-y border-line bg-surface/60">
        <div className="mx-auto grid max-w-[1180px] grid-cols-2 gap-px px-5 md:grid-cols-4">
          {[
            ["16", "استراتيجية", "من كلاسيكي لموجات Flat"],
            ["20", "زوج عملات", "BTC · ETH · SOL وغيرهم"],
            ["x5", "رافعة Futures", "LONG و SHORT"],
            ["3", "مصادر بيانات", "Bybit · OKX · Binance"],
          ].map(([v,l,sub])=>(
            <div key={l} className="py-7 text-center">
              <div className="font-display text-[34px] font-bold leading-none text-corona">{v}</div>
              <div className="mt-2 text-sm font-bold">{l}</div>
              <div className="mt-0.5 text-xs text-faint">{sub}</div>
            </div>
          ))}
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="mx-auto max-w-[1180px] px-5 py-20">
        <h2 className="text-center text-[30px] font-black">إزاي بيشتغل</h2>
        <p className="mt-2 text-center text-sm text-muted">من الفكرة لأول صفقة في 3 خطوات</p>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, i)=>(
            <div key={title} className="rounded-2xl border border-line bg-surface p-6">
              <div className="flex items-center justify-between">
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-corona/10 text-corona"><Icon size={20} strokeWidth={1.8}/></span>
                <span className="font-display text-4xl font-bold text-line">0{i+1}</span>
              </div>
              <h3 className="mt-5 text-lg font-bold">{title}</h3>
              <p className="mt-2 text-sm leading-7 text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* STRATEGIES — numbers come from lib/strategy-stats.json (research/measure_strategies.py) */}
      <section id="strategies" className="mx-auto max-w-[1180px] scroll-mt-20 px-5 pb-20">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-[30px] font-black">الـ 16 استراتيجية</h2>
            <p className="mt-1 max-w-[720px] text-sm leading-6 text-muted">
              نتايج حقيقية من Backtest على {STATS_META.symbols.map(x => x.replace("/USDT", "")).join(" و")}، فريم ساعة و4 ساعات
              ({STATS_META.sets} مجموعات بيانات، {STATS_META.candlesPerSet.toLocaleString("en-US")} شمعة لكل واحدة، لحد {STATS_META.to}).
              كل صفقة ${STATS_META.engine.marginUsdt} × {STATS_META.engine.leverage}، والربح بعد الرسوم.
            </p>
          </div>
          <a href="/backtest" className="flex items-center gap-1 text-sm font-semibold text-corona hover:underline">اختبر أي واحدة بنفسك <ArrowUpRight size={14}/></a>
        </div>
        <div className="mt-6 overflow-x-auto rounded-2xl border border-line bg-surface">
          <table className="w-full min-w-[780px] text-sm">
            <thead className="bg-surface2/60 text-xs text-muted">
              <tr>
                <th className="px-5 py-3 text-right font-semibold">الاستراتيجية</th>
                <th className="hidden px-5 py-3 text-right font-semibold lg:table-cell">الفكرة</th>
                <th className="px-4 py-3 text-center font-semibold">صفقات</th>
                <th className="px-4 py-3 text-center font-semibold">نسبة الفوز</th>
                <th className="px-4 py-3 text-center font-semibold">PF</th>
                <th className="px-4 py-3 text-center font-semibold">صافي الربح</th>
                <th className="px-4 py-3 text-center font-semibold">كسبت في</th>
                <th className="px-4 py-3 text-center font-semibold">متاحة من</th>
              </tr>
            </thead>
            <tbody>
              {STRATEGIES.map((s, i)=>{
                const t = unlockTier(i), best = s.id === MOST_CONSISTENT.id
                return (
                  <tr key={s.id} className={`border-t border-line ${best ? "bg-corona/[0.05]" : "hover:bg-surface2/50"}`}>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <span className="font-bold">{s.nameAr}</span>
                        <span className="font-display text-xs text-faint">{s.name}</span>
                        {best && <span className="rounded-full bg-corona px-2 py-0.5 text-[10px] font-bold text-void">الأثبت</span>}
                      </div>
                      <div className="mt-0.5 text-xs text-muted lg:hidden">{s.desc}</div>
                    </td>
                    <td className="hidden px-5 py-3.5 text-xs text-muted lg:table-cell">{s.desc}</td>
                    <td className="px-4 py-3.5 text-center font-mono text-muted">{s.trades.toLocaleString("en-US")}</td>
                    <td className="px-4 py-3.5 text-center font-mono text-muted">{s.winRate}%</td>
                    <td className={`px-4 py-3.5 text-center font-mono font-bold ${pfTone(s.pf)}`}>{s.pf.toFixed(2)}</td>
                    <td className={`px-4 py-3.5 text-center font-mono font-bold ${s.pnl >= 0 ? "text-profit" : "text-loss"}`} dir="ltr">{s.pnl >= 0 ? "+" : ""}{s.pnl.toFixed(0)}$</td>
                    <td className="px-4 py-3.5 text-center font-mono text-muted">{s.setsWon}/{STATS_META.sets}</td>
                    <td className="px-4 py-3.5 text-center"><span className="rounded-full px-2.5 py-0.5 text-[11px] font-bold" style={{color: t.color, background: `${t.color}1A`}}>{t.name}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-faint">
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-profit"/> PF ≥ 1.05 كسبانة</span>
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-corona"/> 0.95–1.05 تقريباً متعادلة</span>
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-loss"/> أقل من 0.95 خسرانة</span>
          <span>· «الأثبت» = كسبت في أكبر عدد من المجموعات، في الفترة كلها وفي آخر 40% منها</span>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className="mx-auto max-w-[1180px] px-5 py-20">
          <h2 className="text-center text-[30px] font-black">الباقات</h2>
          <p className="mt-2 text-center text-sm text-muted">ابدأ مجاناً، ورقّي وقت ما تحتاج استراتيجيات أكتر</p>
          <div className="mt-10"><Pricing/></div>
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto max-w-[820px] px-5 py-20">
        <h2 className="text-center text-[30px] font-black">أسئلة شائعة</h2>
        <div className="mt-8 space-y-3">
          {FAQ.map(({ q, a })=>(
            <details key={q} className="group rounded-2xl border border-line bg-surface px-5 py-4 open:bg-surface2/40">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-bold">{q}<span className="text-corona transition group-open:rotate-45">+</span></summary>
              <p className="mt-3 text-sm leading-7 text-muted">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-[1180px] px-5 pb-20">
        <div className="rounded-3xl border border-umbra/40 bg-gradient-to-br from-[#1E1846] via-surface to-surface px-6 py-12 text-center">
          <h2 className="text-[28px] font-black">جاهز تتداول بالأرقام؟</h2>
          <p className="mt-2 text-sm text-muted">افتح المنصة مجاناً، واختبر أول استراتيجية في أقل من دقيقة.</p>
          <a href="/dashboard" className="mt-6 inline-flex items-center gap-2 rounded-xl bg-corona px-7 py-3 text-sm font-bold text-void transition hover:bg-corona-soft"><Zap size={16}/> ابدأ مجاناً</a>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-[1180px] px-5 py-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Logo size="sm"/>
            <div className="flex gap-5 text-sm text-muted">
              <a href="/backtest" className="hover:text-ink">Backtest</a>
              <a href="#pricing" className="hover:text-ink">الباقات</a>
              <a href="/auth" className="hover:text-ink">دخول</a>
            </div>
          </div>
          <p className="mt-6 text-xs leading-6 text-faint">تنبيه: تداول العملات الرقمية عالي المخاطرة، والأداء السابق في الـ Backtest مش ضمان لنتايج مستقبلية. المحتوى ده مش نصيحة استثمارية.</p>
          <div className="mt-4 flex flex-wrap justify-between gap-2 font-mono text-[11px] text-faint">
            <span>{BRAND.footer}</span><span dir="ltr">{BRAND.domain}</span>
          </div>
        </div>
      </footer>
    </main>
  )
}

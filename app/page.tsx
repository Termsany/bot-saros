import { Pricing } from "@/components/Pricing"
import { HeroPreview } from "@/components/HeroPreview"
import { BRAND } from "@/lib/brand"
import { BOT_PAGE, COMBINED, STATS_META, STRATEGIES, minCapitalNote, pfTone, sharpeTone, unlockTier } from "@/lib/strategies"
import { Logo } from "@/components/Logo"
import { FooterAuthLink, LandingNavAuth } from "@/components/AccountMenu"
import { ArrowUpRight, CandlestickChart, Check, Layers, LineChart, ShieldCheck, Zap } from "lucide-react"


const STEPS = [
  { icon: Layers, title: "4 بوتات بس، مختبرة بجد", body: "جربنا أكتر من 15 فكرة من أبحاث التداول على كل عملات Binance من 2019 — والمشطوبة كمان — وفضّلنا اللي نجح بس: ترند يومي، مومنتم لونج/شورت، شورت العملات الجديدة، وترند النسبة (High Risk)." },
  { icon: CandlestickChart, title: "أرقام من غير تجميل", body: "كل رقم محسوب بعد الرسوم والـ funding الحقيقي، والعملات بتتختار بالفوليوم وقتها مش بأثر رجعي. والإعدادات اتختارت على قبل 2024 واتختبرت على اللي بعدها." },
  { icon: LineChart, title: "تابعها لحظة بلحظة", body: "البوتات شغالة على السيرفر 24 ساعة على محفظة وهمية، وانت شايف كل صفقة وأرباحها لحظة بلحظة في الداشبورد وعلى صفحة البوتات." },
]

const FAQ = [
  { q: "هل البوت بيضمن ربح؟", a: "لأ. الأرقام اللي في الموقع نتايج اختبارات على بيانات سابقة، والنتايج السابقة مش ضمان للمستقبل. تداول العملات الرقمية — خصوصاً بالرافعة — عالي المخاطرة وممكن تخسر جزء من رأس مالك أو كله." },
  { q: "لازم أحط فلوس حقيقية عشان أجرّب؟", a: "لأ. الـ Backtest والمحفظة التجريبية بفلوس وهمية 100%، والباقة المجانية مش محتاجة كارت." },
  { q: "الأرقام اللي في جدول البوتات جاية منين؟", a: "من اختبار على كل عقود USDT على Binance من 2019 — ومعاها العملات اللي اتشالت، عشان النتيجة متبقاش منحازة للعملات اللي نجحت. العملات بتتختار بالفوليوم وقتها، والربح بعد الرسوم والـ funding الحقيقي، بهامش 20$ × 2. الـ Sharpe «2024+» هو أداء الفترة اللي ما اتستخدمتش في اختيار الإعدادات." },
  { q: "ليه 4 استراتيجيات بس؟", a: "لأننا اختبرنا أكتر من 15 فكرة من أبحاث التداول (عكس الترند، الأزواج، الـ funding، الـ beta وغيرهم) وكلها فشلت على فريم اليوم ما عدا دول. بنعرض اللي اشتغل بس. وترند النسبة متعلّم High Risk لأن أقصى تراجعه كبير." },
  { q: "إيه الفرق بين الباقات؟", a: "كل باقة بتفتح بوتات أكتر ومدة Backtest أطول: المجانية الترند اليومي و7 أيام Backtest، Starter بيضيف المومنتم و30 يوم، Pro بيضيف شورت العملات الجديدة و90 يوم، وElite الـ 4 بوتات وBacktest بلا حدود." },
  { q: "الدفع آمن؟", a: "الدفع كله عن طريق Stripe، وبيانات الكارت مش بتعدّي على سيرفراتنا أصلاً." },
]

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
export const revalidate = 300

/** The plans' current prices (the admin can change them), or none so Pricing shows its defaults. */
async function planPrices(): Promise<Record<string, number> | undefined>{
  try{
    const r = await fetch(`${API}/api/plans`, { next: { revalidate: 300 }, signal: AbortSignal.timeout(4000) })
    return r.ok ? (await r.json()).prices : undefined
  }catch{ return undefined }
}

export default async function Page(){
  const prices = await planPrices()
  return (
    <main className="min-h-screen overflow-x-clip bg-void text-ink">
      <header className="sticky top-0 z-30 border-b border-line/70 bg-void/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between px-5">
          <Logo/>
          <nav className="flex items-center gap-1">
            <a href="#strategies" className="hidden px-3 text-sm text-muted hover:text-ink md:block">الاستراتيجيات</a>
            <a href="#pricing" className="hidden px-3 text-sm text-muted hover:text-ink md:block">الباقات</a>
            <a href="/backtest" className="hidden px-3 text-sm text-muted hover:text-ink md:block">Backtest</a>
            <LandingNavAuth/>
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
            <p className="mt-5 max-w-[540px] text-base leading-8 text-muted">رقم بوتات تداول للعملات الرقمية: 4 استراتيجيات بس — اللي نجحت من أكتر من 15 فكرة اختبرناها على كل العملات من 2019. لونج وشورت، شغالة دلوقتي وتقدر تتابعها لحظة بلحظة.</p>
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
            ["4", "بوتات شغالة", "لونج وشورت · Paper"],
            [`${STATS_META.symbolsTested}`, "عملة في الاختبار", "من 2019 · والمشطوبة كمان"],
            [COMBINED.core.sharpeOut.toFixed(2), "Sharpe 2024+", "التلات بوتات الأساسية مع بعض"],
            ["24/7", "متابعة مباشرة", "الداشبورد + bot.da3m.io"],
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

      {/* STRATEGIES — numbers come from lib/bot-stats.json (research/bots_stats.py) */}
      <section id="strategies" className="mx-auto max-w-[1180px] scroll-mt-20 px-5 pb-20">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-[30px] font-black">الـ 4 بوتات</h2>
            <p className="mt-1 max-w-[760px] text-sm leading-6 text-muted">
              اختبار على كل عقود USDT على Binance ({STATS_META.symbolsTested} عملة، والمشطوبة كمان) من {STATS_META.from.slice(0, 4)} لحد {STATS_META.to}،
              والعملات بتتختار بالفوليوم وقتها. كل صفقة ${STATS_META.marginUsdt} × {STATS_META.leverage}، والربح بعد الرسوم والـ funding.
              الإعدادات اتختارت على قبل 2024، و«Sharpe ‎2024+» هو أداء الفترة اللي بعدها.
            </p>
          </div>
          <a href={BOT_PAGE} target="_blank" rel="noopener" className="flex items-center gap-1 text-sm font-semibold text-corona hover:underline">شوفها شغالة دلوقتي <ArrowUpRight size={14}/></a>
        </div>
        <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {STRATEGIES.map((s, i)=>{
            const t = unlockTier(i)
            return (
              <div key={s.id} className={`flex flex-col rounded-2xl border bg-surface p-5 ${s.risk === "high" ? "border-loss/40" : "border-line"}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[17px] font-bold leading-snug">{s.nameAr}</div>
                    <div className="text-[12px] text-faint">{s.name} · {s.sides}</div>
                  </div>
                  {s.risk === "high"
                    ? <span className="shrink-0 rounded-full border border-loss/40 bg-loss/10 px-2.5 py-0.5 text-[12px] font-semibold text-loss">خطورة عالية</span>
                    : <span className="shrink-0 rounded-full px-2.5 py-0.5 text-[12px] font-semibold" style={{color: t.color, background: `${t.color}1A`}}>{t.name}</span>}
                </div>
                <p className="mt-2 flex-1 text-[13px] leading-6 text-muted">{s.desc}</p>
                <div className="mt-4 grid grid-cols-4 gap-1 border-t border-line pt-3 text-center">
                  {[["صفقات", s.trades.toLocaleString("en-US"), "text-ink"], ["الفوز", `${s.winRate}%`, "text-ink"], ["PF", s.pf.toFixed(2), pfTone(s.pf)], ["Sharpe 24+", s.sharpeOut.toFixed(2), sharpeTone(s.sharpeOut)]].map(([l, v, c]) => (
                    <div key={l}><div className={`font-mono text-[15px] font-medium tabular ${c}`}>{v}</div><div className="text-[11px] text-faint">{l}</div></div>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between rounded-xl bg-surface2/60 px-3 py-2 text-[12px]">
                  <span className="text-muted">صافي <b className={`font-mono ${s.pnl >= 0 ? "text-profit" : "text-loss"}`} dir="ltr">{s.pnl >= 0 ? "+" : ""}{s.pnl.toFixed(0)}$</b> · تراجع <b className="font-mono text-loss/85" dir="ltr">−{s.maxDD.toFixed(0)}$</b></span>
                  <span className="font-mono font-bold text-corona" dir="ltr" title={minCapitalNote(s)}>${s.minCapital.toLocaleString("en-US")}</span>
                </div>
              </div>
            )
          })}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-corona/40 bg-corona/[0.06] px-6 py-5">
          <div>
            <div className="text-[17px] font-bold">التلات بوتات الأساسية مع بعض</div>
            <div className="mt-0.5 text-[13px] text-muted">ترند + مومنتم + شورت العملات الجديدة — نادراً ما بيخسروا في نفس الوقت</div>
          </div>
          <div className="flex gap-8 text-center">
            <div><div className="font-mono text-[22px] font-bold text-profit" dir="ltr">+{COMBINED.core.pnl.toFixed(0)}$</div><div className="text-[11px] text-faint">صافي الربح</div></div>
            <div><div className="font-mono text-[22px] font-bold text-loss/85" dir="ltr">−{COMBINED.core.maxDD.toFixed(0)}$</div><div className="text-[11px] text-faint">أقصى تراجع</div></div>
            <div><div className={`font-mono text-[22px] font-bold ${sharpeTone(COMBINED.core.sharpeOut)}`}>{COMBINED.core.sharpeOut.toFixed(2)}</div><div className="text-[11px] text-faint">Sharpe ‎2024+</div></div>
            <div><div className="font-mono text-[22px] font-bold text-corona" dir="ltr">${STRATEGIES.slice(0, 3).reduce((a, s) => a + s.minCapital, 0).toLocaleString("en-US")}</div><div className="text-[11px] text-faint">أقل رأس مال</div></div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-faint">
          <span>Sharpe = الربح مقارنةً بتقلّبه (فوق 1 كويس)</span>
          <span>· أقصى تراجع = أكبر نزول من قمة الأرباح</span>
          <span>· أقل رأس مال = هامش يكفي أقل صفقة تقبلها Binance (5$، وETH ‏20$، وBTC ‏50$) × أقصى صفقات مفتوحة + أكبر خسارة متتالية، على x2</span>
          <span>· نتايج سابقة على فلوس وهمية، مش ضمان لأي ربح</span>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className="mx-auto max-w-[1180px] px-5 py-20">
          <h2 className="text-center text-[30px] font-black">الباقات</h2>
          <p className="mt-2 text-center text-sm text-muted">ابدأ مجاناً بالترند اليومي، ورقّي وقت ما تحتاج بوتات أكتر</p>
          <div className="mt-10"><Pricing prices={prices}/></div>
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
          <p className="mt-2 text-sm text-muted">افتح المنصة مجاناً، وتابع البوتات شغالة لحظة بلحظة.</p>
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
              <FooterAuthLink/>
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

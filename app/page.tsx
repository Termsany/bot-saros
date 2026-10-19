import { Pricing } from "@/components/Pricing"
import { STRATEGIES } from "@/lib/strategies"
import { Activity, Wifi, ShieldCheck, Zap, TrendingUp, Layers } from "lucide-react"

export default function Page(){
  const heroStats = [
    { label: "زوج سيولة", value: "20", sub: "BTC · ETH · SOL · BNB" },
    { label: "استراتيجية", value: "15", sub: "ICT بطل BTC 4h" },
    { label: "أفضل فريم", value: "4h", sub: "PF ∞ · +10.48", highlight: true },
  ]

  return (
    <main className="min-h-screen bg-[#070B12] text-[#E8EEF5]">
      {/* Header — same as dashboard */}
      <header className="flex h-16 items-center justify-between border-b border-[#1c2632] bg-[#0a1018] px-5 lg:px-8 sticky top-0 z-30">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-[#00D395]/10 text-[#00D395]"><Activity size={18}/></div>
          <div><div className="text-sm font-semibold tracking-[0.18em]">BOT SAROS</div><div className="font-mono text-[9px] tracking-[0.2em] text-[#647386]">AUTONOMOUS TRADING TERMINAL</div></div>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden md:flex items-center gap-2 text-[11px] text-[#00D395] font-mono"><Wifi size={13}/> BINANCE SPOT <i className="h-1.5 w-1.5 rounded-full bg-[#00D395] animate-pulse"/></span>
          <a href="/auth" className="hidden md:block text-[11px] text-[#778597] hover:text-white px-3 py-1.5 rounded border border-[#1c2632]">دخول</a>
          <a href="/dashboard" className="px-4 py-2 rounded bg-[#00D395] text-[#062016] text-xs font-bold hover:bg-[#00b87a]">افتح المنصة</a>
        </div>
      </header>

      {/* Hero — Bloomberg style */}
      <section className="mx-auto max-w-[1600px] px-5 lg:px-8 pt-10 pb-6">
        <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-8 items-center">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-[#1c2632] bg-[#0c131c] px-3 py-1.5 text-[11px] font-mono text-[#00D395]"><span className="h-2 w-2 rounded-full bg-[#00D395] animate-pulse"/> FUTURES LONG/SHORT x5 — Paper وهمي</div>
            <h1 className="mt-4 text-4xl lg:text-5xl font-black tracking-tight leading-[0.95]">اختر استراتيجيتك.<br/><span className="text-[#00D395]">اختبرها.</span> اربح.</h1>
            <p className="mt-4 text-sm leading-relaxed text-[#8A9AB0] max-w-[560px]">15 استراتيجية — من الكلاسيكي إلى SMC و AI Ensemble. اختر ما يناسبك، اعمل Backtest لكل واحدة لوحدها وشوف نسبة الربح قبل ما تشترك.</p>
            <div className="mt-6 flex gap-3">
              <a href="/dashboard" className="px-6 py-3 rounded bg-[#00D395] text-[#062016] text-sm font-bold hover:bg-[#00b87a] flex items-center gap-2"><Zap size={14}/> جرّب مجانا</a>
              <a href="#strategies" className="px-6 py-3 rounded border border-[#1c2632] bg-[#0c131c] text-sm hover:bg-[#111a25]">شوف الاستراتيجيات</a>
            </div>
            <div className="mt-8 grid grid-cols-3 gap-3 max-w-[460px]">
              {heroStats.map(s=>(
                <div key={s.label} className={`rounded border p-3 ${s.highlight ? "border-[#00D395]/30 bg-[#0c131c]" : "border-[#1c2632] bg-[#0c131c]"}`}>
                  <div className="text-[10px] tracking-[0.14em] text-[#68778a]">{s.label}</div>
                  <div className={`mt-1 font-mono text-2xl font-black ${s.highlight?"text-[#00D395]":"text-white"}`}>{s.value}</div>
                  <div className="font-mono text-[10px] text-[#5f6e81]">{s.sub}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 15 strategies — terminal card grid */}
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-semibold tracking-[0.14em]">الـ 15 استراتيجية</h2>
              <span className="font-mono text-[10px] text-[#647386]">BTC 4h — WR / PF حقيقي</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {STRATEGIES.slice(0,15).map(s=>(
                <div key={s.id} className={`rounded border p-2.5 ${s.id==="ict" ? "border-[#00D395]/40 bg-[#00D395]/[0.06]" : "border-[#1d2936] bg-[#0a1018]"}`}>
                  <div className="flex justify-between items-start"><span className="text-sm">{s.icon}</span>{s.id==="ict" && <span className="h-2 w-2 rounded-full bg-[#00D395] animate-pulse"/>}</div>
                  <div className="mt-1 text-[11px] font-bold leading-tight">{s.nameAr}</div>
                  <div className="text-[10px] text-[#647386] leading-tight">{s.desc}</div>
                  <div className="mt-2 flex gap-1.5 font-mono text-[10px]"><span className={s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}>WR {s.winRate}%</span><span className="text-[#5f6e81]">PF {s.pf}</span></div>
                </div>
              ))}
            </div>
            <a href="/backtest" className="mt-3 flex items-center justify-center gap-2 rounded bg-[#00D395]/10 border border-[#00D395]/20 py-2 text-xs font-bold text-[#00D395] hover:bg-[#00D395]/15"><TrendingUp size={12}/> اختبر أي استراتيجية — /backtest</a>
          </div>
        </div>
      </section>

      {/* 8 المتطورة — same card style as dashboard */}
      <section id="strategies" className="mx-auto max-w-[1600px] px-5 lg:px-8 py-6">
        <div className="flex items-baseline gap-3 mb-1"><Layers size={14} className="text-[#00D395]"/><h2 className="text-sm font-semibold tracking-[0.14em]">الـ 8 المتطورة الجديدة</h2></div>
        <p className="font-mono text-[11px] text-[#647386]">SMC · VWAP · SuperTrend · Bollinger · Harmonic · ICT · Heikin · AI — كل واحدة Backtest لوحدها</p>
        <div className="grid md:grid-cols-4 gap-3 mt-4">
          {STRATEGIES.filter(s=>["smc","vwap","supertrend","bollinger","harmonic","ict","heikin","ai"].includes(s.id)).map(s=>(
            <div key={s.id} className={`rounded border p-4 ${s.id==="ict"?"border-[#00D395]/40 bg-[#0c131c]":"border-[#1c2632] bg-[#0c131c]"}`}>
              <div className="flex justify-between"><span className="text-xl">{s.icon}</span><span className={`h-2 w-2 rounded-full ${s.winRate>=45?"bg-[#00D395]":s.winRate>=35?"bg-[#FFB800]":"bg-[#FF3B5C]"}`}/></div>
              <div className="mt-2 text-xs font-bold">{s.nameAr} — {s.name}</div>
              <div className="font-mono text-[11px] text-[#647386] mt-1">{s.desc}</div>
              <div className="mt-3 flex gap-2 font-mono text-[10px]"><span className="rounded bg-[#00D395]/10 border border-[#00D395]/20 px-2 py-1 text-[#00D395]">WR {s.winRate}%</span><span className="rounded border border-[#1c2632] px-2 py-1 text-[#8A9AB0]">PF {s.pf}</span></div>
              <a href="/backtest" className="mt-3 block text-center rounded border border-[#1c2632] bg-[#0a1018] py-2 text-xs hover:bg-[#111a25]">اختبرها →</a>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing — same header style */}
      <section id="pricing" className="mx-auto max-w-[1600px] px-5 lg:px-8 py-8">
        <div className="flex items-center gap-2"><ShieldCheck size={14} className="text-[#00D395]"/><h2 className="text-sm font-semibold tracking-[0.14em]">الباقات</h2><span className="font-mono text-[11px] text-[#647386]">— كل باقة بعدد استراتيجيات مختلف</span></div>
        <div className="mt-4"><Pricing/></div>
      </section>

      <footer className="mx-auto max-w-[1600px] px-5 lg:px-8 border-t border-[#1c2632] mt-6 py-6 flex flex-wrap justify-between gap-3 font-mono text-[11px] text-[#5f6e81]">
        <span>Bot Saros © 2026 — هوية مستقلة — 15 استراتيجية + Backtest + Futures LONG/SHORT</span>
        <span>ENGINE STATUS <b className="text-[#00D395]">● OPERATIONAL</b> · bot-saros.vercel.app</span>
      </footer>
    </main>
  )
}

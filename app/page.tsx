import { Pricing } from "@/components/Pricing"
import { LiveTicker } from "@/components/LiveTicker"
import { STRATEGIES } from "@/lib/strategies"

export default function Page(){
  return (
    <main>
      {/* Nav */}
      <header className="sticky top-0 z-20 backdrop-blur bg-[#070B12]/80 border-b border-[#1E2A3A]">
        <div className="max-w-[1200px] mx-auto px-4 py-3 flex justify-between items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-[#00D395] grid place-items-center font-black text-[#062016] text-sm">S</div>
            <div>
              <div className="font-black text-sm leading-none">Bot Saros</div>
              <div className="text-[10px] text-[#8A9AB0]">AI Futures Terminal — 15 Strategies</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <LiveTicker/>
            <a href="/auth" className="px-3 py-1.5 rounded-xl border border-[#1E2A3A] text-xs">دخول</a>
            <a href="/dashboard" className="px-3 py-1.5 rounded-xl bg-[#00D395] text-[#062016] text-xs font-bold">افتح المنصة</a>
            <a href="#pricing" className="px-3 py-1.5 rounded-xl border border-[#1E2A3A] text-xs">الأسعار</a>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-[1200px] mx-auto px-4 py-10 grid md:grid-cols-2 gap-8 items-center">
        <div>
          <div className="inline-flex items-center gap-2 text-[11px] px-2 py-1 rounded-full border border-[#1E2A3A] bg-[#111827]"><span className="w-2 h-2 rounded-full bg-[#00D395] animate-pulse"/> FUTURES LONG/SHORT x5 — Paper وهمي</div>
          <h1 className="text-3xl md:text-4xl font-black mt-3 leading-tight">اختر استراتيجيتك.<br/><span className="text-[#00D395]">اختبرها.</span> اربح.</h1>
          <p className="text-sm text-[#8A9AB0] mt-3">15 استراتيجية — من الكلاسيكي إلى SMC و AI Ensemble. اختر ما يناسبك، اعمل Backtest لكل واحدة لوحدها وشوف نسبة الربح قبل ما تشترك.</p>
          <div className="flex gap-2 mt-5">
            <a href="/dashboard" className="px-5 py-2.5 rounded-xl bg-[#00D395] text-[#062016] text-sm font-bold">جرّب مجانا</a>
            <a href="#strategies" className="px-5 py-2.5 rounded-xl border border-[#1E2A3A] text-sm">شوف الاستراتيجيات</a>
          </div>
          <div className="flex gap-4 mt-6 text-xs">
            <span><b className="text-white">20</b> <span className="text-[#8A9AB0]">زوج سيولة</span></span>
            <span><b className="text-white">15</b> <span className="text-[#8A9AB0]">استراتيجية</span></span>
            <span><b className="text-[#00D395]">4h ⭐</b> <span className="text-[#8A9AB0]">أفضل فريم +12.7</span></span>
          </div>
        </div>
        <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
          <div className="text-xs font-bold mb-2">الـ 15 استراتيجية — اختر واختبر</div>
          <div className="grid grid-cols-3 gap-1.5">
            {STRATEGIES.slice(0,15).map(s=>(
              <div key={s.id} className="rounded-xl border border-[#1E2A3A] bg-[#0E141D] p-2">
                <div className="text-[11px] font-bold">{s.nameAr}</div>
                <div className="text-[10px] text-[#8A9AB0]">{s.desc}</div>
                <div className="text-[10px] mt-1"><span className={s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}>WR {s.winRate}%</span> <span className="text-[#8A9AB0]">PF {s.pf}</span></div>
              </div>
            ))}
          </div>
          <div className="text-[11px] text-center mt-2 text-[#8A9AB0]">كل كارت عليه نسبة الربح الحقيقية من Backtest BTC 4h</div>
        </div>
      </section>

      {/* Strategies detail */}
      <section id="strategies" className="max-w-[1200px] mx-auto px-4 py-8">
        <h2 className="text-lg font-black">الـ 8 المتطورة الجديدة</h2>
        <p className="text-xs text-[#8A9AB0] mt-1">SMC و VWAP و SuperTrend و Bollinger و Harmonic و ICT و Heikin و AI — كل واحدة Backtest لوحدها</p>
        <div className="grid md:grid-cols-4 gap-3 mt-4">
          {STRATEGIES.filter(s=>["smc","vwap","supertrend","bollinger","harmonic","ict","heikin","ai"].includes(s.id)).map(s=>(
            <div key={s.id} className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-4">
              <div className="text-lg">{s.icon}</div>
              <div className="font-bold text-sm mt-1">{s.nameAr} — {s.name}</div>
              <div className="text-xs text-[#8A9AB0] mt-1">{s.desc}</div>
              <div className="flex gap-2 mt-2 text-xs"><span className="px-2 py-1 rounded-full bg-[#0A2E1A] text-[#00D395]">WR {s.winRate}%</span><span className="px-2 py-1 rounded-full bg-[#1E2A3A]">PF {s.pf}</span></div>
              <a href="/backtest" className="mt-3 block text-center text-xs py-1.5 rounded-xl border border-[#1E2A3A]">اختبرها →</a>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="max-w-[1200px] mx-auto px-4 py-8">
        <h2 className="text-lg font-black">الباقات — عدّلها كما تريد</h2>
        <p className="text-xs text-[#8A9AB0]">كل باقة بعدد استراتيجيات مختلف — التسعير قابل للتعديل من لوحة التحكم</p>
        <div className="mt-4"><Pricing/></div>
      </section>

      <footer className="border-t border-[#1E2A3A] mt-8 py-6 text-center text-xs text-[#8A9AB0]">
        Bot Saros © 2026 — هوية مستقلة عن Elite Skin — مبني على 15 استراتيجية + Backtest + Futures LONG/SHORT
      </footer>
    </main>
  )
}

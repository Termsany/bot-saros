import { Pricing } from "@/components/Pricing"
import { BRAND } from "@/lib/brand"
import { STRATEGIES } from "@/lib/strategies"
import { Logo } from "@/components/Logo"
import { ArrowUpRight, Check, ShieldCheck, Zap } from "lucide-react"

export default function Page(){
  return (
    <main className="min-h-screen bg-[#070B12] text-[#E8EEF8]">
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-[#1c2632] bg-[#0a1018]/90 backdrop-blur px-5 lg:px-8">
        <Logo />
        <div className="flex items-center gap-2">
          <a href="/backtest" className="hidden md:block text-xs text-[#8A9AB0] hover:text-white px-3">Backtest</a>
          <a href="/auth" className="hidden md:block text-xs text-[#8A9AB0] hover:text-white px-3">دخول</a>
          <a href="/dashboard" className="rounded bg-[#00D395] px-4 py-2 text-xs font-bold text-[#062016] hover:bg-[#00b87a]">افتح المنصة</a>
        </div>
      </header>

      {/* HERO — clean, one message, generous whitespace */}
      <section className="mx-auto max-w-[1100px] px-5 lg:px-8 pt-16 pb-10 text-center">
        <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-[#1c2632] bg-[#0c131c] px-3 py-1.5 font-mono text-[11px] text-[#00D395]"><span className="h-1.5 w-1.5 rounded-full bg-[#00D395] animate-pulse"/> FUTURES LONG / SHORT x5 — Paper</div>
        <h1 className="mx-auto mt-6 max-w-[720px] text-4xl font-black leading-[1.05] tracking-tight lg:text-5xl">منصة واحدة.<br/> <span className="text-[#00D395]">15 استراتيجية.</span> قرار واحد.</h1>
        <p className="mx-auto mt-4 max-w-[520px] text-sm leading-relaxed text-[#8A9AB0]">اختبر كل استراتيجية على حدة ببيانات Binance الحقيقية — قبل ما تدفع. ICT بطل BTC 4h: PF ∞ · +10.48</p>
        <div className="mt-7 flex justify-center gap-3">
          <a href="/dashboard" className="inline-flex items-center gap-2 rounded bg-[#00D395] px-7 py-3 text-sm font-bold text-[#062016] hover:bg-[#00b87a]"><Zap size={15}/> جرّب مجانا</a>
          <a href="/backtest" className="rounded border border-[#1c2632] bg-[#0c131c] px-7 py-3 text-sm hover:bg-[#111a25]">شغّل Backtest</a>
        </div>
        <div className="mx-auto mt-10 grid max-w-[560px] grid-cols-3 gap-3 text-center">
          {[
            ["20", "زوج سيولة", "BTC · ETH · SOL"],
            ["15", "استراتيجية", "من كلاسيكي لـ AI"],
            ["4h", "أفضل فريم", "PF ∞"],
          ].map(([v,l,s])=>(
            <div key={l} className="rounded-xl border border-[#1c2632] bg-[#0c131c] p-4">
              <div className="font-mono text-2xl font-black text-white">{v}</div>
              <div className="text-xs font-bold mt-1">{l}</div>
              <div className="font-mono text-[11px] text-[#5f6e81] mt-0.5">{s}</div>
            </div>
          ))}
        </div>
      </section>

      {/* STRATEGIES — table, not 15 tiny cards */}
      <section id="strategies" className="mx-auto max-w-[1100px] px-5 lg:px-8 py-8">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-bold tracking-[0.14em]">الـ 15 استراتيجية</h2>
          <a href="/backtest" className="font-mono text-xs text-[#00D395] hover:underline flex items-center gap-1">اختبر أي واحدة <ArrowUpRight size={12}/></a>
        </div>
        <p className="font-mono text-xs text-[#647386] mt-1">كل صف = استراتيجية + وصف + WR/PF من BTC 4h حقيقي · ICT مميزة</p>

        <div className="mt-4 overflow-hidden rounded-xl border border-[#1c2632]">
          <table className="w-full text-sm">
            <thead className="bg-[#0a1018] font-mono text-[11px] tracking-[0.12em] text-[#5f6e81]">
              <tr><th className="px-4 py-3 text-right font-normal">الاستراتيجية</th><th className="px-4 py-3 text-right font-normal hidden md:table-cell">الطريقة</th><th className="px-4 py-3 text-center font-normal">WR</th><th className="px-4 py-3 text-center font-normal">PF</th><th className="px-4 py-3"></th></tr>
            </thead>
            <tbody className="divide-y divide-[#1c2632]">
              {STRATEGIES.slice(0,15).map(s=>(
                <tr key={s.id} className={s.id==="ict" ? "bg-[#00D395]/[0.06]" : "bg-[#0c131c] hover:bg-[#111a25]"}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <span className="text-lg leading-none">{s.icon}</span>
                      <div><div className="font-bold text-sm leading-none">{s.nameAr} <span className="font-normal text-[#647386]">— {s.name}</span>{s.id==="ict" && <span className="ml-2 rounded-full bg-[#00D395] px-2 py-0.5 font-mono text-[10px] font-bold text-[#062016]">بطل</span>}</div>
                      <div className="font-mono text-xs text-[#8A9AB0] md:hidden mt-0.5">{s.desc}</div></div>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#8A9AB0] hidden md:table-cell">{s.desc}</td>
                  <td className="px-4 py-3 text-center"><span className={`font-mono text-sm font-bold ${s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}`}>{s.winRate}%</span></td>
                  <td className="px-4 py-3 text-center font-mono text-sm text-[#8A9AB0]">{s.pf}</td>
                  <td className="px-4 py-3 text-center"><a href="/backtest" className="text-xs text-[#647386] hover:text-white">اختبر →</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center gap-4 font-mono text-[11px] text-[#5f6e81]"><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#00D395]"/> WR ≥45%</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#FFB800]"/> 35-44%</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#FF3B5C]"/> &lt;35%</span><span className="ml-auto">Binance 4h · 300 شمعة</span></div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="mx-auto max-w-[1100px] px-5 lg:px-8 py-10">
        <h2 className="text-center text-sm font-bold tracking-[0.14em]">الباقات</h2>
        <p className="text-center font-mono text-xs text-[#647386] mt-1">ابدأ مجانا — حدّث وقت ما تحب</p>
        <div className="mt-6"><Pricing/></div>
        <div className="mt-4 flex justify-center gap-6 font-mono text-[11px] text-[#5f6e81]"><span className="flex items-center gap-1.5"><Check size={12} className="text-[#00D395]"/> إلغاء في أي وقت</span><span className="flex items-center gap-1.5"><ShieldCheck size={12} className="text-[#00D395]"/> دفع آمن Stripe</span></div>
      </section>

      <footer className="mx-auto max-w-[1100px] px-5 lg:px-8 border-t border-[#1c2632] py-6 flex flex-wrap justify-between gap-3 font-mono text-[11px] text-[#5f6e81]">
        <span>{BRAND.footer}</span>
        <span>ENGINE <b className="text-[#00D395]">● OPERATIONAL</b> · {BRAND.domain}</span>
      </footer>
    </main>
  )
}

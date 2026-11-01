"use client"
import { useEffect, useState } from "react"
import { apiLiveMeasurement } from "@/lib/api"
import { Card, CardHeader, Pill, type Tone } from "@/components/ui"

const STATUS: Record<string, [string, Tone]> = {
  collecting: ["بيجمّع", "neutral"], in_range: ["في المدى", "profit"], attention: ["محتاج نظرة", "corona"],
  far: ["بعيدة — تتقفل", "loss"], not_measured: ["مش بتتقاس", "neutral"],
}

const pct = (v?: number|null) => v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`
const num = (v?: number|null) => v == null ? "—" : String(v)

/** Demo against the backtest baseline, per strategy (owner, 2026-11-01): only the strategies' own exits since the
 *  measurement started, in % of the trade's margin like the baseline. Sample and rules were agreed before any result:
 *  30 trades (15 for the slow ones); after its sample a strategy is switched off — not re-tuned — when its profit
 *  factor is under 1 or its drawdown is over 1.5 × the baseline's. */
export function DemoMeasurement({ labels }: { labels: Record<string, string> }){
  const [m, setM] = useState<any|null|undefined>(undefined)
  useEffect(() => {
    const load = () => apiLiveMeasurement().then(setM)
    load(); const t = setInterval(load, 300_000); return () => clearInterval(t)
  }, [])
  if(m === undefined) return null
  if(m === null) return <Card><p className="py-6 text-center text-[13px] text-faint">القياس مش متاح دلوقتي</p></Card>

  const rows = Object.entries(m.strategies || {}) as [string, any][]
  const pair = (demo: string, base: string) => (
    <div dir="ltr" style={{ textAlign: "right" }}><span className="font-mono font-semibold tabular">{demo}</span>
      <span className="font-mono text-[11px] text-faint tabular"> / {base}</span></div>
  )
  return (
    <Card>
      <CardHeader title="الـ Demo قدام الـ backtest"
        sub={`صفقات الاستراتيجيات نفسها من ${new Date(m.start).toLocaleDateString("ar-EG")} — من غير القفل اليدوي. كل رقم: الـ Demo / الجدول، نسبة من مارجن الصفقة.`} />
      {!m.baseline_available && <p className="mb-3 text-[12px] text-loss">جدول الـ backtest مش موجود على السيرفر</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[13px]">
          <thead className="text-[12px] text-faint">
            <tr>{["الاستراتيجية", "العينة", "نسبة الكسب", "متوسط الكسب", "متوسط الخسارة", "Profit factor", "أسوأ تراجع (مارجن)", "صفقات/شهر", "الحالة"]
              .map(h => <th key={h} className="px-2 py-2 text-right font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(([s, r]) => {
              const d = r.demo || {}, b = r.baseline || {}, [st, tone] = STATUS[r.status] || [r.status, "neutral"]
              const done = r.sample ? Math.min(100, d.trades / r.sample * 100) : 0
              return (
                <tr key={s} className="border-t border-line align-top">
                  <td className="px-2 py-3 text-[14px] font-semibold">{labels[s] || s}</td>
                  <td className="px-2 py-3">
                    {r.sample ? <>
                      <div className="font-mono tabular" dir="ltr" style={{ textAlign: "right" }}>{d.trades} / {r.sample}</div>
                      <div className="mt-1 h-1.5 w-20 overflow-hidden rounded-full bg-surface2"><div className="h-full bg-signal" style={{ width: `${done}%` }} /></div>
                    </> : <span className="text-muted">—</span>}
                  </td>
                  <td className="px-2 py-3">{pair(d.win_rate == null ? "—" : `${d.win_rate}%`, b.win_rate == null ? "—" : `${b.win_rate}%`)}</td>
                  <td className="px-2 py-3">{pair(pct(d.avg_win_pct), pct(b.avg_win_pct))}</td>
                  <td className="px-2 py-3">{pair(pct(d.avg_loss_pct), pct(b.avg_loss_pct))}</td>
                  <td className="px-2 py-3">{pair(num(d.profit_factor), num(b.profit_factor))}</td>
                  <td className="px-2 py-3">{pair(num(d.max_dd_margins), num(b.max_dd_margins))}</td>
                  <td className="px-2 py-3">{pair(d.days >= 14 ? num(d.per_month) : "بدري", num(b.per_month))}</td>
                  <td className="px-2 py-3">
                    <Pill tone={tone}>{st}</Pill>
                    {(r.reasons || []).map((x: string) => <div key={x} className="mt-1 max-w-[220px] text-[11px] text-muted">{x}</div>)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[12px] text-faint">
        العينة 30 صفقة (15 لـ RSI-2 وشورت العملات الجديدة). بعد العينة: الـ profit factor أقل من 1 أو التراجع أكتر من {m.dd_limit}× الجدول = الاستراتيجية تتقفل، مش تتعدّل.
        «محتاج نظرة» تنبيه بس، مش حكم. الأرقام دي backtest: مش ضمان.
      </p>
    </Card>
  )
}

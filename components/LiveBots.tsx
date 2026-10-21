"use client"
import { ExternalLink } from "lucide-react"
import { BOT_PAGE } from "@/lib/strategies"
import { ago, type LiveBot } from "@/lib/live-bots"

const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const tone = (v: number) => v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const px = (v?: number) => v === undefined || v === null ? "—" : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })

/** The four paper bots on the VPS, live (data refreshed by useLiveBots in the parent). */
export function LiveBots({ bots, loaded }: { bots: LiveBot[], loaded: boolean }){
  return (
    <section id="live-bots" className="scroll-mt-6 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold">البوتات شغالة دلوقتي</h2>
          <p className="text-[13px] text-muted">الـ 4 بوتات على السيرفر — Paper (فلوس وهمية)، بتتحدث كل 15 ثانية</p>
        </div>
        <a href={BOT_PAGE} target="_blank" rel="noopener" className="flex items-center gap-1 text-sm font-semibold text-corona hover:underline">صفحة البوتات بالأسعار اللحظية <ExternalLink size={14}/></a>
      </div>
      {!loaded ? <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-faint">بيحمّل البوتات…</div> : (
        <div className="grid gap-3 lg:grid-cols-2">
          {bots.map(b => {
            const s = b.strategy, total = b.realized + b.unrealized
            const top = [...b.positions].sort((x, y) => Math.abs(y.pnl) - Math.abs(x.pnl)).slice(0, 5)
            return (
              <div key={s.id} className={`flex flex-col rounded-2xl border bg-surface p-4 ${s.risk === "high" ? "border-loss/35" : "border-line"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-bold">{s.nameAr}</span>
                      {s.risk === "high" && <span className="rounded-full border border-loss/45 bg-loss/10 px-2 py-0.5 text-[10px] font-bold text-loss">⚠️ HIGH RISK</span>}
                    </div>
                    <div className="text-xs text-muted">{s.desc} · {s.sides}</div>
                  </div>
                  <span className={`flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[11px] font-bold ${!b.ok ? "text-loss" : b.fresh ? "text-profit" : "text-corona"}`}>
                    <i className={`h-1.5 w-1.5 rounded-full ${!b.ok ? "bg-loss" : b.fresh ? "animate-pulse bg-profit" : "bg-corona"}`}/>
                    {!b.ok ? "مش متاح" : b.fresh ? "شغال" : `آخر تحديث ${ago(b.updated)}`}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  {[["محقق", b.realized], ["مفتوح", b.unrealized], ["الإجمالي", total]].map(([k, v]) => (
                    <div key={k as string} className="rounded-xl bg-surface2/60 py-2">
                      <div className="text-[11px] text-muted">{k}</div>
                      <div className={`font-mono text-sm font-bold tabular ${tone(v as number)}`} dir="ltr">{money(v as number)}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap justify-between gap-2 text-[11px] text-faint">
                  <span>{b.open} مفتوحة · {b.closed} اتقفلت ({b.wins} كسبانة / {b.losses} خسرانة)</span>
                  {b.note && <span className="truncate">{b.note}</span>}
                </div>
                <div className="mt-3 flex-1 overflow-x-auto">
                  {top.length === 0 ? <div className="py-4 text-center text-xs text-faint">مفيش صفقات مفتوحة دلوقتي</div> : (
                    <table className="w-full text-[12px]">
                      <tbody>
                        {top.map(p => (
                          <tr key={p.label + p.side} className="border-t border-line/70">
                            <td className="py-1.5 font-bold" dir="ltr" style={{ textAlign: "right" }}>{p.label}</td>
                            <td className="py-1.5">
                              {p.side === "pair" ? <span className="text-faint">{p.detail}</span>
                                : <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${p.side === "long" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{p.side.toUpperCase()}</span>}
                            </td>
                            <td className="py-1.5 font-mono text-muted tabular" dir="ltr" style={{ textAlign: "right" }}>{p.price !== undefined ? `${px(p.entry)} → ${px(p.price)}` : ""}</td>
                            <td className={`py-1.5 font-mono font-bold tabular ${tone(p.pnl)}`} dir="ltr" style={{ textAlign: "right" }}>{money(p.pnl)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {b.positions.length > top.length && <div className="pt-1.5 text-[11px] text-faint">+ {b.positions.length - top.length} تانيين على <a href={BOT_PAGE} target="_blank" rel="noopener" className="text-corona hover:underline">صفحة البوتات</a></div>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

"use client"
import { useCallback, useEffect, useState } from "react"
import { apiLiveClose, apiLiveCloseResult, apiLiveStatus } from "@/lib/api"
import { ago } from "@/lib/live-bots"

const money = (v?: number|null) => v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const tone = (v?: number|null) => !v ? "text-muted" : v > 0 ? "text-profit" : "text-loss"
const px = (v?: number|null) => v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })
const pct = (from?: number|null, to?: number|null) => from && to ? `${((to / from - 1) * 100).toFixed(1)}%` : ""

/** The real-orders bot (daily trend, Binance) for the admin: every position with its stop and exit level, and a
 *  button that asks the bot to close it. The backend allows this to the admin only; the bot only ever closes. */
export function LivePositions(){
  const [st, setSt] = useState<any|null|undefined>(undefined)
  const [busy, setBusy] = useState<Record<string, string>>({})
  const load = useCallback(async () => setSt(await apiLiveStatus()), [])
  useEffect(() => { load(); const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])

  async function close(symbol: string){
    if(!confirm(`تقفل ${symbol} دلوقتي بسعر السوق؟\nالبوت مش هيشتريها تاني غير لما الترند يقف ويبدأ من جديد.`)) return
    setBusy(b => ({ ...b, [symbol]: "بيبعت الطلب…" }))
    try{
      const { id } = await apiLiveClose(symbol)
      setBusy(b => ({ ...b, [symbol]: "البوت بيقفل (لحد دقيقة)…" }))
      for(let i = 0; i < 50; i++){                          // the bot runs every minute; a request expires after 10
        await new Promise(r => setTimeout(r, 3000))
        const r = await apiLiveCloseResult(id)
        if(r.done){
          setBusy(b => ({ ...b, [symbol]: r.ok ? `✅ اتقفلت @ ${px(r.price)} · ${money(r.pnl)}` : `⚠️ ${r.msg}` }))
          load(); return
        }
      }
      setBusy(b => ({ ...b, [symbol]: "⚠️ البوت ما ردّش — اتأكد من Binance" }))
    }catch(e: any){ setBusy(b => ({ ...b, [symbol]: `⚠️ ${e.message}` })) }
  }

  if(st === undefined) return <div className="mt-6 text-xs text-faint">بيحمّل الصفقات الحقيقية…</div>
  if(st === null) return null                                // not the admin (the backend refuses everyone else)
  const env = st.env === "live" ? "فلوس حقيقية" : st.env === "demo" ? "Binance Demo" : st.env || ""
  return (
    <div className="mt-6 rounded-2xl border border-corona/40 bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-black">الترند اليومي — أوامر حقيقية {env && <span className="mr-1 rounded-full bg-corona/15 px-2 py-0.5 text-[11px] text-corona">{env}</span>}</h2>
        <span className={`text-[11px] ${st.running ? "text-profit" : "text-loss"}`}>{st.running ? `شغال · آخر تحديث ${ago(st.updated)}` : "البوت مش شغال"}</span>
      </div>
      {st.entry_block && <div className="mt-2 rounded-lg bg-loss/10 px-3 py-2 text-xs text-loss">⛔ الدخول متوقف: {st.entry_block}</div>}
      {st.review && Object.keys(st.review).length > 0 && <div className="mt-2 rounded-lg bg-loss/10 px-3 py-2 text-xs text-loss">🚨 محتاج مراجعة: {Object.entries(st.review).map(([k, v]: any) => `${k.split(":")[0]} (${v.reason})`).join(" · ")}</div>}
      {!st.positions?.length ? <div className="py-6 text-center text-xs text-faint">مفيش صفقات مفتوحة</div> : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead className="text-faint"><tr className="text-right">
              <th className="p-2">العملة</th><th className="p-2">دخول → الآن</th><th className="p-2">الربح</th>
              <th className="p-2 text-loss">وقف الخسارة (على Binance)</th><th className="p-2 text-profit">الهدف / الخروج</th><th className="p-2"></th>
            </tr></thead>
            <tbody>
              {st.positions.map((p: any) => (
                <tr key={p.symbol} className="border-t border-line/70 align-top">
                  <td className="p-2 font-bold" dir="ltr" style={{ textAlign: "right" }}>{p.symbol}{p.unprotected && <div className="text-[10px] text-loss">من غير وقف!</div>}</td>
                  <td className="p-2 font-mono tabular" dir="ltr" style={{ textAlign: "right" }}>{px(p.entry)} → {px(p.price)}<div className="text-[10px] text-faint">{ago(p.opened)}</div></td>
                  <td className={`p-2 font-mono font-bold tabular ${tone(p.pnl)}`} dir="ltr" style={{ textAlign: "right" }}>{money(p.pnl)}</td>
                  <td className="p-2">
                    <span className="font-mono text-loss" dir="ltr">{px(p.sl)}</span> <span className="text-faint">({pct(p.price, p.sl)})</span>
                    <div className="text-[10px] text-faint">لو اتضرب: {money(p.loss_at_sl)}{p.sl_unverified && <span className="text-loss"> · مش متأكدين إنه على Binance</span>}</div>
                  </td>
                  <td className="p-2">
                    {p.exit_below ? <><span className="text-profit">لو قفل يومي تحت <span className="font-mono" dir="ltr">{px(p.exit_below)}</span></span> <span className="text-faint">({pct(p.price, p.exit_below)})</span></>
                      : <span className="text-profit">لما الترند يقف</span>}
                    <div className="text-[10px] text-faint">مفيش هدف سعر ثابت — بيسيب الربح يجري لحد ما الترند يقف</div>
                  </td>
                  <td className="p-2 text-left">
                    <button onClick={() => close(p.symbol)} disabled={!!busy[p.symbol] && !busy[p.symbol].startsWith("⚠️")}
                      className="rounded-lg border border-loss/50 px-3 py-1.5 text-xs font-bold text-loss hover:bg-loss/10 disabled:opacity-50">اقفل</button>
                    {busy[p.symbol] && <div className="mt-1 max-w-[160px] text-[10px] text-muted">{busy[p.symbol]}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {st.history?.length > 0 && (
        <details className="mt-3 text-xs"><summary className="cursor-pointer text-muted">آخر الصفقات المقفولة ({st.history.length})</summary>
          <table className="mt-2 w-full">
            <tbody>{st.history.map((h: any, i: number) => (
              <tr key={i} className="border-t border-line/60">
                <td className="p-1.5 font-bold" dir="ltr" style={{ textAlign: "right" }}>{String(h.symbol).split(":")[0]}</td>
                <td className="p-1.5 font-mono" dir="ltr" style={{ textAlign: "right" }}>{px(h.entry)} → {px(h.exit)}</td>
                <td className={`p-1.5 font-mono ${tone(h.pnl)}`} dir="ltr" style={{ textAlign: "right" }}>{money(h.pnl)}</td>
                <td className="p-1.5 text-muted">{h.reason}</td><td className="p-1.5 text-faint">{ago(h.time)}</td>
              </tr>))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}

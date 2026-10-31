"use client"
import { useState } from "react"
import { apiLiveClose, apiLiveCloseResult } from "@/lib/api"
import { ago } from "@/lib/live-bots"
import { Card, Dot, Pill } from "@/components/ui"

const money = (v?: number|null) => v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const tone = (v?: number|null) => !v ? "text-muted" : v > 0 ? "text-profit" : "text-loss"
const px = (v?: number|null) => v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })
const pct = (from?: number|null, to?: number|null) => from && to ? `${((to / from - 1) * 100).toFixed(1)}%` : ""

function Banner({ t, children }: { t: "loss" | "corona" | "neutral", children: React.ReactNode }){
  const cls = t === "loss" ? "border-loss/30 bg-loss/10 text-loss" : t === "corona" ? "border-corona/30 bg-corona/10 text-corona" : "border-line bg-surface2 text-muted"
  return <div className={`mt-3 rounded-[10px] border px-3 py-2 text-[12px] ${cls}`}>{children}</div>
}

/** Why this bot isn't trading: a refusal from its last few cycles, or else it is only waiting for its signal. */
function WhyNoTrade({ st }: { st: any }){
  if(!st.running || st.entry_block) return null
  const b = st.last_block
  const recent = b?.at && Date.now() - new Date(b.at).getTime() < 10 * 60_000   // the bots run every minute
  if(recent) return <Banner t="corona">آخر رفض ({ago(b.at)}): {b.reason}</Banner>
  return (
    <Banner t="neutral">
      مستني إشارة — مفيش حاجة مانعة الدخول
      {b?.at && <div className="mt-0.5 text-[11px] text-faint">آخر رفض كان {ago(b.at)}: {b.reason}</div>}
    </Banner>
  )
}

/** One real-orders bot (one strategy, Binance) for the admin: every position with its stop and exit level, and a
 *  button that asks that bot to close it. The backend allows this to the admin only; the bot only ever closes. */
export function LivePositions({ strategy, label, st, reload }: { strategy: string, label: string, st: any, reload: () => void }){
  const [busy, setBusy] = useState<Record<string, string>>({})

  async function close(symbol: string){
    if(!confirm(`تقفل ${symbol} (${label}) دلوقتي بسعر السوق؟`)) return
    setBusy(b => ({ ...b, [symbol]: "بيبعت الطلب…" }))
    try{
      const { id } = await apiLiveClose(strategy, symbol)
      setBusy(b => ({ ...b, [symbol]: "البوت بيقفل (لحد دقيقة)…" }))
      for(let i = 0; i < 50; i++){                          // the bot runs every minute; a request expires after 10
        await new Promise(r => setTimeout(r, 3000))
        const r = await apiLiveCloseResult(strategy, id)
        if(r.done){
          setBusy(b => ({ ...b, [symbol]: r.ok ? `✅ اتقفلت @ ${px(r.price)} · ${money(r.pnl)}` : `⚠️ ${r.msg}` }))
          reload(); return
        }
      }
      setBusy(b => ({ ...b, [symbol]: "⚠️ البوت ما ردّش — اتأكد من Binance" }))
    }catch(e: any){ setBusy(b => ({ ...b, [symbol]: `⚠️ ${e.message}` })) }
  }

  if(!st) return null
  const env = st.env === "live" ? "فلوس حقيقية" : st.env === "demo" ? "Binance Demo" : st.env || ""
  const total = ((st.positions || []) as any[]).reduce((a, p) => a + (Number(p.pnl) || 0), 0)
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-[16px] font-bold">{label}</h3>
          {env && <Pill tone={st.env === "live" ? "loss" : "corona"}>{env}</Pill>}
          <span className="flex items-center gap-1.5 text-[12px] text-muted"><Dot tone={st.running ? "profit" : "loss"} pulse={st.running}/>{st.running ? `شغال · آخر تحديث ${ago(st.updated)}` : "البوت مش شغال"}</span>
        </div>
        {st.positions?.length > 0 && <span className="text-[12px] text-muted">{st.positions.length} مفتوحة · <b className={`font-mono tabular ${tone(total)}`} dir="ltr">{money(total)}</b></span>}
      </div>
      {st.entry_block && <Banner t="loss">الدخول متوقف: {st.entry_block}</Banner>}
      <WhyNoTrade st={st} />
      {st.review && Object.keys(st.review).length > 0 && <Banner t="loss">محتاج مراجعة: {Object.entries(st.review).map(([k, v]: any) => `${k.split(":")[0]} (${v.reason})`).join(" · ")}</Banner>}
      {!st.positions?.length ? <div className="py-6 text-center text-[13px] text-faint">مفيش صفقات مفتوحة</div> : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-[13px]">
            <thead className="text-[12px] text-faint"><tr className="text-right">
              <th className="px-2 py-2 font-semibold">العملة</th><th className="px-2 py-2 font-semibold">دخول → الآن</th><th className="px-2 py-2 font-semibold">الربح</th>
              <th className="px-2 py-2 font-semibold">وقف الخسارة (على Binance)</th><th className="px-2 py-2 font-semibold">الخروج</th><th className="px-2 py-2"></th>
            </tr></thead>
            <tbody>
              {st.positions.map((p: any) => (
                <tr key={p.symbol} className="border-t border-line align-top">
                  <td className="px-2 py-3 font-semibold" dir="ltr" style={{ textAlign: "right" }}>
                    {p.symbol}
                    <div className="mt-1 flex justify-end gap-1">{p.side === "short" ? <Pill tone="loss">SHORT</Pill> : <Pill tone="profit">LONG</Pill>}{p.unprotected && <Pill tone="loss">من غير وقف!</Pill>}</div>
                  </td>
                  <td className="px-2 py-3 font-mono tabular" dir="ltr" style={{ textAlign: "right" }}>{px(p.entry)} → {px(p.price)}<div className="text-[11px] text-faint">{ago(p.opened)}</div></td>
                  <td className={`px-2 py-3 font-mono font-semibold tabular ${tone(p.pnl)}`} dir="ltr" style={{ textAlign: "right" }}>{money(p.pnl)}</td>
                  <td className="px-2 py-3">
                    <span className="font-mono text-loss" dir="ltr">{px(p.sl)}</span> <span className="text-faint">({pct(p.price, p.sl)})</span>
                    <div className="text-[11px] text-faint">لو اتضرب: {money(p.loss_at_sl)}{p.sl_unverified && <span className="text-loss"> · مش متأكدين إنه على Binance</span>}</div>
                  </td>
                  <td className="px-2 py-3">
                    {p.exit_below ? <><span className="text-muted">لو قفل يومي تحت <span className="font-mono text-ink" dir="ltr">{px(p.exit_below)}</span></span> <span className="text-faint">({pct(p.price, p.exit_below)})</span></>
                      : <span className="text-muted">على قاعدة الاستراتيجية</span>}
                  </td>
                  <td className="px-2 py-3 text-left">
                    <button onClick={() => close(p.symbol)} disabled={!!busy[p.symbol] && !busy[p.symbol].startsWith("⚠️")}
                      className="rounded-xl border border-loss/40 px-3.5 py-1.5 text-[13px] font-semibold text-loss transition hover:bg-loss/10 disabled:opacity-40">اقفل</button>
                    {busy[p.symbol] && <div className="mt-1 max-w-[160px] text-[11px] text-muted">{busy[p.symbol]}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {st.history?.length > 0 && (
        <details className="mt-3 rounded-[10px] bg-surface2 px-3 py-2 text-[13px]"><summary className="cursor-pointer text-muted">آخر الصفقات المقفولة ({st.history.length})</summary>
          <table className="mt-2 w-full">
            <tbody>{st.history.map((h: any, i: number) => (
              <tr key={i} className="border-t border-line">
                <td className="px-1.5 py-2 font-semibold" dir="ltr" style={{ textAlign: "right" }}>{String(h.symbol).split(":")[0]}</td>
                <td className="px-1.5 py-2 font-mono tabular" dir="ltr" style={{ textAlign: "right" }}>{px(h.entry)} → {px(h.exit)}</td>
                <td className={`px-1.5 py-2 font-mono tabular ${tone(h.pnl)}`} dir="ltr" style={{ textAlign: "right" }}>{money(h.pnl)}</td>
                <td className="px-1.5 py-2 text-muted">{h.reason}</td><td className="px-1.5 py-2 text-faint">{ago(h.time)}</td>
              </tr>))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  )
}

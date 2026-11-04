"use client"
import { Fragment, useState } from "react"
import { apiPaperClose, apiPaperCloseResult } from "@/lib/api"
import { ExternalLink } from "lucide-react"
import { BOT_PAGE, strategyName } from "@/lib/strategies"
import { type LiveBot } from "@/lib/live-bots"
import { agoText, useLocale, useT } from "@/lib/i18n/locale"

const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const tone = (v: number) => v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const px = (v?: number) => v === undefined || v === null ? "—" : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })

const T = {
  ar: {
    confirm: (label: string, name: string) => `تقفل ${label} في بوت «${name}» دلوقتي بالسعر الحالي؟\nده بيغيّر سجل البوت اللي بيشوفه كل الناس.`,
    sending: "بيبعت…", closing: "البوت بيقفل (لحد دقيقة)…", closed: (p: string) => `✅ اتقفلت ${p}$`, noAnswer: "⚠️ البوت ما ردّش",
    title: "البوتات شغالة دلوقتي", sub: (n: number) => `الـ ${n} بوتات على السيرفر — Paper (فلوس وهمية)، بتتحدث كل 15 ثانية`, page: "صفحة البوتات بالأسعار اللحظية",
    loading: "بيحمّل البوتات…", trial: "تجربة جديدة", unavailable: "مش متاح", running: "شغال", updated: (a: string) => `آخر تحديث ${a}`,
    realized: "محقق", open: "مفتوح", total: "الإجمالي", counts: (o: number, c: number, w: number, l: number) => `${o} مفتوحة · ${c} اتقفلت (${w} كسبانة / ${l} خسرانة)`,
    none: "مفيش صفقات مفتوحة دلوقتي", stop: "وقف", close: "اقفل", more: (n: number) => `+ ${n} تانيين على `, botsPage: "صفحة البوتات",
  },
  en: {
    confirm: (label: string, name: string) => `Close ${label} in the "${name}" bot now, at the current price?\nThis changes the bot's record everyone sees.`,
    sending: "Sending…", closing: "The bot is closing it (up to a minute)…", closed: (p: string) => `✅ Closed ${p}$`, noAnswer: "⚠️ The bot didn't answer",
    title: "The bots, running now", sub: (n: number) => `All ${n} bots on the server — paper (play money), refreshed every 15 seconds`, page: "Bots page with live prices",
    loading: "Loading the bots…", trial: "New trial", unavailable: "Unavailable", running: "Running", updated: (a: string) => `updated ${a}`,
    realized: "Realized", open: "Open", total: "Total", counts: (o: number, c: number, w: number, l: number) => `${o} open · ${c} closed (${w} won / ${l} lost)`,
    none: "No open trades right now", stop: "Stop", close: "Close", more: (n: number) => `+ ${n} more on the `, botsPage: "bots page",
  },
}

/** The paper bots on the VPS, live (data refreshed by useLiveBots in the parent). */
export function LiveBots({ bots, loaded, admin = false }: { bots: LiveBot[], loaded: boolean, admin?: boolean }){
  const t = useT(T)
  const locale = useLocale()
  const align = { textAlign: locale === "en" ? "left" : "right" } as const
  const [closing, setClosing] = useState<Record<string, string>>({})
  async function close(bot: string, name: string, ref: string, label: string){
    if(!confirm(t.confirm(label, name))) return
    const k = bot + ref
    setClosing(c => ({ ...c, [k]: t.sending }))
    try{
      const { id } = await apiPaperClose(bot, ref)
      setClosing(c => ({ ...c, [k]: t.closing }))
      for(let i = 0; i < 50; i++){
        await new Promise(r => setTimeout(r, 3000))
        const r = await apiPaperCloseResult(bot, id)
        if(r.done){ setClosing(c => ({ ...c, [k]: r.ok ? t.closed(`${r.pnl > 0 ? "+" : ""}${Number(r.pnl).toFixed(2)}`) : `⚠️ ${r.msg}` })); return }
      }
      setClosing(c => ({ ...c, [k]: t.noAnswer }))
    }catch(e: any){ setClosing(c => ({ ...c, [k]: `⚠️ ${e.message}` })) }
  }
  return (
    <section id="live-bots" className="scroll-mt-6 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold">{t.title}</h2>
          <p className="text-[13px] text-muted">{t.sub(bots.length || 7)}</p>
        </div>
        <a href={BOT_PAGE} target="_blank" rel="noopener" className="flex items-center gap-1 text-sm font-semibold text-corona hover:underline">{t.page} <ExternalLink size={14}/></a>
      </div>
      {!loaded ? <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-faint">{t.loading}</div> : (
        <div className="grid gap-3 lg:grid-cols-2">
          {bots.map(b => {
            const s = b.strategy, total = b.realized + b.unrealized, name = strategyName(s, locale)
            const top = [...b.positions].sort((x, y) => Math.abs(y.pnl) - Math.abs(x.pnl)).slice(0, admin ? 100 : 5)   // the admin sees (and can close) all
            return (
              <div key={s.id} className={`flex flex-col rounded-2xl border bg-surface p-4 transition hover:border-line2 ${s.risk === "high" ? "border-loss/35" : "border-line"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-bold">{name}</span>
                      {s.risk === "high" && <span className="rounded-full border border-loss/45 bg-loss/10 px-2 py-0.5 text-[10px] font-bold text-loss">⚠️ HIGH RISK</span>}
                      {s.experimental && <span className="rounded-full border border-corona/45 bg-corona/10 px-2 py-0.5 text-[10px] font-bold text-corona">{t.trial}</span>}
                    </div>
                    {locale === "ar" && <div className="text-xs text-muted">{s.desc} · {s.sides}</div>}
                  </div>
                  <span className={`flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[11px] font-bold ${!b.ok ? "text-loss" : b.fresh ? "text-profit" : "text-corona"}`}>
                    <i className={`h-1.5 w-1.5 rounded-full ${!b.ok ? "bg-loss" : b.fresh ? "animate-pulse bg-profit" : "bg-corona"}`}/>
                    {!b.ok ? t.unavailable : b.fresh ? t.running : t.updated(agoText(b.updated, locale))}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  {[[t.realized, b.realized], [t.open, b.unrealized], [t.total, total]].map(([k, v]) => (
                    <div key={k as string} className="rounded-xl bg-surface2/60 py-2">
                      <div className="text-[11px] text-muted">{k}</div>
                      <div className={`font-mono text-sm font-bold tabular ${tone(v as number)}`} dir="ltr">{money(v as number)}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap justify-between gap-2 text-[11px] text-faint">
                  <span>{t.counts(b.open, b.closed, b.wins, b.losses)}</span>
                  {b.note && <span className="truncate">{b.note}</span>}
                </div>
                <div className="mt-3 flex-1 overflow-x-auto">
                  {top.length === 0 ? <div className="py-4 text-center text-xs text-faint">{t.none}</div> : (
                    <table className="w-full text-[12px]">
                      <tbody>
                        {top.map(p => (<Fragment key={p.label + p.side}>
                          <tr className="border-t border-line/70">
                            <td className="py-1.5 font-bold" dir="ltr" style={align}>{p.label}</td>
                            <td className="py-1.5">
                              {p.side === "pair" ? <span className="text-faint">{p.detail}</span>
                                : <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${p.side === "long" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{p.side.toUpperCase()}</span>}
                            </td>
                            <td className="py-1.5 font-mono text-muted tabular" dir="ltr" style={align}>{p.price !== undefined ? `${px(p.entry)} → ${px(p.price)}` : ""}</td>
                            <td className={`py-1.5 font-mono font-bold tabular ${tone(p.pnl)}`} dir="ltr" style={align}>{money(p.pnl)}</td>
                          </tr>
                          <tr><td colSpan={4} className="pb-1.5 text-[10.5px] leading-4 text-faint">
                            {p.sl !== undefined && <><span className="text-loss/90">{t.stop} <span className="font-mono" dir="ltr">{px(p.sl)}</span></span> · </>}
                            <span className="text-profit/90">{p.exit}</span>
                            {admin && (closing[s.live + p.ref]
                              ? <span className="ms-2 text-muted">{closing[s.live + p.ref]}</span>
                              : <button onClick={() => close(s.live, name, p.ref, p.label)} className="ms-2 rounded border border-loss/50 px-1.5 text-[10px] font-bold text-loss hover:bg-loss/10">{t.close}</button>)}
                          </td></tr>
                        </Fragment>))}
                      </tbody>
                    </table>
                  )}
                  {b.positions.length > top.length && <div className="pt-1.5 text-[11px] text-faint">{t.more(b.positions.length - top.length)}<a href={BOT_PAGE} target="_blank" rel="noopener" className="text-corona hover:underline">{t.botsPage}</a></div>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

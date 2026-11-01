"use client"
import { useCallback, useEffect, useState } from "react"
import { apiSetUserBots, apiUserBotClose, apiUserBots } from "@/lib/api"
import { LABELS } from "@/components/LiveStrategies"
import { Card, CardHeader, Pill, btn, field, label, type Tone } from "@/components/ui"

/** What the provisioner (root, on the server) answered for this user — docs/phase2-design.md. */
const ANSWER: Record<string, [string, Tone, string]> = {
  running: ["شغّالة", "profit", "البوتات بتاعتك شغالة على حساب Binance Demo بتاعك."],
  waiting_approval: ["مستنية الموافقة", "corona", "طلبك وصل — الإدارة لسه ما وافقتش على حسابك. أول ما توافق البوتات بتشتغل لوحدها."],
  no_consent: ["ناقص الموافقة", "loss", "اكتب نص الموافقة في الخطوة 3 الأول."],
  no_keys: ["ناقص المفاتيح", "loss", "احفظ مفاتيح Binance Demo في الخطوة 1 الأول."],
  no_place: ["مفيش مكان دلوقتي", "corona", "عدد الحسابات على السيرفر وصل للحد. طلبك محفوظ وهيشتغل أول ما يفضى مكان."],
  off: ["متوقفة", "neutral", "البوتات متوقفة. الصفقات المفتوحة بتخرج على قاعدتها ووقفها."],
  refused: ["اترفض", "loss", "الإعدادات مش مقبولة على السيرفر."],
}
const money = (v?: number|null) => v == null ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`

/** A user's own strategies on their own Binance Demo account: choose up to the allowed number, capital and margin;
 *  the server's provisioner runs each as the owner's bot does, after the owner approves the account. */
export function UserBots({ consent }: { consent: { enabled: boolean, leverage?: number, risk_per_trade_pct?: number, max_aggregate_risk_pct?: number } }){
  const [data, setData] = useState<any|null|undefined>(undefined)
  const [chosen, setChosen] = useState<string[]>([])
  const [capital, setCapital] = useState("1000")
  const [margin, setMargin] = useState("20")
  const [msg, setMsg] = useState("")
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const d = await apiUserBots(); setData(d)
    if(d?.desired){ setChosen(d.desired.strategies || []); setCapital(String(d.desired.capital_usdt ?? "")); setMargin(String(d.desired.capital_margin_override_usdt ?? "")) }
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t) }, [load])

  if(data === undefined) return null
  if(data === null) return <Card><p className="py-6 text-center text-[13px] text-faint">مش متاح دلوقتي</p></Card>
  const max = data.rules?.max_strategies ?? 2
  const ans = ANSWER[data.provision?.state] || null
  const enabled = !!data.desired?.enabled

  function toggle(s: string){
    setChosen(c => c.includes(s) ? c.filter(x => x !== s) : c.length < max ? [...c, s] : c)
  }
  async function save(on: boolean){
    const cap = Number(capital) || 0, m = Number(margin) || 0
    if(on && !chosen.length){ setMsg("اختار استراتيجية واحدة على الأقل"); return }
    if(on && !(m > 0 && m <= cap)){ setMsg("المارجن لكل صفقة لازم يكون أكبر من صفر ومش أكبر من راس المال"); return }
    const text = on ? `تشغيل على Binance Demo (فلوس وهمية):\n${chosen.map(s => LABELS[s] || s).join("\n")}\nراس المال ${cap}$ · مارجن ${m}$ لكل صفقة` : "إيقاف البوتات؟ الصفقات المفتوحة بتخرج على قاعدتها."
    if(!confirm(text)) return
    setBusy(true); setMsg("")
    try{
      await apiSetUserBots({ env: "demo", enabled: on, strategies: chosen, leverage: consent.leverage ?? 2,
        risk_per_trade_pct: consent.risk_per_trade_pct ?? 0.25, max_aggregate_risk_pct: consent.max_aggregate_risk_pct ?? 1,
        capital_usdt: cap, capital_margin_override_usdt: m })
      setMsg(on ? "✅ اتحفظ — السيرفر بيطبّقه خلال دقيقة" : "✅ اتوقفت"); load()
    }catch(e: any){ setMsg(`⚠️ ${e.message}`) }
    finally{ setBusy(false) }
  }
  async function close(s: string, symbol: string){
    if(!confirm(`قفل ${symbol} دلوقتي بسعر السوق؟`)) return
    try{ await apiUserBotClose(s, symbol); setMsg("✅ طلب القفل اتبعت — بيتنفّذ خلال دقيقة"); setTimeout(load, 70_000) }
    catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }

  const bots = Object.entries(data.bots || {}) as [string, any][]
  return (
    <Card className="border-signal/30">
      <CardHeader title="4 · البوتات بتاعتك" sub={`على Binance Demo بس (فلوس وهمية) · لحد ${max} استراتيجيات · نفس كود بوت الإدارة`}
        action={ans && <Pill tone={ans[1]}>{ans[0]}</Pill>} />
      {ans && <p className="mb-4 rounded-xl bg-surface2 px-4 py-3 text-[13px] text-muted">{ans[2]}</p>}
      {!consent.enabled && <p className="mb-4 text-[12px] text-loss">محتاج الموافقة (الخطوة 3) قبل ما البوتات تشتغل.</p>}

      <div className="mb-4 grid gap-2 sm:grid-cols-2">
        {(data.rules?.strategies || []).map((s: string) => {
          const on = chosen.includes(s), full = !on && chosen.length >= max
          return (
            <button key={s} type="button" onClick={() => toggle(s)} disabled={full}
              className={`rounded-xl border px-3 py-2.5 text-right text-[14px] ${on ? "border-signal bg-signal/10 font-semibold" : "border-line"} ${full ? "opacity-40" : ""}`}>
              {on ? "✓ " : ""}{LABELS[s] || s}
            </button>
          )
        })}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block"><span className={label}>راس المال ($) — مش أكتر من رصيد الـ Demo</span>
          <input type="number" min={0} value={capital} onChange={e => setCapital(e.target.value)} className={`${field} font-mono`} dir="ltr"/></label>
        <label className="block"><span className={label}>المارجن لكل صفقة ($)</span>
          <input type="number" min={0} value={margin} onChange={e => setMargin(e.target.value)} className={`${field} font-mono`} dir="ltr"/></label>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button onClick={() => save(true)} disabled={busy} className={btn.primary}>{enabled ? "احفظ التغييرات" : "شغّل البوتات"}</button>
        {enabled && <button onClick={() => save(false)} disabled={busy} className={btn.secondary}>وقّف البوتات</button>}
        {msg && <span className="text-[12px] text-muted">{msg}</span>}
      </div>

      {bots.length > 0 && (
        <div className="mt-5 space-y-4">
          {bots.map(([s, b]) => (
            <div key={s} className="rounded-xl border border-line p-3">
              <div className="mb-2 flex items-center justify-between">
                <b className="text-[14px]">{LABELS[s] || s}</b>
                <Pill tone={b.running ? "profit" : "neutral"}>{b.running ? "شغال" : "مش شغال"}</Pill>
              </div>
              {b.entry_block && <p className="mb-2 text-[12px] text-corona">الدخول متوقف: {b.entry_block}</p>}
              {(b.positions || []).length === 0 ? <p className="text-[12px] text-faint">مفيش صفقات مفتوحة</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[480px] text-[13px]">
                    <thead className="text-[12px] text-faint"><tr>{["العملة", "الاتجاه", "الدخول", "الربح", ""].map(h => <th key={h} className="px-2 py-1.5 text-right font-semibold">{h}</th>)}</tr></thead>
                    <tbody>
                      {b.positions.map((p: any) => (
                        <tr key={p.symbol} className="border-t border-line">
                          <td className="px-2 py-2 font-mono" dir="ltr" style={{ textAlign: "right" }}>{p.symbol}</td>
                          <td className="px-2 py-2"><Pill tone={p.side === "short" ? "loss" : "profit"}>{p.side === "short" ? "SHORT" : "LONG"}</Pill></td>
                          <td className="px-2 py-2 font-mono" dir="ltr" style={{ textAlign: "right" }}>{p.entry}</td>
                          <td className={`px-2 py-2 font-mono ${(p.pnl ?? 0) >= 0 ? "text-profit" : "text-loss"}`} dir="ltr" style={{ textAlign: "right" }}>{p.pnl_estimated ? "≈ " : ""}{money(p.pnl)}</td>
                          <td className="px-2 py-2"><button onClick={() => close(s, p.symbol)} className="text-[12px] text-loss underline">اقفل</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

"use client"
import { useCallback, useEffect, useState } from "react"
import { apiLiveStatus, apiLiveStrategies, apiSetLiveStrategies } from "@/lib/api"
import { Dot, Pill, Toggle, type Tone } from "@/components/ui"

/** Admin overview, laid out like the Figma frame "04 · الإدارة": key numbers, the Demo account's strategies with their
 *  yes/no and share of the slots, alerts, and the capital plan. Data: /api/live/strategies?env=demo, /api/live/status,
 *  and the admin finance endpoint the page already loads. */

const LABELS: Record<string, string> = {
  trend_daily: "الترند اليومي", ratio_trend: "ترند النسبة", momentum_ls: "مومنتم لونج/شورت", listing_short: "شورت العملات الجديدة",
  vol_breakout: "بريك أوت التذبذب", rsi2_pullback: "RSI-2", trend_breakout: "اختراق الترند",
}
const LEVEL: Record<string, [string, Tone]> = { low: ["خطورة منخفضة", "profit"], medium: ["خطورة متوسطة", "corona"], high: ["خطورة عالية", "loss"], very_high: ["خطورة عالية جدًا", "loss"] }
const usd = (v: number) => `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`
const signedUsd = (v: number) => `${v > 0 ? "+" : ""}${usd(v)}`

export type OverviewData = { cfg: any | null, status: any | null }
export type Alert = { message: string, tone: Tone, when?: string }

function Stat({ label, value, hint, tone }: { label: string, value: string, hint: string, tone?: "profit" | "loss" }){
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface px-5 py-[18px]">
      <div className="text-[13px] text-muted">{label}</div>
      <div className={`mt-1.5 truncate font-mono text-[22px] font-bold leading-tight tabular ${tone === "profit" ? "text-profit" : tone === "loss" ? "text-loss" : "text-ink"}`}>{value}</div>
      <div className="mt-1.5 text-[12px] text-faint">{hint}</div>
    </div>
  )
}

/** The drawing only (no fetching), so it can be checked with sample data. */
export function AdminOverviewView({ data, finance, killTripped, alerts, chosen, onToggle, onSave, saving, msg, onOpen }: {
  data: OverviewData, finance: any, killTripped: boolean, alerts: Alert[], chosen: Set<string>, onToggle: (id: string, on: boolean) => void,
  onSave: () => void, saving: boolean, msg: string, onOpen: (section: string) => void,
}){
  const rows: any[] = data.cfg?.strategies || []
  const cap = data.cfg?.capital || {}
  const plan = cap.plan
  const onCount = rows.filter(r => chosen.has(r.id)).length
  const share = plan && onCount ? Math.max(1, Math.floor(plan.max_open / onCount)) : null
  const running = rows.filter(r => r.running).length
  const changed = rows.some(r => r.on !== chosen.has(r.id))
  const fin = finance || {}
  const openPnl = (id: string) => ((data.status?.strategies?.[id]?.positions || []) as any[]).reduce((a, p) => a + (Number(p.pnl) || 0), 0)
  const status = (r: any): [string, Tone] => r.review?.length ? ["محتاج مراجعة", "loss"] : !chosen.has(r.id) ? ["متوقفة", "neutral"]
    : r.entry_block ? ["الدخول متوقف", "corona"] : r.running ? ["شغال", "profit"] : ["البوت مش شغال", "neutral"]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="بوتات Demo شغالة" value={rows.length ? `${running} / ${rows.length}` : "—"} hint="من آخر حالة كتبها كل بوت"/>
        <Stat label="الإيراد الشهري (MRR)" value={fin.mrr_usd != null ? usd(Number(fin.mrr_usd)) : "—"} hint="من الاشتراكات الشغالة" tone="profit"/>
        <Stat label="مستخدمون مدفوعون" value={fin.paying_users != null ? String(fin.paying_users) : "—"} hint={fin.total_users != null ? `من ${fin.total_users} مستخدم` : "—"}/>
        <Stat label="قفل الطوارئ" value={killTripped ? "شغال" : "مش شغال"} hint="حساب Demo وحساب حقيقي" tone={killTripped ? "loss" : "profit"}/>
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_372px]">
        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[17px] font-bold">استراتيجيات حساب Demo</h2>
              <p className="mt-0.5 text-[12px] text-muted">{share != null ? `كل استراتيجية شغالة ليها لحد ${share} صفقات (${plan.max_open} مكان ÷ ${onCount})` : "حدد خطة راس المال عشان يتحسب نصيب كل استراتيجية"}</p>
            </div>
            <div className="flex items-center gap-2">
              {msg && <span className="text-[12px] text-muted">{msg}</span>}
              <button onClick={onSave} disabled={!changed || saving} className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm font-semibold transition hover:border-corona/40 disabled:opacity-40">{saving ? "بيحفظ…" : "احفظ التغييرات"}</button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-[13px]">
              <thead className="text-[12px] text-faint">
                <tr>{["الاستراتيجية", "تشتغل", "مفتوحة / النصيب", "ربح المفتوح", "الحالة"].map(h => <th key={h} className="px-2 py-2 text-right font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody>
                {!rows.length && <tr><td colSpan={5} className="px-2 py-8 text-center text-faint">{data.cfg === null ? "مش متاح دلوقتي" : "بيحمّل…"}</td></tr>}
                {rows.map(r => {
                  const on = chosen.has(r.id), pnl = openPnl(r.id), [st, tone] = status(r)
                  return (
                    <tr key={r.id} className="border-t border-line">
                      <td className="px-2 py-3 text-[14px] font-semibold">{LABELS[r.id] || r.id}</td>
                      <td className="px-2 py-3"><Toggle on={on} onChange={v => onToggle(r.id, v)} label={`${LABELS[r.id] || r.id} تشتغل`}/></td>
                      <td className="px-2 py-3 font-mono tabular" dir="ltr" style={{ textAlign: "right" }}>{r.positions} / {on && share != null ? share : "—"}</td>
                      <td className={`px-2 py-3 font-mono tabular ${pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "text-muted"}`} dir="ltr" style={{ textAlign: "right" }}>{signedUsd(pnl)}</td>
                      <td className="px-2 py-3"><Pill tone={tone}>{st}</Pill></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <button onClick={() => onOpen("real")} className="mt-3 text-[13px] font-semibold text-corona">الحساب الحقيقي والصفقات المفتوحة ←</button>
        </section>

        <div className="space-y-5">
          <section className="rounded-2xl border border-line bg-surface p-5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="text-[17px] font-bold">التنبيهات</h2>
              <Pill tone={alerts.some(a => a.tone === "loss" || a.tone === "corona") ? "loss" : "profit"}>{alerts.some(a => a.tone === "loss" || a.tone === "corona") ? `${alerts.filter(a => a.tone === "loss" || a.tone === "corona").length} محتاجة انتباه` : "مفيش مشاكل"}</Pill>
            </div>
            <div className="divide-y divide-line">
              {alerts.slice(0, 6).map((a, i) => (
                <div key={i} className="flex items-start justify-between gap-3 py-2.5 text-[13px]">
                  <span className="flex min-w-0 items-start gap-2"><span className="mt-1.5"><Dot tone={a.tone}/></span><span>{a.message}</span></span>
                  {a.when && <span className="shrink-0 font-mono text-[12px] text-faint">{a.when}</span>}
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-line bg-surface p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-[17px] font-bold">راس المال (Demo)</h2>
              {plan && <Pill tone={(LEVEL[plan.level] || LEVEL.medium)[1]}>{(LEVEL[plan.level] || LEVEL.medium)[0]}</Pill>}
            </div>
            {plan ? <>
              <div className="grid grid-cols-4 gap-2">
                {[["الرصيد", cap.equity_last != null ? `$${Math.round(Number(cap.equity_last)).toLocaleString("en-US")}` : "—"], ["المارجن", usd(plan.margin)], ["الأماكن", String(plan.max_open)], ["النصيب", share != null ? String(share) : "—"]].map(([l, v]) => (
                  <div key={l} className="min-w-0 rounded-[10px] bg-surface2 px-2.5 py-2.5">
                    <div className="truncate text-[11px] text-muted">{l}</div>
                    <div className="truncate font-mono text-[14px] font-medium tabular">{v}</div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[12px] text-faint">وقف واحد = <b className="font-mono text-loss" dir="ltr">−{usd(plan.loss_per_trade)}</b> ({plan.loss_per_trade_pct}%) · كل الوقفات مع بعض = <b className="font-mono text-loss" dir="ltr">−{plan.worst_case_pct}%</b></p>
            </> : <p className="text-[13px] text-muted">مفيش خطة راس مال على حساب Demo.</p>}
            <button onClick={() => onOpen("real")} className="mt-4 w-full rounded-xl border border-line bg-surface2 py-2.5 text-sm font-semibold transition hover:border-corona/40">عدّل راس المال</button>
          </section>
        </div>
      </div>
    </div>
  )
}

/** The overview with its data: the Demo account's strategies and capital, and each bot's live status. */
export function AdminOverview({ finance, killTripped, operationalAlerts, onOpen }: { finance: any, killTripped: boolean, operationalAlerts: any[], onOpen: (section: string) => void }){
  const [data, setData] = useState<OverviewData>({ cfg: undefined, status: undefined })
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState("")
  const load = useCallback(async () => {
    const [cfg, status] = await Promise.all([apiLiveStrategies("demo"), apiLiveStatus()])
    setData({ cfg, status })
    if (cfg) setChosen(new Set(cfg.strategies.filter((r: any) => r.on).map((r: any) => r.id)))
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t) }, [load])

  async function save(){
    setSaving(true); setMsg("")
    try { await apiSetLiveStrategies("demo", "", [...chosen]); setMsg("✅ اتحفظ"); await load() }
    catch (e: any) { setMsg(`⚠️ ${e.message}`) }
    finally { setSaving(false) }
  }

  const rows: any[] = data.cfg?.strategies || []
  const alerts: Alert[] = [
    ...operationalAlerts.filter(Boolean).map((a: any) => typeof a === "string" ? { message: a, tone: "corona" as Tone }
      : { message: a.title ? `${a.title} · ${a.message || a.reason || ""}` : (a.message || a.reason || "تنبيه"), tone: (a.severity === "error" || a.severity === "critical" ? "loss" : "corona") as Tone }),
    ...rows.filter(r => r.review?.length).map(r => ({ message: `${LABELS[r.id] || r.id} محتاجة مراجعة: ${r.review.join("، ")}`, tone: "loss" as Tone })),
    ...rows.filter(r => r.entry_block).map(r => ({ message: `الدخول متوقف في ${LABELS[r.id] || r.id}: ${r.entry_block}`, tone: "corona" as Tone })),
  ]
  if (!alerts.length && rows.length) {
    const off = rows.filter(r => !r.running)
    alerts.push(off.length ? { message: `${off.length} بوت مش بيكتب حالته: ${off.map(r => LABELS[r.id] || r.id).join("، ")}`, tone: "corona" }
      : { message: "كل بوتات Demo كتبت حالتها في آخر 5 دقايق", tone: "profit" })
  }
  if (!alerts.length) alerts.push({ message: "مفيش تنبيهات تشغيلية حالية", tone: "profit" })

  return <AdminOverviewView data={data} finance={finance} killTripped={killTripped} alerts={alerts} chosen={chosen}
    onToggle={(id, on) => setChosen(s => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n })}
    onSave={save} saving={saving} msg={msg} onOpen={onOpen}/>
}

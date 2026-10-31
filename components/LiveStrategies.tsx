"use client"
import { useCallback, useEffect, useState } from "react"
import { apiLiveStatus, apiLiveStrategies, apiSetCapital, apiSetLiveStrategies } from "@/lib/api"
import { LivePositions } from "@/components/LivePositions"
import { Card, CardHeader, Pill, Toggle, btn, field, label, type Tone } from "@/components/ui"

const usd = (v: number) => `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`
const signedUsd = (v: number) => `${v > 0 ? "+" : ""}${usd(v)}`

const LEV = 2, STOP = 0.40   // every strategy: x2 and a 40% stop (risk_manager.PLAN_LEVERAGE / PLAN_STOP_LOSS)

/** Same rule as risk_manager.capital_plan: capital capped by the account's balance; margin = the manual one, or
 *  max(min, capital × margin %); max open = capital × (1 − reserve %) ÷ margin; what one stop / every stop costs. */
function plan(capital: number, manual: number, c: any){
  if(!(capital > 0)) return null
  const eff = c?.equity_last > 0 ? Math.min(capital, c.equity_last) : capital
  const margin = manual > 0 ? manual : Math.max(c?.capital_min_margin_usdt ?? 30, eff * (c?.capital_margin_pct ?? 1) / 100)
  const maxOpen = Math.floor(eff * (1 - (c?.capital_reserve_pct ?? 40) / 100) / margin)
  const loss = margin * LEV * STOP, lossPct = loss / eff * 100
  const level = lossPct < 1 ? "low" : lossPct < 2 ? "medium" : lossPct < 5 ? "high" : "very_high"
  const rpt = c?.risk_per_trade_pct, agg = c?.max_aggregate_risk_pct
  const blockedPerTrade = rpt != null && lossPct > rpt
  const byAgg = agg != null && lossPct > 0 ? Math.floor(agg / lossPct) : maxOpen
  return { eff, margin, maxOpen, loss, lossPct, worst: loss * maxOpen / eff * 100, level, blockedPerTrade, allowed: blockedPerTrade ? 0 : Math.min(maxOpen, byAgg) }
}

const LEVEL: Record<string, [string, Tone]> = {
  low: ["خطورة منخفضة", "profit"], medium: ["خطورة متوسطة", "corona"], high: ["خطورة عالية", "loss"], very_high: ["خطورة عالية جدًا", "loss"],
}

function Tile({ label, value, hint }: { label: string, value: string, hint?: string }){
  return (
    <div className="min-w-0 rounded-[10px] bg-surface2 px-3 py-2.5">
      <div className="truncate text-[11px] text-muted">{label}</div>
      <div className="truncate font-mono text-[15px] font-semibold tabular" dir="ltr" style={{ textAlign: "right" }}>{value}</div>
      {hint && <div className="truncate text-[11px] text-faint">{hint}</div>}
    </div>
  )
}

function Note({ tone, children }: { tone: "loss" | "corona", children: React.ReactNode }){
  return <div className={`mt-2 rounded-[10px] border px-3 py-2 text-[12px] ${tone === "loss" ? "border-loss/30 bg-loss/10 text-loss" : "border-corona/30 bg-corona/10 text-corona"}`}>{children}</div>
}

/** The owner's capital for this account, and optionally their own margin per trade: the margin and the most trades
 *  open at once (all strategies together) follow, with what a stop would cost. Entries beyond the count are refused. */
function CapitalPanel({ env, cfg, reload }: { env: "demo"|"live", cfg: any, reload: () => void }){
  const c = cfg.capital || {}
  const [value, setValue] = useState<string>(c.capital_usdt ? String(c.capital_usdt) : "")
  const [manual, setManual] = useState<string>(c.capital_margin_override_usdt ? String(c.capital_margin_override_usdt) : "")
  const [msg, setMsg] = useState("")
  useEffect(() => {
    setValue(c.capital_usdt ? String(c.capital_usdt) : ""); setManual(c.capital_margin_override_usdt ? String(c.capital_margin_override_usdt) : ""); setMsg("")
  }, [env, c.capital_usdt, c.capital_margin_override_usdt])
  const p = plan(Number(value), Number(manual), c)
  const changed = Number(value) !== (c.capital_usdt || 0) || Number(manual) !== (c.capital_margin_override_usdt || 0)
  async function save(){
    const n = Number(value) || 0, m = Number(manual) || 0
    const risk = p ? `\nلو الوقف اتضرب في صفقة: −${usd(p.loss)} (${p.lossPct.toFixed(1)}% من راس المال) — ${LEVEL[p.level][0]}` : ""
    if(!confirm(n ? `راس المال ${usd(n)} على ${env === "demo" ? "الـ Demo" : "الحساب الحقيقي"}:\nمارجن ${usd(p!.margin)} لكل صفقة${m ? " (يدوي)" : ""}، وبحد أقصى ${p!.maxOpen} صفقة مفتوحة.${risk}` : "إلغاء خطة راس المال؟")) return
    try{ await apiSetCapital(env, n, m); setMsg("✅ اتحفظ"); reload() } catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }
  const lv = p ? LEVEL[p.level] : null
  return (
    <Card>
      <CardHeader title={`راس المال (${env === "demo" ? "Demo" : "حقيقي"})`} action={lv && <Pill tone={lv[1]}>{lv[0]}</Pill>}
        sub={`${c.capital_reserve_pct ?? 40}% احتياطي · رافعة 2x · وقف 40% من السعر`} />
      <div className="grid grid-cols-2 gap-3">
        <label className="min-w-0"><span className={label}>راس المال (USDT)</span>
          <input type="number" min={0} inputMode="decimal" value={value} onChange={e => setValue(e.target.value)} dir="ltr" placeholder="مثلا 1000" className={`${field} font-mono`} />
        </label>
        <label className="min-w-0"><span className={label}>المارجن لكل صفقة</span>
          <input type="number" min={0} inputMode="decimal" value={manual} onChange={e => setManual(e.target.value)} dir="ltr" placeholder="تلقائي" className={`${field} font-mono`} />
        </label>
      </div>
      <p className="mt-2 text-[12px] text-faint">سيب المارجن فاضي يتحسب لوحده: {c.capital_margin_pct ?? 1}% من راس المال ومش أقل من {usd(c.capital_min_margin_usdt ?? 30)}.</p>
      {p && lv ? <>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Tile label={`المارجن${Number(manual) > 0 ? " (يدوي)" : ""}`} value={usd(p.margin)} hint={`حجم الصفقة ${usd(p.margin * LEV)}`} />
          <Tile label="أقصى صفقات مفتوحة" value={String(p.maxOpen)} />
          <Tile label="مفتوح دلوقتي" value={`${c.open_trades ?? "—"}${c.plan ? ` / ${c.plan.max_open}` : ""}`} />
          <Tile label="الرصيد" value={c.equity_last != null ? usd(Math.round(Number(c.equity_last))) : "—"} />
        </div>
        <div className="mt-3 space-y-1 text-[12px] text-muted">
          <div>وقف واحد = <b className="font-mono text-loss" dir="ltr">−{usd(p.loss)}</b> ({p.lossPct.toFixed(1)}% من راس المال)</div>
          <div>كل الوقفات مع بعض ({p.maxOpen}) = <b className="font-mono text-loss" dir="ltr">−{p.worst.toFixed(0)}%</b></div>
          <div className="text-faint">منخفضة أقل من 1% للصفقة · متوسطة 1–2% · عالية 2–5% · عالية جدًا فوق 5%</div>
        </div>
        {p.margin * LEV < 50 && <Note tone="loss">حجم الصفقة {usd(p.margin * LEV)} أقل من أقل أمر على BTC في Binance ($50) — صفقات BTC هتترفض.</Note>}
        {p.blockedPerTrade && <Note tone="loss">خسارة الصفقة {p.lossPct.toFixed(1)}% أكبر من حد المخاطرة للصفقة الواحدة ({c.risk_per_trade_pct}%): كل الدخول هيترفض لحد ما تقلّل المارجن أو ترفع الحد.</Note>}
        {!p.blockedPerTrade && p.allowed < p.maxOpen && <Note tone="corona">حد المخاطرة الإجمالي ({c.max_aggregate_risk_pct}%) هيوقف الدخول عند {p.allowed} صفقة، قبل الـ {p.maxOpen}.</Note>}
      </> : <p className="mt-4 rounded-[10px] bg-surface2 px-3 py-2.5 text-[12px] text-muted">مفيش خطة: كل بوت بيدخل بالحجم المضبوط في خدمته ومفيش حد لعدد الصفقات.</p>}
      {p && p.eff < Number(value) && <Note tone="loss">رصيد الحساب ({usd(p.eff)}) أقل من راس المال اللي كتبته: الحساب كله على الرصيد.</Note>}
      <div className="mt-4 flex items-center gap-3">
        <button onClick={save} disabled={!changed} className={`${btn.primary} flex-1`}>احفظ راس المال</button>
        {msg && <span className="text-[12px] text-muted">{msg}</span>}
      </div>
    </Card>
  )
}

// trades a strategy opens at once: a momentum basket is 5 long + 5 short (bot.MOM), a ratio pair 2 legs
const OPENS_AT_ONCE: Record<string, number> = { momentum_ls: 10, ratio_trend: 2 }

const LABELS: Record<string, string> = {
  trend_daily: "ترند يومي", vol_breakout: "اختراق التقلب", rsi2_pullback: "RSI2 الارتداد", trend_breakout: "اختراق الترند",
  listing_short: "شورت العملات الجديدة", momentum_ls: "مومنتم لونج/شورت", ratio_trend: "ترند النسبة",
}

/** The drawing only (no fetching), so it can be checked with sample data. */
export function LiveStrategiesView({ env, onEnv, cfg, status, chosen, onToggle, account, onAccount, onSave, saving, msg, reload }: {
  env: "demo"|"live", onEnv: (e: "demo"|"live") => void, cfg: any, status: any, chosen: Set<string>, onToggle: (id: string, on: boolean) => void,
  account: string, onAccount: (v: string) => void, onSave: () => void, saving: boolean, msg: string, reload: () => void,
}){
  const envSwitch = (
    <div className="inline-flex rounded-xl border border-line bg-surface p-1">
      {(["demo", "live"] as const).map(e => (
        <button key={e} onClick={() => onEnv(e)}
          className={`rounded-[9px] px-4 py-1.5 text-[13px] transition ${env === e ? "bg-surface2 font-semibold text-ink" : "text-muted hover:text-ink"}`}>
          {e === "demo" ? "Demo · فلوس وهمية" : "فلوس حقيقية"}
        </button>
      ))}
    </div>
  )
  if(cfg === undefined) return <div className="space-y-5">{envSwitch}<Card><p className="py-8 text-center text-[13px] text-faint">بيحمّل…</p></Card></div>
  if(cfg === null) return <div className="space-y-5">{envSwitch}<Card><p className="py-8 text-center text-[13px] text-loss">مش متاح (أدمن بس)</p></Card></div>

  const rows: any[] = cfg.strategies || []
  const total: number | undefined = cfg.capital?.plan?.max_open
  const onCount = rows.filter(r => chosen.has(r.id)).length
  const share = total && onCount ? Math.max(1, Math.floor(total / onCount)) : null
  const starved = share != null ? rows.filter(r => chosen.has(r.id) && (OPENS_AT_ONCE[r.id] || 1) > share) : []
  const changed = rows.some(r => r.on !== chosen.has(r.id))
  const openPnl = (id: string) => ((status?.strategies?.[id]?.positions || []) as any[]).reduce((a, p) => a + (Number(p.pnl) || 0), 0)
  const state = (r: any): [string, Tone] => r.review?.length ? ["محتاج مراجعة", "loss"] : !chosen.has(r.id) ? ["متوقفة", "neutral"]
    : r.entry_block ? ["الدخول متوقف", "corona"] : r.running ? ["شغال", "profit"] : ["البوت مش شغال", "neutral"]
  const withBots = rows.filter(r => status?.strategies?.[r.id]?.running || status?.strategies?.[r.id]?.positions?.length)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {envSwitch}
        {env === "live" && <Pill tone={cfg.enabled ? "profit" : "loss"}>{cfg.enabled ? "التداول الحقيقي مسموح على السيرفر" : "التداول الحقيقي مقفول على السيرفر (ALLOW_LIVE_TRADING)"}</Pill>}
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_372px]">
        <Card>
          <CardHeader title="الاستراتيجيات على حسابك"
            sub={share != null ? `كل استراتيجية شغالة ليها لحد ${share} صفقات (${total} مكان ÷ ${onCount})` : "تشتغل = تقدر تدخل صفقات. مقفولة = مش هتدخل جديد، والمفتوح بيخرج على قاعدته ووقفه."}
            action={<>
              {msg && <span className="text-[12px] text-muted">{msg}</span>}
              <button onClick={onSave} disabled={saving || !changed || (env === "live" && !account.trim() && chosen.size > 0)} className={btn.secondary}>{saving ? "بيحفظ…" : "احفظ التغييرات"}</button>
            </>} />
          {env === "live" && (
            <label className="mb-4 block max-w-sm"><span className={label}>اسم الحساب (لازم يطابق BINANCE_LIVE_ACCOUNT على السيرفر)</span>
              <input value={account} onChange={e => onAccount(e.target.value)} dir="ltr" className={field} />
            </label>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-[13px]">
              <thead className="text-[12px] text-faint">
                <tr>{["الاستراتيجية", "تشتغل", "البوت", "مفتوحة / النصيب", "ربح المفتوح", "الحالة"].map(h => <th key={h} className="px-2 py-2 text-right font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const on = chosen.has(r.id), pnl = openPnl(r.id), [st, tone] = state(r)
                  return (
                    <tr key={r.id} className="border-t border-line">
                      <td className="px-2 py-3 text-[14px] font-semibold">{LABELS[r.id] || r.id}</td>
                      <td className="px-2 py-3"><Toggle on={on} onChange={v => onToggle(r.id, v)} label={`${LABELS[r.id] || r.id} تشتغل`}/></td>
                      <td className="px-2 py-3 text-[12px] text-muted">{r.running ? `شغال${r.env ? " · " + r.env : ""}` : "مش شغال"}</td>
                      <td className="px-2 py-3 font-mono tabular" dir="ltr" style={{ textAlign: "right" }}>{r.positions ?? 0} / {on && share != null ? share : "—"}</td>
                      <td className={`px-2 py-3 font-mono tabular ${pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "text-muted"}`} dir="ltr" style={{ textAlign: "right" }}>{signedUsd(pnl)}</td>
                      <td className="px-2 py-3"><Pill tone={tone}>{st}</Pill></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {starved.map(r => <Note key={r.id} tone="loss">{LABELS[r.id] || r.id} بتفتح {OPENS_AT_ONCE[r.id]} صفقات مع بعض، فبنصيب {share} مش هتدخل خالص: ارفع راس المال أو شغّل استراتيجيات أقل.</Note>)}
        </Card>
        <CapitalPanel env={env} cfg={cfg} reload={reload} />
      </div>

      {withBots.length > 0 && <h2 className="pt-1 text-[17px] font-bold">الصفقات المفتوحة على Binance</h2>}
      {withBots.map(r => <LivePositions key={r.id} strategy={r.id} label={LABELS[r.id] || r.id} st={status.strategies[r.id]} reload={reload} />)}
    </div>
  )
}

/** The admin's own live account: yes/no per strategy (the activation record the bots check before every entry),
 *  and each strategy's bot with its positions. A strategy turned off stops entering; its open positions still exit. */
export function LiveStrategies(){
  const [env, setEnv] = useState<"demo"|"live">("demo")
  const [cfg, setCfg] = useState<any|null|undefined>(undefined)
  const [status, setStatus] = useState<any|null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [account, setAccount] = useState("")
  const [msg, setMsg] = useState("")
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    const [c, s] = await Promise.all([apiLiveStrategies(env), apiLiveStatus()])
    setCfg(c); setStatus(s)
    if(c){
      setChosen(new Set(c.strategies.filter((r: any) => r.on).map((r: any) => r.id)))
      setAccount(a => a || c.account || "")
    }
  }, [env])
  useEffect(() => { load(); const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])

  async function save(){
    const list = [...chosen]
    const where = env === "demo" ? "على حساب الـ Demo (فلوس وهمية)" : `بفلوس حقيقية على حساب "${account}"`
    const text = list.length ? `تشغيل ${where}:\n${list.map(s => LABELS[s] || s).join("\n")}\n\nأي استراتيجية مش في القايمة هتبطّل تدخل صفقات جديدة.` : `إيقاف كل الاستراتيجيات عن الدخول ${where}؟`
    if(!confirm(text)) return
    setSaving(true); setMsg("")
    try{ await apiSetLiveStrategies(env, account.trim(), list); setMsg("✅ اتحفظ"); load() }
    catch(e: any){ setMsg(`⚠️ ${e.message}`) }
    finally{ setSaving(false) }
  }

  return <LiveStrategiesView env={env} onEnv={e => { setEnv(e); setCfg(undefined); setMsg("") }} cfg={cfg} status={status} chosen={chosen}
    onToggle={(id, on) => setChosen(s => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n })}
    account={account} onAccount={setAccount} onSave={save} saving={saving} msg={msg} reload={load} />
}

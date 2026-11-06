"use client"
import { useCallback, useEffect, useRef, useState } from "react"
import { CapitalQuestion, apiKillSwitch, apiLiveStatus, apiLiveStrategies, apiSetCapital, apiSetLimits, apiSetLiveStrategies } from "@/lib/api"
import { LivePositions } from "@/components/LivePositions"
import { NAME_AR } from "@/lib/strategies"
import { DemoMeasurement } from "@/components/DemoMeasurement"
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

/** The real account's name in confirms and titles: the main one, or a strategy's own sub-account. */
export const accountName = (env: "demo"|"live", acct: string) => env === "demo" ? "الـ Demo" : acct ? `الحساب الحقيقي '${acct}'` : "الحساب الحقيقي"

function Note({ tone, children }: { tone: "loss" | "corona", children: React.ReactNode }){
  return <div className={`mt-2 rounded-[10px] border px-3 py-2 text-[12px] ${tone === "loss" ? "border-loss/30 bg-loss/10 text-loss" : "border-corona/30 bg-corona/10 text-corona"}`}>{children}</div>
}

/** The owner's capital for this account, and optionally their own margin per trade: the margin and the most trades
 *  open at once (all strategies together) follow, with what a stop would cost. Entries beyond the count are refused. */
function CapitalPanel({ env, acct = "", cfg, reload }: { env: "demo"|"live", acct?: string, cfg: any, reload: () => void }){
  const c = cfg.capital || {}
  const [value, setValue] = useState<string>(c.capital_usdt ? String(c.capital_usdt) : "")
  const [manual, setManual] = useState<string>(c.capital_margin_override_usdt ? String(c.capital_margin_override_usdt) : "")
  const [msg, setMsg] = useState("")
  useEffect(() => {
    setValue(c.capital_usdt ? String(c.capital_usdt) : ""); setManual(c.capital_margin_override_usdt ? String(c.capital_margin_override_usdt) : ""); setMsg("")
  }, [env, acct, c.capital_usdt, c.capital_margin_override_usdt])
  const p = plan(Number(value), Number(manual), c)
  const changed = Number(value) !== (c.capital_usdt || 0) || Number(manual) !== (c.capital_margin_override_usdt || 0)
  async function save(){
    const n = Number(value) || 0, m = Number(manual) || 0
    const risk = p ? `\nلو الوقف اتضرب في صفقة: −${usd(p.loss)} (${p.lossPct.toFixed(1)}% من راس المال) — ${LEVEL[p.level][0]}` : ""
    // the account first, loud: on 2026-11-03 the real account's plan was saved on the Demo tab by mistake
    const where = env === "live" ? `⚠️ ${accountName(env, acct)} — فلوس حقيقية` : "🧪 حساب الـ Demo — فلوس وهمية"
    if(!confirm(n ? `${where}\n\nراس المال ${usd(n)}:\nمارجن ${usd(p!.margin)} لكل صفقة${m ? " (يدوي)" : ""}، وبحد أقصى ${p!.maxOpen} صفقة مفتوحة.${risk}` : `${where}\n\nإلغاء خطة راس المال؟`)) return
    try{ await apiSetCapital(env, n, m, false, acct); setMsg("✅ اتحفظ"); reload() }
    catch(e: any){
      if(!(e instanceof CapitalQuestion)){ setMsg(`⚠️ ${e.message}`); return }
      if(!confirm(`${where}\n\n${e.message}\n\nاحفظ برضه؟`)){ setMsg("ما اتحفظش"); return }
      try{ await apiSetCapital(env, n, m, true, acct); setMsg("✅ اتحفظ"); reload() } catch(e2: any){ setMsg(`⚠️ ${e2.message}`) }
    }
  }
  const lv = p ? LEVEL[p.level] : null
  return (
    <Card>
      <CardHeader title={`راس المال (${env === "demo" ? "Demo" : acct ? `حقيقي · ${acct}` : "حقيقي"})`} action={lv && <Pill tone={lv[1]}>{lv[0]}</Pill>}
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

const LIMITS: [string, string, string][] = [
  ["risk_per_trade_pct", "الصفقة الواحدة", "خسارة صفقة واحدة لو ضربت الوقف"],
  ["max_aggregate_risk_pct", "كل الصفقات المفتوحة", "مجموع خسارة كل المفتوح لو ضرب الوقف"],
  ["max_correlated_risk_pct", "صفقات مرتبطة", "نفس الاتجاه في نفس المجموعة (alts / majors)"],
  ["max_daily_loss_pct", "خسارة اليوم", "يقفل قفل الطوارئ (الدخول بس)"],
  ["max_drawdown_pct", "أقصى تراجع", "من أعلى رصيد · يقفل قفل الطوارئ"],
]

/** The account's risk limits, in % of its balance on Binance — the risk gate reads them before every entry. With them,
 *  what the strategies switched on need at the saved margin: one leg, the biggest basket, and one side of it. */
function LimitsPanel({ env, acct = "", cfg, chosen, reload }: { env: "demo"|"live", acct?: string, cfg: any, chosen: Set<string>, reload: () => void }){
  const c = cfg.capital || {}
  const saved = () => Object.fromEntries(LIMITS.map(([k]) => [k, c[k] != null ? String(c[k]) : ""]))
  const [vals, setVals] = useState<Record<string, string>>(saved)
  const [msg, setMsg] = useState("")
  useEffect(() => { setVals(saved()); setMsg("") }, [env, acct, ...LIMITS.map(([k]) => c[k])])   // eslint-disable-line react-hooks/exhaustive-deps
  const changed = LIMITS.some(([k]) => vals[k] !== "" && Number(vals[k]) !== Number(c[k]))
  const bad = LIMITS.some(([k]) => vals[k] !== "" && !(Number(vals[k]) > 0 && Number(vals[k]) <= 100))
  // the gate's basis (risk_manager.risk_basis): the capital when a plan is set, at most the account's balance
  const p = plan(Number(c.capital_usdt) || 0, Number(c.capital_margin_override_usdt) || 0, c)
  const equity = p?.eff ?? (Number(c.equity_last) > 0 ? Number(c.equity_last) : undefined)
  const legs = Math.max(1, ...Array.from(chosen).map(s => OPENS_AT_ONCE[s] || 1))
  const leg = p && equity ? p.loss / equity * 100 : null
  const need: Record<string, number> | null = leg == null ? null : {
    risk_per_trade_pct: leg, max_aggregate_risk_pct: leg * legs, max_correlated_risk_pct: leg * Math.ceil(legs / 2),
  }
  const short = need ? LIMITS.filter(([k]) => need[k] != null && Number(vals[k] || c[k]) < need[k] - 1e-9) : []
  async function save(){
    const patch = Object.fromEntries(LIMITS.filter(([k]) => vals[k] !== "" && Number(vals[k]) !== Number(c[k])).map(([k]) => [k, Number(vals[k])]))
    const lines = LIMITS.filter(([k]) => k in patch).map(([k, l]) => `${l}: ${c[k] ?? "—"}% ← ${patch[k]}%`).join("\n")
    if(!confirm(`حدود المخاطرة على ${accountName(env, acct)}:\n${lines}`)) return
    try{ await apiSetLimits(env, patch, acct); setMsg("✅ اتحفظ"); reload() } catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }
  return (
    <Card>
      <CardHeader title={`حدود المخاطرة (${env === "demo" ? "Demo" : acct ? `حقيقي · ${acct}` : "حقيقي"})`} sub="% من راس المال اللي فوق (ولو الرصيد أقل، من الرصيد) · البوت بيراجعها قبل كل دخول" />
      <div className="grid grid-cols-2 gap-3">
        {LIMITS.map(([k, l, hint]) => (
          <label key={k} className="min-w-0" title={hint}><span className={label}>{l} %</span>
            <input type="number" min={0} max={100} step="0.01" inputMode="decimal" value={vals[k]} onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))}
              dir="ltr" className={`${field} font-mono`} aria-label={`${l} (%)`} />
          </label>
        ))}
      </div>
      {need && equity ? (
        <p className="mt-3 text-[12px] text-muted">
          بالمارجن ده ({`$${p!.margin}`}) على {usd(Math.round(equity))}: الصفقة محتاجة <b className="font-mono" dir="ltr">{need.risk_per_trade_pct.toFixed(2)}%</b>
          {legs > 1 && <> · السلة ({legs}) <b className="font-mono" dir="ltr">{need.max_aggregate_risk_pct.toFixed(1)}%</b> · ناحية واحدة <b className="font-mono" dir="ltr">{need.max_correlated_risk_pct.toFixed(1)}%</b></>}
        </p>
      ) : <p className="mt-3 text-[12px] text-faint">حط راس المال والمارجن الأول علشان يتحسب المطلوب.</p>}
      {short.map(([k, l]) => <Note key={k} tone="loss">{l} ({vals[k] || c[k]}%) أقل من المطلوب ({need![k].toFixed(2)}%): الدخول هيترفض.</Note>)}
      {env === "live" && <p className="mt-2 text-[12px] text-faint">على الفلوس الحقيقية البوت بياخد الأقل بين الرقم ده وسقف root في allow-live.env على السيرفر — الموقع مايقدرش يغيّر السقف.</p>}
      {bad && <Note tone="loss">كل رقم لازم يكون أكبر من 0 ولحد 100.</Note>}
      <div className="mt-4 flex items-center gap-3">
        <button onClick={save} disabled={!changed || bad} className={`${btn.primary} flex-1`}>احفظ الحدود</button>
        {msg && <span className="text-[12px] text-muted">{msg}</span>}
      </div>
    </Card>
  )
}

/** The strategies' names: the one list (lib/strategies.json, development-plan 3.4), as everywhere on the site. */
export const LABELS: Record<string, string> = NAME_AR

/** The drawing only (no fetching), so it can be checked with sample data. */
/** The kill switch of the real account shown: every strategy on it stops entering (exits and stops still work). */
function KillSwitchPanel({ acct, cfg, reload }: { acct: string, cfg: any, reload: () => void }){
  const ks = cfg.kill_switch || {}
  const [msg, setMsg] = useState("")
  useEffect(() => setMsg(""), [acct])
  async function flip(){
    const action = ks.tripped ? "reset" : "trip"
    const text = action === "reset"
      ? `⚠️ ${accountName("live", acct)} — فلوس حقيقية\n\nفك قفل الطوارئ؟ الاستراتيجيات المفعّلة هترجع تدخل صفقات.${ks.reason ? `\n\nسبب القفل: ${ks.reason}\nلو السبب لسه موجود (زي التراجع) هيقفل تاني في الدقيقة اللي بعدها.` : ""}`
      : `⚠️ ${accountName("live", acct)} — فلوس حقيقية\n\nتشغيل قفل الطوارئ؟ مفيش دخول جديد لأي استراتيجية على الحساب ده، والخروج والوقفات شغالين.`
    if(!confirm(text)) return
    try{ await apiKillSwitch(action, acct); setMsg("✅ اتنفذ"); reload() } catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }
  return (
    <Card className={ks.tripped ? "border-loss/45" : undefined}>
      <CardHeader title={`قفل الطوارئ (${acct || "الأساسي"})`} action={<Pill tone={ks.tripped ? "loss" : "profit"}>{ks.tripped ? "شغّال" : "مش شغّال"}</Pill>}
        sub="بيوقف الدخول الجديد على الحساب ده بس · الخروج والوقفات شغالين" />
      {ks.tripped && ks.reason && <Note tone="loss">{ks.reason}</Note>}
      <div className="mt-4 flex items-center gap-3">
        <button onClick={flip} data-testid="kill-switch" className={`${btn.secondary} flex-1`}>{ks.tripped ? "فك قفل الطوارئ" : "شغّل قفل الطوارئ"}</button>
        {msg && <span className="text-[12px] text-muted">{msg}</span>}
      </div>
    </Card>
  )
}

export function LiveStrategiesView({ env, onEnv, acct = "", onAcct = () => {}, cfg, status, chosen, onToggle, account, onAccount, onSave, saving, msg, reload }: {
  env: "demo"|"live", onEnv: (e: "demo"|"live") => void, acct?: string, onAcct?: (a: string) => void, cfg: any, status: any, chosen: Set<string>, onToggle: (id: string, on: boolean) => void,
  account: string, onAccount: (v: string) => void, onSave: () => void, saving: boolean, msg: string, reload: () => void,
}){
  const envSwitch = (
    <div className="inline-flex rounded-xl border border-line bg-surface p-1">
      {(["live", "demo"] as const).map(e => (
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
  // the Demo and the real-money bot of a strategy share one status folder: only this account's bot is shown here
  const mine = (id: string) => status?.strategies?.[id]?.env === env ? status.strategies[id] : null
  const openPnl = (id: string) => ((mine(id)?.positions || []) as any[]).reduce((a, p) => a + (Number(p.pnl) || 0), 0)
  const state = (r: any): [string, Tone] => r.review?.length ? ["محتاج مراجعة", "loss"] : !chosen.has(r.id) ? ["متوقفة", "neutral"]
    : r.entry_block ? ["الدخول متوقف", "corona"] : r.running ? ["شغال", "profit"] : ["البوت مش شغال", "neutral"]
  const withBots = rows.filter(r => mine(r.id)?.running || mine(r.id)?.positions?.length)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {envSwitch}
        {env === "live" && <Pill tone={cfg.enabled ? "profit" : "loss"}>{cfg.enabled ? "التداول الحقيقي مسموح على السيرفر" : "التداول الحقيقي مقفول على السيرفر (ALLOW_LIVE_TRADING)"}</Pill>}
      </div>
      {env === "live" && (cfg.accounts?.length || 0) > 1 && (
        // each sub-account is its own Binance account: its own capital, limits, yes/no and kill switch
        <div className="flex flex-wrap items-center gap-2" data-testid="account-picker">
          <span className="text-[12px] text-faint">الحساب على Binance:</span>
          {cfg.accounts.map((a: any) => (
            <button key={a.name || "main"} onClick={() => onAcct(a.name)}
              className={`rounded-[9px] border px-3 py-1.5 text-[13px] transition ${acct === a.name ? "border-loss/45 bg-loss/10 font-semibold text-ink" : "border-line text-muted hover:text-ink"}`}>
              {a.name || "الأساسي"} <span className="text-[11px] text-faint">· {(a.strategies || []).map((s: string) => LABELS[s] || s).join("، ") || "—"}</span>
            </button>
          ))}
        </div>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_372px]">
        <Card className={env === "live" ? "border-loss/45" : "border-signal/45"}>
          <div className={`mb-3 rounded-lg px-3 py-2 text-[13px] font-semibold ${env === "live" ? "bg-loss/10 text-loss" : "bg-signal/10 text-signal"}`}>
            {env === "live" ? `بتغيّر ${accountName(env, acct)}${!acct && account.trim() ? ` "${account.trim()}"` : ""} — فلوس حقيقية` : "بتغيّر حساب الـ Demo — فلوس وهمية، وده بيأثر على قياس الـ Demo"}
          </div>
          <CardHeader title={env === "live" ? "الاستراتيجيات على الحساب الحقيقي" : "الاستراتيجيات على الـ Demo"}
            sub={share != null ? `كل استراتيجية شغالة ليها لحد ${share} صفقات (${total} مكان ÷ ${onCount})` : "تشتغل = تقدر تدخل صفقات. مقفولة = مش هتدخل جديد، والمفتوح بيخرج على قاعدته ووقفه."}
            action={<>
              {msg && <span className="text-[12px] text-muted">{msg}</span>}
              <button onClick={onSave} disabled={saving || !changed || (env === "live" && !(acct || account.trim()) && chosen.size > 0)} className={btn.secondary}>{saving ? "بيحفظ…" : "احفظ التغييرات"}</button>
            </>} />
          {env === "live" && (
            <label className="mb-4 block max-w-sm"><span className={label}>اسم الحساب (لازم يطابق BINANCE_LIVE_ACCOUNT على السيرفر)</span>
              {/* a sub-account's bot reads BINANCE_LIVE_ACCOUNT=<its name> (live_account.py): fixed here */}
              <input value={acct || account} onChange={e => onAccount(e.target.value)} readOnly={!!acct} dir="ltr" className={field} />
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
        <div className="space-y-5">
          <CapitalPanel env={env} acct={acct} cfg={cfg} reload={reload} />
          <LimitsPanel env={env} acct={acct} cfg={cfg} chosen={chosen} reload={reload} />
          {/* only from an API that reports it: a missing state must never read as "off" */}
          {env === "live" && cfg.kill_switch && <KillSwitchPanel acct={acct} cfg={cfg} reload={reload} />}
        </div>
      </div>

      {env === "demo" && <DemoMeasurement labels={LABELS} />}

      {withBots.length > 0 && <h2 className="pt-1 text-[17px] font-bold">الصفقات المفتوحة على Binance</h2>}
      {withBots.map(r => <LivePositions key={r.id} strategy={r.id} label={LABELS[r.id] || r.id} st={status.strategies[r.id]} reload={reload} />)}
    </div>
  )
}

/** What a save changes, account first: what starts, what stops entering (2026-11-03: a Demo save meant for the real
 *  account turned six strategies off, and the old text listed only the ones left on). */
export function switchConfirmText(env: "demo"|"live", account: string, saved: { id: string, on: boolean }[], chosen: Set<string>, acct = ""){
  const name = (s: string) => LABELS[s] || s
  const turnOn = saved.filter(r => !r.on && chosen.has(r.id)).map(r => name(r.id))
  const turnOff = saved.filter(r => r.on && !chosen.has(r.id)).map(r => name(r.id))
  const where = env === "demo" ? "حساب الـ Demo (فلوس وهمية)" : acct ? `${accountName(env, acct)} (فلوس حقيقية)` : `الحساب الحقيقي "${account.trim()}" (فلوس حقيقية)`
  return [`هتغيّر ${where}:`,
    turnOn.length ? `\nهتشتغل:\n${turnOn.join("\n")}` : "",
    turnOff.length ? `\nهتبطّل تدخل صفقات جديدة (المفتوح بيخرج عادي):\n${turnOff.join("\n")}` : "",
    env === "demo" && turnOff.length ? "\nالاستراتيجيات اللي هتتقفل هيقف قياسها على الـ Demo." : "",
    `\nبعد الحفظ شغالين: ${chosen.size ? [...chosen].map(name).join("، ") : "ولا واحدة"}`].filter(Boolean).join("\n")
}

/** The admin's own live account: yes/no per strategy (the activation record the bots check before every entry),
 *  and each strategy's bot with its positions. A strategy turned off stops entering; its open positions still exit. */
export function LiveStrategies(){
  // real money first (owner, 2026-11-03: the tab opened on Demo, and the real bot was hard to find)
  const [env, setEnv] = useState<"demo"|"live">("live")
  const [acct, setAcct] = useState("")          // a live strategy's own sub-account; "" = the main account
  const [cfg, setCfg] = useState<any|null|undefined>(undefined)
  const [status, setStatus] = useState<any|null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [account, setAccount] = useState("")
  const [msg, setMsg] = useState("")
  const [saving, setSaving] = useState(false)
  // the tab shown now, and whether its switches have unsaved changes: an answer for the other tab (a slow request
  // from before a tab change) is dropped, and the 15 s refresh never overwrites switches the owner is changing
  // the account too: an answer for the main account must never fill a sub-account's switches, or the other way round
  const envNow = useRef(`${env}:${acct}`)
  const dirty = useRef(false)

  const load = useCallback(async () => {
    const want = `${env}:${acct}`
    const [c, s] = await Promise.all([apiLiveStrategies(env, acct), apiLiveStatus()])
    if(envNow.current !== want) return
    setCfg(c); setStatus(s)
    if(c){
      if(!dirty.current) setChosen(new Set(c.strategies.filter((r: any) => r.on).map((r: any) => r.id)))
      if(!acct) setAccount(a => a || c.account || "")
    }
  }, [env, acct])
  useEffect(() => { load(); const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])

  async function save(){
    const list = [...chosen]
    if(!confirm(switchConfirmText(env, account, cfg?.strategies || [], chosen, env === "live" ? acct : ""))) return
    setSaving(true); setMsg("")
    try{ await apiSetLiveStrategies(env, env === "live" && acct ? acct : account.trim(), list, env === "live" ? acct : ""); dirty.current = false; setMsg("✅ اتحفظ"); load() }
    catch(e: any){ setMsg(`⚠️ ${e.message}`) }
    finally{ setSaving(false) }
  }

  const pick = (e: "demo"|"live", a: string) => { envNow.current = `${e}:${a}`; dirty.current = false; setEnv(e); setAcct(a); setCfg(undefined); setMsg("") }
  return <LiveStrategiesView env={env} onEnv={e => pick(e, e === "live" ? acct : "")} acct={env === "live" ? acct : ""} onAcct={a => pick("live", a)} cfg={cfg} status={status} chosen={chosen}
    onToggle={(id, on) => { dirty.current = true; setChosen(s => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n }) }}
    account={account} onAccount={setAccount} onSave={save} saving={saving} msg={msg} reload={load} />
}

"use client"
import { useCallback, useEffect, useState } from "react"
import { apiLiveStatus, apiLiveStrategies, apiSetCapital, apiSetLiveStrategies } from "@/lib/api"
import { LivePositions } from "@/components/LivePositions"

const usd = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`

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

const LEVEL: Record<string, [string, string, string]> = {
  low: ["منخفضة", "text-profit", "border-profit/40"], medium: ["متوسطة", "text-amber-300", "border-amber-300/40"],
  high: ["عالية", "text-loss", "border-loss/40"], very_high: ["عالية جدًا", "text-loss", "border-loss"],
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
    const risk = p ? `\nلو الوقف اتضرب في صفقة: −${usd(p.loss)} (${p.lossPct.toFixed(1)}% من راس المال) — خطورة ${LEVEL[p.level][0]}` : ""
    if(!confirm(n ? `راس المال ${usd(n)} على ${env === "demo" ? "الـ Demo" : "الحساب الحقيقي"}:\nمارجن ${usd(p!.margin)} لكل صفقة${m ? " (يدوي)" : ""}، وبحد أقصى ${p!.maxOpen} صفقة مفتوحة.${risk}` : "إلغاء خطة راس المال؟")) return
    try{ await apiSetCapital(env, n, m); setMsg("✅ اتحفظ"); reload() } catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }
  const lv = p ? LEVEL[p.level] : null
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <h2 className="text-sm font-black">راس المال والمارجن</h2>
      <p className="mt-1 text-xs text-muted">راس المال بيحدد أقصى عدد صفقات مفتوحة في نفس الوقت، وبيتقسم بالتساوي على الاستراتيجيات الشغالة، و{c.capital_reserve_pct ?? 40}% منه بيفضل احتياطي. المارجن لكل صفقة: سيبه فاضي يتحسب لوحده ({c.capital_margin_pct ?? 1}% من راس المال ومش أقل من {usd(c.capital_min_margin_usdt ?? 30)})، أو اكتبه بنفسك. رافعة 2x ووقف 40% من السعر.</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">راس المال (USDT)
          <input type="number" min={0} inputMode="decimal" value={value} onChange={e => setValue(e.target.value)} dir="ltr" placeholder="مثلا 1000"
            className="mt-1 block w-36 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm" />
        </label>
        <label className="text-xs text-muted">المارجن لكل صفقة (اختياري)
          <input type="number" min={0} inputMode="decimal" value={manual} onChange={e => setManual(e.target.value)} dir="ltr" placeholder="تلقائي"
            className="mt-1 block w-36 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm" />
        </label>
        <button onClick={save} disabled={!changed} className="rounded-lg bg-corona px-4 py-2 text-xs font-black text-bg disabled:opacity-40">احفظ</button>
        {msg && <span className="text-xs text-muted">{msg}</span>}
      </div>
      {p && lv ? <>
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
          <div className="rounded-xl border border-line/70 p-2">المارجن لكل صفقة{Number(manual) > 0 && <span className="text-faint"> (يدوي)</span>}<div className="font-mono text-base font-black" dir="ltr">{usd(p.margin)}</div><div className="text-[10px] text-faint">حجم الصفقة {usd(p.margin * LEV)}</div></div>
          <div className="rounded-xl border border-line/70 p-2">أقصى صفقات مفتوحة<div className="font-mono text-base font-black" dir="ltr">{p.maxOpen}</div></div>
          <div className="rounded-xl border border-line/70 p-2">مفتوح دلوقتي<div className="font-mono text-base font-black" dir="ltr">{c.open_trades ?? "—"}{c.plan ? ` / ${c.plan.max_open}` : ""}</div></div>
        </div>
        <div className={`mt-3 rounded-xl border ${lv[2]} p-3 text-xs`}>
          <div className="font-black">مدى الخطورة: <span className={lv[1]}>{lv[0]}</span></div>
          <ul className="mt-1 space-y-0.5 text-muted">
            <li>لو الوقف اتضرب في صفقة واحدة: <b className="text-loss" dir="ltr">−{usd(p.loss)}</b> = <b className={lv[1]}>{p.lossPct.toFixed(1)}%</b> من راس المال</li>
            <li>لو الوقف اتضرب في كل الصفقات المفتوحة مرة واحدة ({p.maxOpen}): <b className="text-loss">−{p.worst.toFixed(0)}%</b> من راس المال</li>
            <li className="text-faint">منخفضة أقل من 1% للصفقة · متوسطة 1–2% · عالية 2–5% · عالية جدًا فوق 5%</li>
          </ul>
          {p.margin * LEV < 50 && <div className="mt-1 text-loss">⚠️ حجم الصفقة {usd(p.margin * LEV)} أقل من أقل أمر على BTC في Binance ($50) — صفقات BTC هتترفض.</div>}
          {p.blockedPerTrade && <div className="mt-1 text-loss">⛔ خسارة الصفقة {p.lossPct.toFixed(1)}% أكبر من حد المخاطرة للصفقة الواحدة في دفتر المخاطرة ({c.risk_per_trade_pct}%): كل الدخول هيترفض لحد ما تقلّل المارجن أو ترفع الحد.</div>}
          {!p.blockedPerTrade && p.allowed < p.maxOpen && <div className="mt-1 text-amber-300">حد المخاطرة الإجمالي في دفتر المخاطرة ({c.max_aggregate_risk_pct}%) هيوقف الدخول عند {p.allowed} صفقة، قبل الـ {p.maxOpen}.</div>}
        </div>
      </> : <div className="mt-2 text-xs text-faint">مفيش خطة: كل بوت بيدخل بالحجم المضبوط في خدمته ومفيش حد لعدد الصفقات.</div>}
      {p && p.eff < Number(value) && <div className="mt-2 text-xs text-loss">رصيد الحساب ({usd(p.eff)}) أقل من راس المال اللي كتبته: الحساب كله على الرصيد.</div>}
    </div>
  )
}

// trades a strategy opens at once: a momentum basket is 5 long + 5 short (bot.MOM), a ratio pair 2 legs
const OPENS_AT_ONCE: Record<string, number> = { momentum_ls: 10, ratio_trend: 2 }

/** Same rule as risk_manager.strategy_slots: the account's count split evenly between the strategies on, at least 1. */
function SharePanel({ total, chosen }: { total?: number, chosen: Set<string> }){
  const k = chosen.size
  if(!total || !k) return null
  const share = Math.max(1, Math.floor(total / k))
  const starved = [...chosen].filter(s => (OPENS_AT_ONCE[s] || 1) > share)
  return (
    <div className="mt-3 text-xs text-muted">
      كل استراتيجية شغالة ليها لحد <b className="font-mono" dir="ltr">{share}</b> صفقة مفتوحة ({total} مكان في الحساب ÷ {k} استراتيجية)، ومن غير ما تعدّي الحد اللي اتجربت عليه.
      {starved.map(s => <div key={s} className="mt-1 text-loss">⚠️ {LABELS[s] || s} بتفتح {OPENS_AT_ONCE[s]} صفقات مع بعض، فبنصيب {share} مش هتدخل خالص: ارفع راس المال أو شغّل استراتيجيات أقل.</div>)}
    </div>
  )
}

const LABELS: Record<string, string> = {
  trend_daily: "ترند يومي", vol_breakout: "اختراق التقلب", rsi2_pullback: "RSI2 الارتداد", trend_breakout: "اختراق الترند",
  listing_short: "شورت العملات الجديدة", momentum_ls: "مومنتم لونج/شورت", ratio_trend: "ترند النسبة",
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

  if(cfg === undefined) return <div className="text-xs text-faint">بيحمّل…</div>
  if(cfg === null) return <div className="text-xs text-loss">مش متاح (أدمن بس)</div>
  const changed = cfg.strategies.some((r: any) => r.on !== chosen.has(r.id))
  return (
    <div className="space-y-3">
      <CapitalPanel env={env} cfg={cfg} reload={load} />
      <div className="rounded-2xl border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-black">الاستراتيجيات على حسابك</h2>
          <div className="flex gap-1 text-xs">
            {(["demo", "live"] as const).map(e => (
              <button key={e} onClick={() => { setEnv(e); setCfg(undefined); setMsg("") }}
                className={`rounded-lg px-3 py-1 font-bold ${env === e ? "bg-corona text-bg" : "border border-line text-muted"}`}>{e === "demo" ? "Demo (فلوس وهمية)" : "فلوس حقيقية"}</button>
            ))}
          </div>
        </div>
        {env === "live" && <div className={`mt-1 text-[11px] ${cfg.enabled ? "text-profit" : "text-loss"}`}>{cfg.enabled ? "التداول الحقيقي مسموح على السيرفر" : "التداول الحقيقي مقفول على السيرفر (ALLOW_LIVE_TRADING)"}</div>}
        <p className="mt-1 text-xs text-muted">نعم = الاستراتيجية تقدر تدخل صفقات على حسابك. لا = مش هتدخل جديد، والمفتوح بيخرج على قاعدته ووقفه.</p>
        {env === "live" && <label className="mt-3 block text-xs text-muted">اسم الحساب (لازم يطابق BINANCE_LIVE_ACCOUNT على السيرفر)
          <input value={account} onChange={e => setAccount(e.target.value)} dir="ltr" className="mt-1 block w-full max-w-xs rounded-lg border border-line bg-bg px-2 py-1.5 text-sm" />
        </label>}
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {cfg.strategies.map((r: any) => (
            <label key={r.id} className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-line/70 px-3 py-2">
              <span className="text-sm font-bold">{LABELS[r.id] || r.id}
                <span className={`mr-2 text-[10px] ${r.running ? "text-profit" : "text-faint"}`}>{r.running ? `شغال${r.env ? " · " + r.env : ""} · ${r.positions} صفقة` : "البوت مش شغال"}</span>
                {r.review?.length > 0 && <span className="mr-1 text-[10px] text-loss">· محتاج مراجعة</span>}
              </span>
              <span className="flex items-center gap-2 text-xs">
                <span className={chosen.has(r.id) ? "text-profit" : "text-faint"}>{chosen.has(r.id) ? "نعم" : "لا"}</span>
                <input type="checkbox" checked={chosen.has(r.id)} onChange={e => setChosen(s => { const n = new Set(s); e.target.checked ? n.add(r.id) : n.delete(r.id); return n })} />
              </span>
            </label>
          ))}
        </div>
        <SharePanel total={cfg.capital?.plan?.max_open} chosen={chosen} />
        <div className="mt-3 flex items-center gap-3">
          <button onClick={save} disabled={saving || !changed || (env === "live" && !account.trim() && chosen.size > 0)}
            className="rounded-lg bg-corona px-4 py-2 text-xs font-black text-bg disabled:opacity-40">{saving ? "بيحفظ…" : "احفظ"}</button>
          {msg && <span className="text-xs text-muted">{msg}</span>}
        </div>
      </div>
      {cfg.strategies.filter((r: any) => status?.strategies?.[r.id]?.running || status?.strategies?.[r.id]?.positions?.length).map((r: any) => (
        <LivePositions key={r.id} strategy={r.id} label={LABELS[r.id] || r.id} st={status.strategies[r.id]} reload={load} />
      ))}
    </div>
  )
}

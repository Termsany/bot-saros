"use client"
import { useCallback, useEffect, useState } from "react"
import { apiLiveStatus, apiLiveStrategies, apiSetCapital, apiSetLiveStrategies } from "@/lib/api"
import { LivePositions } from "@/components/LivePositions"

const usd = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`

/** Same rule as risk_manager.capital_plan: margin = max(min, capital × margin %); max open = capital × (1 − reserve %) ÷ margin. */
function plan(capital: number, c: any){
  if(!(capital > 0)) return null
  const margin = Math.max(c?.capital_min_margin_usdt ?? 30, capital * (c?.capital_margin_pct ?? 1) / 100)
  return { margin, maxOpen: Math.floor(capital * (1 - (c?.capital_reserve_pct ?? 40) / 100) / margin) }
}

/** The owner's capital for this account: it decides the margin per trade and the most trades open at once (all the
 *  strategies together). Entries beyond that count are refused until the capital is raised. */
function CapitalPanel({ env, cfg, reload }: { env: "demo"|"live", cfg: any, reload: () => void }){
  const c = cfg.capital || {}
  const [value, setValue] = useState<string>(c.capital_usdt ? String(c.capital_usdt) : "")
  const [msg, setMsg] = useState("")
  useEffect(() => { setValue(c.capital_usdt ? String(c.capital_usdt) : ""); setMsg("") }, [env, c.capital_usdt])
  const p = plan(Number(value), c)
  async function save(){
    const n = Number(value) || 0
    if(!confirm(n ? `راس المال ${usd(n)} على ${env === "demo" ? "الـ Demo" : "الحساب الحقيقي"}:\nمارجن ${usd(p!.margin)} لكل صفقة، وبحد أقصى ${p!.maxOpen} صفقة مفتوحة.` : "إلغاء خطة راس المال؟")) return
    try{ await apiSetCapital(env, n); setMsg("✅ اتحفظ"); reload() } catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <h2 className="text-sm font-black">راس المال</h2>
      <p className="mt-1 text-xs text-muted">بيحدد المارجن لكل صفقة وأقصى عدد صفقات مفتوحة في نفس الوقت (كل الاستراتيجيات مع بعض). أي صفقة زيادة بتترفض لحد ما ترفع راس المال. {c.capital_reserve_pct ?? 40}% بيفضل احتياطي، والمارجن {c.capital_margin_pct ?? 1}% من راس المال ومش أقل من {usd(c.capital_min_margin_usdt ?? 30)}، رافعة 2x.</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">راس المال (USDT)
          <input type="number" min={0} inputMode="decimal" value={value} onChange={e => setValue(e.target.value)} dir="ltr" placeholder="مثلا 1000"
            className="mt-1 block w-40 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm" />
        </label>
        <button onClick={save} disabled={Number(value) === (c.capital_usdt || 0)} className="rounded-lg bg-corona px-4 py-2 text-xs font-black text-bg disabled:opacity-40">احفظ</button>
        {msg && <span className="text-xs text-muted">{msg}</span>}
      </div>
      {p ? <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
        <div className="rounded-xl border border-line/70 p-2">المارجن لكل صفقة<div className="font-mono text-base font-black" dir="ltr">{usd(p.margin)}</div></div>
        <div className="rounded-xl border border-line/70 p-2">أقصى صفقات مفتوحة<div className="font-mono text-base font-black" dir="ltr">{p.maxOpen}</div></div>
        <div className="rounded-xl border border-line/70 p-2">مفتوح دلوقتي<div className="font-mono text-base font-black" dir="ltr">{c.open_trades ?? "—"}{c.plan ? ` / ${c.plan.max_open}` : ""}</div></div>
      </div> : <div className="mt-2 text-xs text-faint">مفيش خطة: كل بوت بيدخل بالحجم المضبوط في خدمته ومفيش حد لعدد الصفقات.</div>}
      {c.plan && c.plan.effective_capital < c.plan.capital && <div className="mt-2 text-xs text-loss">رصيد الحساب أقل من راس المال: العدد محسوب على {usd(c.plan.effective_capital)}.</div>}
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

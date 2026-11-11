"use client"
import { useEffect, useState } from "react"
import { AppShell } from "@/components/AppShell"
import { Card, CardHeader, PageHeader, Pill, btn, field, label } from "@/components/ui"
import { ShieldCheck, Eye, EyeOff, Power, CheckCircle2 } from "lucide-react"
import { authHeaders } from "@/lib/supabase"
import { CONSENT_TEXT } from "@/lib/liveConsent"
import { UserBots } from "@/components/UserBots"
import { UserMfa } from "@/components/UserMfa"
import { apiUserBotsRisk, type LiveRisk } from "@/lib/api"
import { LIVE_STRATEGIES, LIVE_NAMES } from "@/lib/liveStrategies"
import { useLocale, useT } from "@/lib/i18n/locale"

// The page's words (Figma "RAQM — Global Redesign 2026"); the consent text itself stays English (the server compares it).
const T = {
  ar: {
    rLev: "الرافعة من 1 لـ 5", rTrade: "المخاطرة لكل صفقة لحد 1%", rMax: "أقصى مخاطرة مفتوحة لحد 3%", rOrder: "المخاطرة لكل صفقة لازم تكون أقل من أقصى مخاطرة مفتوحة",
    needKeys: "ضع API Key و Secret", saved: "تم الحفظ بشكل مشفر ✓", saveFailed: "فشل الحفظ", needConsent: "لازم تكتب نص الموافقة بالكامل وتعلّم المربع",
    consented: "تم تسجيل موافقتك على Binance Demo — اختار البوتات تحت", enableFailed: "فشل التفعيل", confirmOff: "إيقاف التداول الحقيقي الخاص بك الآن؟", off: "تم إيقاف LIVE",
    sKeys: "مفاتيح المنصة", sKeysDone: "اتحفظت · من غير سحب", sKeysNow: "احفظ مفاتيحك", sRisk: "حدود المخاطرة", sRiskDone: (l: number, r: number) => `x${l} · ${r}% للصفقة`,
    sConsent: "الموافقة", sConsentDone: "اتكتبت ✓", sConsentNow: "اقرا واكتب النص", sOn: "التفعيل", sOnDone: (x?: string) => `شغال على ${x}`, sOnWait: "مستني الخطوات اللي قبله",
    fLev: "الرافعة (1–5)", fTrade: "المخاطرة لكل صفقة % (لحد 1)", fMax: "أقصى مخاطرة مفتوحة % (لحد 3)",
    title: "بوتاتي على Binance (Demo)", subtitle: "مفاتيح Binance Demo بتاعتك · فلوس وهمية · مستقل تمامًا عن حساب الإدارة",
    onPill: (env: string, x?: string) => `● ${env} على ${x}`, notOn: "مش مفعّل",
    c1: "1 · مفاتيح المنصة", c1Sub: "بتتشفر على السيرفر ومش بترجع للمتصفح تاني", exchange: "المنصة", hide: "اخفي", show: "اظهر", okxOnly: "Passphrase (OKX بس)", saveEnc: "احفظ متشفّر",
    c2: "2 · حدود المخاطرة", c2Sub: "بتتسجل مع الموافقة · السيرفر بيرفض أي قيمة برا الحدود دي",
    riskLine: (r: number, m: number) => <>لو الوقف اتضرب في صفقة: بتخسر <b className="font-mono text-loss">{r}%</b> من رصيدك · كل الصفقات المفتوحة مع بعض: <b className="font-mono text-ink">{m}%</b> بالكتير</>,
    c3: "3 · الموافقة والتفعيل", c3Sub: "على مسؤوليتك الخاصة",
    agreed: (x?: string, demo?: boolean, l?: number, r?: number, m?: number) => `موافق على ${x}${demo ? " Demo" : ""} · x${l} · ${r}% للصفقة · أقصى ${m}%`,
    withdraw: "اسحب موافقتك (الدخول بيقف)",
    meaning: "معنى الموافقة: الحساب والمفاتيح بتوعك، وانت بتشغّل التداول الحقيقي بفلوسك وعلى مسؤوليتك، بعيد عن إدارة المنصة. وفاهم إن ده ممكن يخسّرك فلوس، وانت المسؤول بالكامل.",
    typeExact: "اكتب النص الإنجليزي ده بالظبط (السيرفر بيقارنه حرف بحرف):", typeHere: "اكتب نص الموافقة بالكامل هنا", understood: "قريت وفاهم المخاطر بالكامل",
    agreeBtn: (x?: string) => `وافق على ${x} Demo (فلوس وهمية)`, keysFirst: (x?: string) => `احفظ مفاتيح ${x} الأول.`,
    account: "حالة حسابك", keysOf: (x: string) => `مفاتيح ${x}`, keyPaper: "محفوظة · Paper", keyNone: "مش موجودة", realTrading: "التداول الحقيقي", running: "شغال",
    demoOnly: <><b className="text-corona">دلوقتي على Binance Demo بس</b> (فلوس وهمية): اعمل مفاتيح من وضع Demo Trading في Binance. الفلوس الحقيقية مقفولة لحد ما الاستراتيجيات تخلص قياسها.</>,
    mDemo: "Demo · فلوس وهمية", mLive: "فلوس حقيقية", mLiveNote: "بالدعوة بس · momentum و/أو RSI-2 · على حسابك انت في Binance",
    stratsL: "الاستراتيجيات — واحدة أو الاتنين (كل واحدة لحد 10 صفقات في نفس الوقت)", stratsNeed: "اختار استراتيجية واحدة على الأقل",
    cAmount: "2 · المبلغ والمارجن", cAmountSub: "انت اللي بتحددهم · السيرفر بيحسب الخطورة ومش بيقبل غير اللي وافقت عليه",
    capital: "راس المال ($) — مش أكتر من رصيدك على Binance", marginL: "المارجن لكل صفقة ($)",
    reserveL: "الاحتياطي (%) — برّه الصفقات",
    fits: (n: number, legs: number) => `بيدخل ${n} صفقة من ${legs} في السلة`,
    floorNote: (pct: number) => `لو رصيدك نزل تحت ${pct}% من راس المال، البوت مش بيفتح سلة جديدة لحد ما تراجع (الوقفات والخروج شغالين)`,
    size: "حجم الصفقة", oneStop: "لو الوقف اتضرب في صفقة", worst: (n: number) => `أسوأ حالة (الـ ${n} وقفات)`, ofCapital: "من راس المال",
    levels: { low: "خطورة منخفضة", medium: "خطورة متوسطة", high: "خطورة عالية", very_high: "خطورة عالية جدًا" } as Record<string, string>,
    lCalc: "بيحسب…", lNeed: "اكتب راس المال والمارجن",
    minNote: "BTC محتاج مارجن $25 وETH $10 على الأقل (أقل أمر على Binance) — أقل من كده بيتسابوا",
    acceptLevel: (lvl: string, worst: string, pct: number) => `بوافق على ${lvl}: أسوأ حالة ممكن تخسّرني ${worst} (${pct}% من راس المال)، على مسؤوليتي`,
    agreeLive: "وافق على الفلوس الحقيقية",
    agreedLive: (cap?: number | null, mar?: number | null, s?: string) => `موافق على فلوس حقيقية · ${s} · راس مال $${cap} · مارجن $${mar} للصفقة`,
    sRiskLive: (lvl: string, worst: string) => `${lvl} · أسوأ حالة ${worst}`,
    liveNote: <><b className="text-loss">فلوس حقيقية</b>: البوت بيتداول بفلوسك على حسابك انت في Binance، وممكن تخسر. المفتاح لازم يكون <b>مقفول على IP السيرفر</b> وعليه <b>Reading وFutures بس</b>: السحب والتحويلات والـ Spot/Margin والـ Options كلها مقفولة. السيرفر بيتأكد من ده بنفسه قبل أول صفقة وكل يوم بعدها، ومفتاح مش كده بيترفض والبوت بيبطّل يفتح صفقات.</>,
  },
  en: {
    rLev: "Leverage is 1 to 5", rTrade: "Risk per trade is up to 1%", rMax: "Max open risk is up to 3%", rOrder: "Risk per trade must be below the max open risk",
    needKeys: "Enter the API key and secret", saved: "Saved, encrypted ✓", saveFailed: "Saving failed", needConsent: "Type the whole consent text and tick the box",
    consented: "Your consent for Binance Demo is recorded — pick your bots below", enableFailed: "Enabling failed", confirmOff: "Stop your own trading now?", off: "LIVE stopped",
    sKeys: "Exchange keys", sKeysDone: "Saved · no withdrawals", sKeysNow: "Save your keys", sRisk: "Risk limits", sRiskDone: (l: number, r: number) => `x${l} · ${r}% per trade`,
    sConsent: "Consent", sConsentDone: "Typed ✓", sConsentNow: "Read and type the text", sOn: "Enable", sOnDone: (x?: string) => `Running on ${x}`, sOnWait: "Waiting for the steps before",
    fLev: "Leverage (1–5)", fTrade: "Risk per trade % (up to 1)", fMax: "Max open risk % (up to 3)",
    title: "My Binance Demo bots", subtitle: "Your own Binance Demo keys · play money · fully apart from the admin account",
    onPill: (env: string, x?: string) => `● ${env} on ${x}`, notOn: "Not enabled",
    c1: "1 · Exchange keys", c1Sub: "Encrypted on the server and never sent back to the browser", exchange: "Exchange", hide: "Hide", show: "Show", okxOnly: "Passphrase (OKX only)", saveEnc: "Save encrypted",
    c2: "2 · Risk limits", c2Sub: "Recorded with your consent · the server refuses any value outside these limits",
    riskLine: (r: number, m: number) => <>If a trade's stop is hit, you lose <b className="font-mono text-loss">{r}%</b> of your balance · all open trades together: <b className="font-mono text-ink">{m}%</b> at most</>,
    c3: "3 · Consent and enabling", c3Sub: "At your own risk",
    agreed: (x?: string, demo?: boolean, l?: number, r?: number, m?: number) => `Agreed on ${x}${demo ? " Demo" : ""} · x${l} · ${r}% per trade · max ${m}%`,
    withdraw: "Withdraw your consent (entries stop)",
    meaning: "What the consent means: the account and keys are yours, and you run the trading with your money and at your own risk, apart from the platform's management. You understand this can lose you money, and you are fully responsible.",
    typeExact: "Type this English text exactly (the server compares it letter by letter):", typeHere: "Type the whole consent text here", understood: "I have read and fully understand the risks",
    agreeBtn: (x?: string) => `Agree on ${x} Demo (play money)`, keysFirst: (x?: string) => `Save your ${x} keys first.`,
    account: "Your account", keysOf: (x: string) => `${x} keys`, keyPaper: "Saved · Paper", keyNone: "None", realTrading: "Trading", running: "Running",
    demoOnly: <><b className="text-corona">Binance Demo only for now</b> (play money): create keys in Binance's Demo Trading mode. Real money stays locked until the strategies finish their measurement.</>,
    mDemo: "Demo · play money", mLive: "Real money", mLiveNote: "By invitation · momentum and/or RSI-2 · on your own Binance account",
    stratsL: "Strategies — one or both (each up to 10 trades at once)", stratsNeed: "Pick at least one strategy",
    cAmount: "2 · Amount and margin", cAmountSub: "You set them · the server computes the risk and holds you to what you accepted",
    capital: "Capital ($) — not more than your Binance balance", marginL: "Margin per trade ($)",
    reserveL: "Reserve (%) — kept out of trades",
    fits: (n: number, legs: number) => `${n} of the basket's ${legs} trades fit`,
    floorNote: (pct: number) => `If your balance falls under ${pct}% of the capital, the bot opens no new basket until you look (stops and exits keep working)`,
    size: "Trade size", oneStop: "If one trade's stop is hit", worst: (n: number) => `Worst case (all ${n} stops)`, ofCapital: "of the capital",
    levels: { low: "Low risk", medium: "Medium risk", high: "High risk", very_high: "Very high risk" } as Record<string, string>,
    lCalc: "Computing…", lNeed: "Enter the capital and the margin",
    minNote: "BTC needs a $25 margin and ETH $10 at least (Binance's smallest order) — below that they're skipped",
    acceptLevel: (lvl: string, worst: string, pct: number) => `I accept ${lvl}: the worst case can lose me ${worst} (${pct}% of the capital), at my own risk`,
    agreeLive: "Agree to real money",
    agreedLive: (cap?: number | null, mar?: number | null, s?: string) => `Agreed to real money · ${s} · capital $${cap} · margin $${mar} per trade`,
    sRiskLive: (lvl: string, worst: string) => `${lvl} · worst case ${worst}`,
    liveNote: <><b className="text-loss">Real money</b>: the bot trades your money on your own Binance account, and you can lose. The key must be <b>restricted to the server's IP</b> with <b>Reading and Futures only</b>: withdrawals, transfers, Spot/Margin and Options all off. The server checks this itself before the first trade and every day after; a key that isn't is refused and the bot stops opening trades.</>,
  },
}

const EXCHANGES = [
  { id: "binance", name: "Binance" },
  { id: "bybit", name: "Bybit" },
  { id: "okx", name: "OKX" },
  { id: "mexc", name: "MEXC" },
] as const

type KeyStatus = { configured: boolean; paper: boolean }
type LiveStatus = { enabled: boolean; exchange?: string; leverage?: number; risk_per_trade_pct?: number; max_aggregate_risk_pct?: number; consented_at?: string; environment?: string; capital_usdt?: number | null; margin_usdt?: number | null; strategies?: string[] | null }

/**
 * User-facing live-trading settings — require_user, NOT admin. Every call here
 * is scoped by the signed-in session's own user id on the backend
 * (/api/user/keys/*, /api/user/live/*); there is no user_id field anywhere in
 * these requests for a client to spoof.
 */
export default function UserLiveSettingsPage() {
  const t = useT(T)
  const locale = useLocale()
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const [status, setStatus] = useState<Record<string, KeyStatus>>({})
  const [liveStatus, setLiveStatus] = useState<LiveStatus>({ enabled: false })
  const [apiKey, setApiKey] = useState("")
  const [secret, setSecret] = useState("")
  const [passphrase, setPassphrase] = useState("")
  const [show, setShow] = useState(false)
  const [exchange, setExchange] = useState<string>("binance")
  const [confirmText, setConfirmText] = useState("")
  const [agreeChecked, setAgreeChecked] = useState(false)
  const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  // same defaults and caps as backend/app/user_live_activation.py (the backend re-checks them)
  const [leverage, setLeverage] = useState(2)
  const [riskPerTrade, setRiskPerTrade] = useState(0.25)
  const [maxRisk, setMaxRisk] = useState(1)
  const [money, setMoney] = useState<"demo" | "live">("demo")
  const [capital, setCapital] = useState("1000")
  const [margin, setMargin] = useState("20")
  const [reserve, setReserve] = useState("40")      // user_bots.LIVE_RESERVE_DEFAULT; the whole basket must fit after it
  const [liveStrats, setLiveStrats] = useState<string[]>(["momentum_ls"])   // real money: momentum and/or RSI-2 (owner, 2026-11-07)
  const [risk, setRisk] = useState<LiveRisk | null>(null)
  const [riskBusy, setRiskBusy] = useState(false)
  const live = money === "live"
  useEffect(() => {           // the risk of the numbers typed, from the server (the same numbers it will hold the user to)
    if (!live) return
    const cap = Number(capital), mar = Number(margin), res = Number(reserve)
    if (!(cap > 0 && mar > 0) || reserve === "" || !(res >= 0) || !liveStrats.length) { setRisk(null); return }
    setRiskBusy(true)
    const id = setTimeout(async () => { setRisk(await apiUserBotsRisk(cap, mar, res, liveStrats)); setRiskBusy(false) }, 300)
    return () => clearTimeout(id)
  }, [live, capital, margin, reserve, liveStrats])
  const ordered = (s: string[]) => LIVE_STRATEGIES.filter(x => s.includes(x)) as string[]
  function toggleStrat(s: string){
    setLiveStrats(cur => cur.includes(s) ? (cur.length > 1 ? cur.filter(x => x !== s) : cur) : ordered([...cur, s]))
  }
  const usd = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
  const liveRiskError = !liveStrats.length ? t.stratsNeed : !(Number(capital) > 0 && Number(margin) > 0) ? t.lNeed : riskBusy || !risk ? t.lCalc : !risk.ok ? (risk.why || t.lNeed) : ""
  const demoRiskError = !(leverage >= 1 && leverage <= 5) ? t.rLev
    : !(riskPerTrade > 0 && riskPerTrade <= 1) ? t.rTrade
    : !(maxRisk > 0 && maxRisk <= 3) ? t.rMax
    : riskPerTrade > maxRisk ? t.rOrder : ""
  const riskError = live ? liveRiskError : demoRiskError

  async function loadStatus() {
    try {
      const r = await fetch(`${API}/api/user/keys/status`, { headers: await authHeaders() })
      if (r.ok) setStatus(await r.json())
    } catch {}
    try {
      const r2 = await fetch(`${API}/api/user/live/status`, { headers: await authHeaders() })
      if (r2.ok) {
        const ls = await r2.json(); setLiveStatus(ls)
        if (ls.enabled && ls.environment === "live" && ls.capital_usdt && ls.margin_usdt) {   // a real-money consent: show it
          setMoney("live"); setCapital(String(ls.capital_usdt)); setMargin(String(ls.margin_usdt))
          if (Array.isArray(ls.strategies) && ls.strategies.length) setLiveStrats(ordered(ls.strategies))
        }
      }
    } catch {}
    try {   // the reserve saved with the bots (it isn't part of the consent: it changes how many trades fit, not a stop's cost)
      const r3 = await fetch(`${API}/api/user/bots`, { headers: await authHeaders() })
      if (r3.ok) { const b = await r3.json(); if (b?.desired?.env === "live" && b.desired.capital_reserve_pct != null) setReserve(String(b.desired.capital_reserve_pct))
        if (b?.desired?.env === "live" && Array.isArray(b.desired.strategies) && b.desired.strategies.length) setLiveStrats(ordered(b.desired.strategies)) }
    } catch {}
  }
  useEffect(() => { loadStatus() }, [])

  // Write-only: the key/secret/passphrase fields are cleared immediately after a
  // successful submit and are NEVER re-populated from the backend (status is
  // configured/paper booleans only — the raw values never round-trip back here).
  async function saveKeys() {
    if (!apiKey || !secret) { setMsg({ type: "error", text: t.needKeys }); return }
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`${API}/api/user/keys/save`, {
        method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ exchange, apiKey, secret, passphrase }),
      })
      const j = await r.json().catch(() => ({}))
      if (r.ok && j.ok) {
        setMsg({ type: "success", text: t.saved })
        setApiKey(""); setSecret(""); setPassphrase("")
        loadStatus()
      } else {
        setMsg({ type: "error", text: j.detail || t.saveFailed })
      }
    } catch (e: any) {
      setMsg({ type: "error", text: String(e?.message || e) })
    } finally {
      setBusy(false)
    }
  }

  async function enableLive() {
    if (riskError) { setMsg({ type: "error", text: riskError }); return }
    if (confirmText !== CONSENT_TEXT || !agreeChecked) {
      setMsg({ type: "error", text: t.needConsent })
      return
    }
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`${API}/api/user/live/enable`, {
        method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
        // users trade on Binance Demo only for now (docs/phase2-design.md): the consent is recorded for Demo
        body: JSON.stringify(live
          ? { exchange, confirm: confirmText, environment: "live", capital_usdt: Number(capital), margin_usdt: Number(margin), strategies: liveStrats }
          : { exchange, confirm: confirmText, leverage, risk_per_trade_pct: riskPerTrade, max_aggregate_risk_pct: maxRisk, environment: "demo" }),
      })
      const j = await r.json().catch(() => ({}))
      if (r.ok) {
        setMsg({ type: "success", text: t.consented })
        setConfirmText(""); setAgreeChecked(false)
        loadStatus()
      } else {
        setMsg({ type: "error", text: j.detail || t.enableFailed })
      }
    } catch (e: any) {
      setMsg({ type: "error", text: String(e?.message || e) })
    } finally {
      setBusy(false)
    }
  }

  async function disableLive() {
    if (!confirm(t.confirmOff)) return
    setBusy(true)
    try {
      await fetch(`${API}/api/user/live/disable`, { method: "POST", headers: await authHeaders() })
      setMsg({ type: "success", text: t.off })
      loadStatus()
    } finally {
      setBusy(false)
    }
  }

  const keysReady = !!status[exchange]?.configured
  // a consent counts for what is on screen: Demo, or real money for exactly these numbers and strategies it covers (a change asks again)
  const covered = liveStatus.strategies || ["momentum_ls"]
  const consented = liveStatus.enabled && (!live || (liveStatus.environment === "live"
    && Number(capital) === Number(liveStatus.capital_usdt) && Number(margin) === Number(liveStatus.margin_usdt)
    && liveStrats.every(s => covered.includes(s))))
  const consentReady = confirmText === CONSENT_TEXT && agreeChecked
  const exName = EXCHANGES.find(e => e.id === exchange)?.name
  const steps: [string, string, "done" | "now" | "todo"][] = [
    [t.sKeys, keysReady ? t.sKeysDone : t.sKeysNow, keysReady ? "done" : "now"],
    [t.sRisk, riskError ? riskError : live && risk ? t.sRiskLive(t.levels[risk.level], usd(risk.worst_usdt)) : t.sRiskDone(leverage, riskPerTrade), !keysReady ? "todo" : riskError ? "now" : "done"],
    [t.sConsent, consentReady ? t.sConsentDone : t.sConsentNow, !keysReady || riskError ? "todo" : consentReady ? "done" : "now"],
    [t.sOn, consented ? t.sOnDone(liveStatus.exchange) : t.sOnWait, consented ? "done" : consentReady ? "now" : "todo"],
  ]
  const riskFields: [string, number, (v: number) => void, number][] = [
    [t.fLev, leverage, setLeverage, 1],
    [t.fTrade, riskPerTrade, setRiskPerTrade, 0.05],
    [t.fMax, maxRisk, setMaxRisk, 0.25],
  ]
  return (
    <AppShell active="/settings/live" themed>
      <PageHeader title={t.title} subtitle={t.subtitle}
        status={<Pill tone={liveStatus.enabled ? "profit" : "neutral"}>{liveStatus.enabled ? t.onPill(liveStatus.environment === "demo" ? "Demo" : "LIVE", liveStatus.exchange) : t.notOn}</Pill>}/>

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl border border-line bg-surface p-1" role="tablist" data-testid="money-switch">
          {(["demo", "live"] as const).map(m => (
            <button key={m} role="tab" aria-selected={money === m} onClick={() => { setMoney(m); setMsg(null); setConfirmText(""); setAgreeChecked(false) }}
              className={`rounded-lg px-4 py-2 text-[13px] font-semibold transition ${money === m ? (m === "live" ? "bg-loss text-white" : "bg-corona text-on-corona") : "text-muted hover:text-ink"}`}>
              {m === "live" ? t.mLive : t.mDemo}
            </button>
          ))}
        </div>
        {live && <span className="text-[12px] text-faint">{t.mLiveNote}</span>}
      </div>

      <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map(([t, h, s], i) => (
          <li key={t} className={`flex items-center gap-3 rounded-[14px] border px-4 py-3.5 ${s === "now" ? "border-corona bg-corona/[0.08]" : "border-line bg-surface"}`}>
            <span className={`grid h-[30px] w-[30px] shrink-0 place-items-center rounded-full font-mono text-sm ${s === "done" ? "bg-profit/15 text-profit" : s === "now" ? "bg-corona/15 text-corona" : "bg-surface2 text-faint"}`}>{s === "done" ? "✓" : i + 1}</span>
            <div className="min-w-0"><div className={`text-[15px] font-semibold ${s === "todo" ? "text-muted" : ""}`}>{t}</div><div className={`truncate text-[12px] ${s === "done" ? "text-profit" : "text-faint"}`}>{h}</div></div>
          </li>
        ))}
      </ol>

      {msg && (
        <div className={`rounded-xl border p-3 text-sm ${msg.type === "success" ? "border-profit/30 bg-profit/[0.06] text-profit" : "border-loss/30 bg-loss/[0.06] text-loss"}`}>{msg.text}</div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-5">
          {live && <UserMfa locale={locale} />}
          {/* Save/update own key — write-only form, never re-displayed */}
          <Card>
            <CardHeader title={t.c1} sub={t.c1Sub}/>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block"><span className={label}>{t.exchange}</span>
                <select value={exchange} onChange={e => setExchange(e.target.value)} className={field}>
                  {EXCHANGES.map(ex => <option key={ex.id} value={ex.id}>{ex.name}</option>)}
                </select>
              </label>
              <label className="block"><span className={label}>API key</span>
                <input value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="API key" className={`${field} font-mono`} dir="ltr"/>
              </label>
              <label className="relative block"><span className={label}>Secret</span>
                <input value={secret} onChange={e => setSecret(e.target.value)} type={show ? "text" : "password"} placeholder="Secret" className={`${field} pe-10 font-mono`} dir="ltr"/>
                <button type="button" onClick={() => setShow(!show)} aria-label={show ? t.hide : t.show} className="absolute bottom-3 end-3 text-faint hover:text-ink">{show ? <EyeOff size={15}/> : <Eye size={15}/>}</button>
              </label>
              {exchange === "okx" && (
                <label className="block"><span className={label}>{t.okxOnly}</span>
                  <input value={passphrase} onChange={e => setPassphrase(e.target.value)} type={show ? "text" : "password"} className={`${field} font-mono`} dir="ltr"/>
                </label>
              )}
            </div>
            <button onClick={saveKeys} disabled={busy} className={`${btn.secondary} mt-4`}><ShieldCheck size={15}/> {t.saveEnc}</button>
          </Card>

          {live ? (
          <Card className="border-loss/30">
            <CardHeader title={t.cAmount} sub={t.cAmountSub} action={risk?.ok && <Pill tone={risk.level === "low" ? "profit" : risk.level === "medium" ? "corona" : "loss"}>{t.levels[risk.level]}</Pill>}/>
            <span className={label}>{t.stratsL}</span>
            <div className="mb-4 grid gap-2 sm:grid-cols-2" data-testid="live-strategies">
              {LIVE_STRATEGIES.map(s => {
                const on = liveStrats.includes(s), [name, desc] = LIVE_NAMES[locale === "en" ? "en" : "ar"][s]
                return (
                  <button key={s} type="button" role="checkbox" aria-checked={on} onClick={() => toggleStrat(s)}
                    className={`rounded-xl border px-3 py-2.5 text-start ${on ? "border-loss bg-loss/10" : "border-line"}`}>
                    <div className="text-[14px] font-semibold">{on ? "✓ " : ""}{name}</div>
                    <div className="text-[11px] text-faint">{desc}</div>
                  </button>
                )
              })}
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block"><span className={label}>{t.capital}</span>
                <input type="number" min={0} inputMode="decimal" value={capital} onChange={e => setCapital(e.target.value)} className={`${field} font-mono`} dir="ltr"/></label>
              <label className="block"><span className={label}>{t.marginL}</span>
                <input type="number" min={0} inputMode="decimal" value={margin} onChange={e => setMargin(e.target.value)} className={`${field} font-mono`} dir="ltr"/></label>
              <label className="block"><span className={label}>{t.reserveL}</span>
                <input type="number" min={10} max={60} step={5} inputMode="decimal" value={reserve} onChange={e => setReserve(e.target.value)} className={`${field} font-mono`} dir="ltr" data-testid="live-reserve"/></label>
            </div>
            {risk && risk.ok ? (
              <div className="mt-4 grid gap-2 sm:grid-cols-3" data-testid="live-risk">
                {[[t.size, usd(Number(margin) * 2), ""], [t.oneStop, `−${usd(risk.one_stop_usdt)}`, `${risk.per_trade_pct}% ${t.ofCapital}`],
                  [t.worst(risk.legs), `−${usd(risk.worst_usdt)}`, `${risk.aggregate_pct}% ${t.ofCapital}`]].map(([l, v, h]) => (
                  <div key={l} className="min-w-0 rounded-[10px] bg-surface2 px-3 py-2.5">
                    <div className="truncate text-[11px] text-muted">{l}</div>
                    <div className="font-mono text-[15px] font-semibold tabular" dir="ltr">{v}</div>
                    {h && <div className="truncate text-[11px] text-faint">{h}</div>}
                  </div>
                ))}
              </div>
            ) : <div className={`mt-4 rounded-xl px-4 py-3 text-[13px] ${riskError && riskError !== t.lCalc ? "bg-loss/10 text-loss" : "bg-surface2 text-muted"}`}>{riskError}</div>}
            {risk && risk.ok && <p className="mt-3 text-[12px] text-muted" data-testid="live-fits">{t.fits(Math.min(risk.max_open, risk.legs), risk.legs)}</p>}
            <p className="mt-2 text-[12px] text-faint">{t.floorNote(80)}</p>
            <p className="mt-1 text-[12px] text-faint">{t.minNote}</p>
          </Card>
          ) : (
          <Card>
            <CardHeader title={t.c2} sub={t.c2Sub}/>
            <div className="grid gap-3 sm:grid-cols-3">
              {riskFields.map(([l, v, set, step]) => (
                <label key={l} className="block"><span className={label}>{l}</span>
                  <input type="number" value={v} step={step} min={0} onChange={e => set(Number(e.target.value))} className={`${field} font-mono`} dir="ltr"/>
                </label>
              ))}
            </div>
            <div className={`mt-4 rounded-xl px-4 py-3 text-[13px] ${riskError ? "bg-loss/10 text-loss" : "bg-surface2 text-muted"}`}>
              {riskError || t.riskLine(riskPerTrade, maxRisk)}
            </div>
          </Card>
          )}

          {/* Explicit consent + enable/disable */}
          <Card className={consented ? "border-profit/40" : live ? "border-loss/40" : "border-corona/30"}>
            <CardHeader title={t.c3} sub={t.c3Sub}/>
            {consented ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm text-profit"><CheckCircle2 size={16}/> {live
                  ? t.agreedLive(liveStatus.capital_usdt, liveStatus.margin_usdt, covered.map(s => LIVE_NAMES[locale === "en" ? "en" : "ar"][s]?.[0] || s).join(" + "))
                  : t.agreed(liveStatus.exchange, liveStatus.environment === "demo", liveStatus.leverage, liveStatus.risk_per_trade_pct, liveStatus.max_aggregate_risk_pct)}</div>
                <button onClick={disableLive} disabled={busy} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-loss px-4 py-2.5 text-sm font-semibold text-void"><Power size={15}/> {t.withdraw}</button>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-[14px] leading-7 text-muted">{t.meaning}</p>
                <p className="text-[12px] text-faint">{t.typeExact}</p>
                <div className="rounded-xl border border-line bg-void p-3 font-mono text-[12px] leading-6" dir="ltr">{CONSENT_TEXT}</div>
                <textarea value={confirmText} onChange={e => setConfirmText(e.target.value)} placeholder={t.typeHere} rows={3} className={`${field} font-mono text-[12px]`} dir="ltr"/>
                <label className="flex items-center gap-2 text-sm font-semibold">
                  <input type="checkbox" checked={agreeChecked} onChange={e => setAgreeChecked(e.target.checked)} className="h-4 w-4 accent-corona"/>
                  {live && risk?.ok ? t.acceptLevel(t.levels[risk.level], usd(risk.worst_usdt), risk.aggregate_pct) : t.understood}
                </label>
                <button onClick={enableLive} disabled={busy || !consentReady || !!riskError || !keysReady}
                  className={live ? "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-loss px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40" : `${btn.primary} w-full`}>
                  {live ? t.agreeLive : t.agreeBtn(exName)}</button>
                {!keysReady && <p className="text-[12px] text-faint">{t.keysFirst(exName)}</p>}
              </div>
            )}
          </Card>

          <UserBots consent={liveStatus} locale={locale} money={money} liveCapital={Number(capital)} liveMargin={Number(margin)} liveReserve={Number(reserve)} liveConsented={consented && live && !!risk?.ok} liveStrategies={liveStrats} />
        </div>

        <Card>
          <h2 className="mb-3 text-[17px] font-bold">{t.account}</h2>
          {/* Key-configured status per exchange — configured/paper booleans only, never the key value */}
          <div className="divide-y divide-line">
            {EXCHANGES.map(ex => {
              const st = status[ex.id] || { configured: false, paper: true }
              return (
                <div key={ex.id} className="flex items-center justify-between py-2.5 text-[13px]">
                  <span className="text-muted">{t.keysOf(ex.name)}</span>
                  <Pill tone={st.configured ? (st.paper ? "corona" : "profit") : "neutral"}>{st.configured ? (st.paper ? t.keyPaper : "LIVE") : t.keyNone}</Pill>
                </div>
              )
            })}
            <div className="flex items-center justify-between py-2.5 text-[13px]">
              <span className="text-muted">{t.realTrading}</span>
              <Pill tone={liveStatus.enabled ? "profit" : "neutral"}>{liveStatus.enabled ? t.running : t.notOn}</Pill>
            </div>
          </div>
          <p className="mt-4 rounded-xl border border-corona/40 bg-corona/[0.06] p-3 text-[12px] leading-6 text-muted">{live ? t.liveNote : t.demoOnly}</p>
        </Card>
      </div>
    </AppShell>
  )
}

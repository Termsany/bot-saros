"use client"
import { useEffect, useState } from "react"
import { AppShell } from "@/components/AppShell"
import { Card, CardHeader, PageHeader, Pill, btn, field, label } from "@/components/ui"
import { ShieldCheck, Eye, EyeOff, Power, CheckCircle2 } from "lucide-react"
import { authHeaders } from "@/lib/supabase"
import { CONSENT_TEXT } from "@/lib/liveConsent"
import { UserBots } from "@/components/UserBots"
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
  },
}

const EXCHANGES = [
  { id: "binance", name: "Binance" },
  { id: "bybit", name: "Bybit" },
  { id: "okx", name: "OKX" },
  { id: "mexc", name: "MEXC" },
] as const

type KeyStatus = { configured: boolean; paper: boolean }
type LiveStatus = { enabled: boolean; exchange?: string; leverage?: number; risk_per_trade_pct?: number; max_aggregate_risk_pct?: number; consented_at?: string; environment?: string }

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
  const riskError = !(leverage >= 1 && leverage <= 5) ? t.rLev
    : !(riskPerTrade > 0 && riskPerTrade <= 1) ? t.rTrade
    : !(maxRisk > 0 && maxRisk <= 3) ? t.rMax
    : riskPerTrade > maxRisk ? t.rOrder : ""

  async function loadStatus() {
    try {
      const r = await fetch(`${API}/api/user/keys/status`, { headers: await authHeaders() })
      if (r.ok) setStatus(await r.json())
    } catch {}
    try {
      const r2 = await fetch(`${API}/api/user/live/status`, { headers: await authHeaders() })
      if (r2.ok) setLiveStatus(await r2.json())
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
        body: JSON.stringify({ exchange, confirm: confirmText, leverage, risk_per_trade_pct: riskPerTrade, max_aggregate_risk_pct: maxRisk, environment: "demo" }),
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
  const consentReady = confirmText === CONSENT_TEXT && agreeChecked
  const exName = EXCHANGES.find(e => e.id === exchange)?.name
  const steps: [string, string, "done" | "now" | "todo"][] = [
    [t.sKeys, keysReady ? t.sKeysDone : t.sKeysNow, keysReady ? "done" : "now"],
    [t.sRisk, riskError ? riskError : t.sRiskDone(leverage, riskPerTrade), !keysReady ? "todo" : riskError ? "now" : "done"],
    [t.sConsent, consentReady ? t.sConsentDone : t.sConsentNow, !keysReady || riskError ? "todo" : consentReady ? "done" : "now"],
    [t.sOn, liveStatus.enabled ? t.sOnDone(liveStatus.exchange) : t.sOnWait, liveStatus.enabled ? "done" : consentReady ? "now" : "todo"],
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

          {/* Explicit consent + enable/disable */}
          <Card className={liveStatus.enabled ? "border-profit/40" : "border-corona/30"}>
            <CardHeader title={t.c3} sub={t.c3Sub}/>
            {liveStatus.enabled ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm text-profit"><CheckCircle2 size={16}/> {t.agreed(liveStatus.exchange, liveStatus.environment === "demo", liveStatus.leverage, liveStatus.risk_per_trade_pct, liveStatus.max_aggregate_risk_pct)}</div>
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
                  {t.understood}
                </label>
                <button onClick={enableLive} disabled={busy || !consentReady || !!riskError || !keysReady} className={`${btn.primary} w-full`}>{t.agreeBtn(exName)}</button>
                {!keysReady && <p className="text-[12px] text-faint">{t.keysFirst(exName)}</p>}
              </div>
            )}
          </Card>

          <UserBots consent={liveStatus} locale={locale} />
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
          <p className="mt-4 rounded-xl border border-corona/40 bg-corona/[0.06] p-3 text-[12px] leading-6 text-muted">{t.demoOnly}</p>
        </Card>
      </div>
    </AppShell>
  )
}

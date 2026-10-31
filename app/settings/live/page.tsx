"use client"
import { useEffect, useState } from "react"
import { AppShell } from "@/components/AppShell"
import { Card, CardHeader, PageHeader, Pill, btn, field, label } from "@/components/ui"
import { ShieldCheck, Eye, EyeOff, Power, CheckCircle2 } from "lucide-react"
import { authHeaders } from "@/lib/supabase"
import { CONSENT_TEXT } from "@/lib/liveConsent"

const EXCHANGES = [
  { id: "binance", name: "Binance" },
  { id: "bybit", name: "Bybit" },
  { id: "okx", name: "OKX" },
  { id: "mexc", name: "MEXC" },
] as const

type KeyStatus = { configured: boolean; paper: boolean }
type LiveStatus = { enabled: boolean; exchange?: string; leverage?: number; risk_per_trade_pct?: number; max_aggregate_risk_pct?: number; consented_at?: string }

/**
 * User-facing live-trading settings — require_user, NOT admin. Every call here
 * is scoped by the signed-in session's own user id on the backend
 * (/api/user/keys/*, /api/user/live/*); there is no user_id field anywhere in
 * these requests for a client to spoof.
 */
export default function UserLiveSettingsPage() {
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
  const riskError = !(leverage >= 1 && leverage <= 5) ? "الرافعة من 1 لـ 5"
    : !(riskPerTrade > 0 && riskPerTrade <= 1) ? "المخاطرة لكل صفقة لحد 1%"
    : !(maxRisk > 0 && maxRisk <= 3) ? "أقصى مخاطرة مفتوحة لحد 3%"
    : riskPerTrade > maxRisk ? "المخاطرة لكل صفقة لازم تكون أقل من أقصى مخاطرة مفتوحة" : ""

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
    if (!apiKey || !secret) { setMsg({ type: "error", text: "ضع API Key و Secret" }); return }
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`${API}/api/user/keys/save`, {
        method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ exchange, apiKey, secret, passphrase }),
      })
      const j = await r.json().catch(() => ({}))
      if (r.ok && j.ok) {
        setMsg({ type: "success", text: "تم الحفظ بشكل مشفر ✓" })
        setApiKey(""); setSecret(""); setPassphrase("")
        loadStatus()
      } else {
        setMsg({ type: "error", text: j.detail || "فشل الحفظ" })
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
      setMsg({ type: "error", text: "لازم تكتب نص الموافقة بالكامل وتعلّم المربع" })
      return
    }
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`${API}/api/user/live/enable`, {
        method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ exchange, confirm: confirmText, leverage, risk_per_trade_pct: riskPerTrade, max_aggregate_risk_pct: maxRisk }),
      })
      const j = await r.json().catch(() => ({}))
      if (r.ok) {
        setMsg({ type: "success", text: "تم تفعيل LIVE على مسؤوليتك الخاصة" })
        setConfirmText(""); setAgreeChecked(false)
        loadStatus()
      } else {
        setMsg({ type: "error", text: j.detail || "فشل التفعيل" })
      }
    } catch (e: any) {
      setMsg({ type: "error", text: String(e?.message || e) })
    } finally {
      setBusy(false)
    }
  }

  async function disableLive() {
    if (!confirm("إيقاف التداول الحقيقي الخاص بك الآن؟")) return
    setBusy(true)
    try {
      await fetch(`${API}/api/user/live/disable`, { method: "POST", headers: await authHeaders() })
      setMsg({ type: "success", text: "تم إيقاف LIVE" })
      loadStatus()
    } finally {
      setBusy(false)
    }
  }

  const keysReady = !!status[exchange]?.configured
  const consentReady = confirmText === CONSENT_TEXT && agreeChecked
  const exName = EXCHANGES.find(e => e.id === exchange)?.name
  const steps: [string, string, "done" | "now" | "todo"][] = [
    ["مفاتيح المنصة", keysReady ? "اتحفظت · من غير سحب" : "احفظ مفاتيحك", keysReady ? "done" : "now"],
    ["حدود المخاطرة", riskError ? riskError : `x${leverage} · ${riskPerTrade}% للصفقة`, !keysReady ? "todo" : riskError ? "now" : "done"],
    ["الموافقة", consentReady ? "اتكتبت ✓" : "اقرا واكتب النص", !keysReady || riskError ? "todo" : consentReady ? "done" : "now"],
    ["التفعيل", liveStatus.enabled ? `شغال على ${liveStatus.exchange}` : "مستني الخطوات اللي قبله", liveStatus.enabled ? "done" : consentReady ? "now" : "todo"],
  ]
  const riskFields: [string, number, (v: number) => void, number][] = [
    ["الرافعة (1–5)", leverage, setLeverage, 1],
    ["المخاطرة لكل صفقة % (لحد 1)", riskPerTrade, setRiskPerTrade, 0.05],
    ["أقصى مخاطرة مفتوحة % (لحد 3)", maxRisk, setMaxRisk, 0.25],
  ]
  return (
    <AppShell active="/settings/live">
      <PageHeader title="التداول الحقيقي على حسابك" subtitle="حسابك، مفاتيحك، قرارك · مستقل تمامًا عن حساب الإدارة"
        status={<Pill tone={liveStatus.enabled ? "profit" : "neutral"}>{liveStatus.enabled ? `● LIVE على ${liveStatus.exchange}` : "مش مفعّل"}</Pill>}/>

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
            <CardHeader title="1 · مفاتيح المنصة" sub="بتتشفر على السيرفر ومش بترجع للمتصفح تاني"/>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block"><span className={label}>المنصة</span>
                <select value={exchange} onChange={e => setExchange(e.target.value)} className={field}>
                  {EXCHANGES.map(ex => <option key={ex.id} value={ex.id}>{ex.name}</option>)}
                </select>
              </label>
              <label className="block"><span className={label}>API key</span>
                <input value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="API key" className={`${field} font-mono`} dir="ltr"/>
              </label>
              <label className="relative block"><span className={label}>Secret</span>
                <input value={secret} onChange={e => setSecret(e.target.value)} type={show ? "text" : "password"} placeholder="Secret" className={`${field} pr-10 font-mono`} dir="ltr"/>
                <button type="button" onClick={() => setShow(!show)} aria-label={show ? "اخفي" : "اظهر"} className="absolute bottom-3 right-3 text-faint hover:text-ink">{show ? <EyeOff size={15}/> : <Eye size={15}/>}</button>
              </label>
              {exchange === "okx" && (
                <label className="block"><span className={label}>Passphrase (OKX بس)</span>
                  <input value={passphrase} onChange={e => setPassphrase(e.target.value)} type={show ? "text" : "password"} className={`${field} font-mono`} dir="ltr"/>
                </label>
              )}
            </div>
            <button onClick={saveKeys} disabled={busy} className={`${btn.secondary} mt-4`}><ShieldCheck size={15}/> احفظ متشفّر</button>
          </Card>

          <Card>
            <CardHeader title="2 · حدود المخاطرة" sub="بتتسجل مع الموافقة · السيرفر بيرفض أي قيمة برا الحدود دي"/>
            <div className="grid gap-3 sm:grid-cols-3">
              {riskFields.map(([l, v, set, step]) => (
                <label key={l} className="block"><span className={label}>{l}</span>
                  <input type="number" value={v} step={step} min={0} onChange={e => set(Number(e.target.value))} className={`${field} font-mono`} dir="ltr"/>
                </label>
              ))}
            </div>
            <div className={`mt-4 rounded-xl px-4 py-3 text-[13px] ${riskError ? "bg-loss/10 text-loss" : "bg-surface2 text-muted"}`}>
              {riskError || <>لو الوقف اتضرب في صفقة: بتخسر <b className="font-mono text-loss">{riskPerTrade}%</b> من رصيدك · كل الصفقات المفتوحة مع بعض: <b className="font-mono text-ink">{maxRisk}%</b> بالكتير</>}
            </div>
          </Card>

          {/* Explicit consent + enable/disable */}
          <Card className={liveStatus.enabled ? "border-profit/40" : "border-corona/30"}>
            <CardHeader title="3 · الموافقة والتفعيل" sub="على مسؤوليتك الخاصة"/>
            {liveStatus.enabled ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm text-profit"><CheckCircle2 size={16}/> LIVE مفعّل على {liveStatus.exchange} · x{liveStatus.leverage} · {liveStatus.risk_per_trade_pct}% للصفقة · أقصى {liveStatus.max_aggregate_risk_pct}%</div>
                <button onClick={disableLive} disabled={busy} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-loss px-4 py-2.5 text-sm font-semibold text-void"><Power size={15}/> وقّف التداول الحقيقي دلوقتي</button>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-[14px] leading-7 text-muted">معنى الموافقة: الحساب والمفاتيح بتوعك، وانت بتشغّل التداول الحقيقي بفلوسك وعلى مسؤوليتك، بعيد عن إدارة المنصة. وفاهم إن ده ممكن يخسّرك فلوس، وانت المسؤول بالكامل.</p>
                <p className="text-[12px] text-faint">اكتب النص الإنجليزي ده بالظبط (السيرفر بيقارنه حرف بحرف):</p>
                <div className="rounded-xl border border-line bg-void p-3 font-mono text-[12px] leading-6" dir="ltr">{CONSENT_TEXT}</div>
                <textarea value={confirmText} onChange={e => setConfirmText(e.target.value)} placeholder="اكتب نص الموافقة بالكامل هنا" rows={3} className={`${field} font-mono text-[12px]`} dir="ltr"/>
                <label className="flex items-center gap-2 text-sm font-semibold">
                  <input type="checkbox" checked={agreeChecked} onChange={e => setAgreeChecked(e.target.checked)} className="h-4 w-4 accent-corona"/>
                  قريت وفاهم المخاطر بالكامل
                </label>
                <button onClick={enableLive} disabled={busy || !consentReady || !!riskError || !keysReady} className={`${btn.primary} w-full`}>فعّل LIVE على {exName}</button>
                {!keysReady && <p className="text-[12px] text-faint">احفظ مفاتيح {exName} الأول.</p>}
              </div>
            )}
          </Card>
        </div>

        <Card>
          <h2 className="mb-3 text-[17px] font-bold">حالة حسابك</h2>
          {/* Key-configured status per exchange — configured/paper booleans only, never the key value */}
          <div className="divide-y divide-line">
            {EXCHANGES.map(ex => {
              const st = status[ex.id] || { configured: false, paper: true }
              return (
                <div key={ex.id} className="flex items-center justify-between py-2.5 text-[13px]">
                  <span className="text-muted">مفاتيح {ex.name}</span>
                  <Pill tone={st.configured ? (st.paper ? "corona" : "profit") : "neutral"}>{st.configured ? (st.paper ? "محفوظة · Paper" : "LIVE") : "مش موجودة"}</Pill>
                </div>
              )
            })}
            <div className="flex items-center justify-between py-2.5 text-[13px]">
              <span className="text-muted">التداول الحقيقي</span>
              <Pill tone={liveStatus.enabled ? "profit" : "neutral"}>{liveStatus.enabled ? "شغال" : "مش مفعّل"}</Pill>
            </div>
          </div>
          <p className="mt-4 rounded-xl border border-loss/40 bg-loss/[0.06] p-3 text-[12px] leading-6 text-muted"><b className="text-loss">لو التداول الحقيقي مقفول على السيرفر</b> هيترفض التفعيل حتى لو كمّلت الخطوات. تقدر تجهّز مفاتيحك وحدودك من دلوقتي.</p>
        </Card>
      </div>
    </AppShell>
  )
}

"use client"
import { useEffect, useState } from "react"
import { Logo } from "@/components/Logo"
import { ShieldCheck, Eye, EyeOff, Power, AlertTriangle, Key, CheckCircle2 } from "lucide-react"
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
    if (confirmText !== CONSENT_TEXT || !agreeChecked) {
      setMsg({ type: "error", text: "لازم تكتب نص الموافقة بالكامل وتعلّم المربع" })
      return
    }
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`${API}/api/user/live/enable`, {
        method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ exchange, confirm: confirmText }),
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

  return (
    <div className="min-h-screen bg-void text-ink">
      <header className="flex h-16 items-center justify-between border-b border-line bg-surface/90 backdrop-blur px-5 lg:px-8 sticky top-0 z-30">
        <Logo />
        <a href="/dashboard" className="px-4 py-2 rounded bg-corona text-void text-xs font-bold">المنصة</a>
      </header>

      <div className="mx-auto max-w-[900px] px-5 lg:px-8 py-8 space-y-6">
        <div>
          <h1 className="text-lg font-black flex items-center gap-2"><Key size={16} className="text-corona"/> إعدادات التداول الحقيقي الخاصة بك</h1>
          <p className="font-mono text-xs text-faint">حسابك، مفاتيحك، قرارك — مستقل تمامًا عن حساب الأدمن</p>
        </div>

        {msg && (
          <div className={`rounded-xl border p-3 text-xs ${msg.type === "success" ? "border-profit/30 bg-profit/[0.06] text-profit" : "border-loss/30 bg-loss/[0.06] text-loss"}`}>
            {msg.text}
          </div>
        )}

        {/* Key-configured status per exchange — configured/paper booleans only, never the key value */}
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="text-sm font-bold mb-3">حالة مفاتيحك</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {EXCHANGES.map(ex => {
              const st = status[ex.id] || { configured: false, paper: true }
              return (
                <div key={ex.id} className="rounded-lg border border-line p-2 text-center">
                  <div className="text-xs font-bold">{ex.name}</div>
                  <div className={`text-[11px] font-mono ${st.configured ? (st.paper ? "text-corona" : "text-profit") : "text-faint"}`}>
                    {st.configured ? (st.paper ? "Paper" : "LIVE") : "غير مربوط"}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        {/* Save/update own key — write-only form, never re-displayed */}
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="text-sm font-bold mb-3">حفظ/تحديث مفاتيحك</h2>
          <div className="space-y-2">
            <select value={exchange} onChange={e => setExchange(e.target.value)}
              className="w-full bg-surface border border-line rounded-lg px-3 py-2.5 text-xs">
              {EXCHANGES.map(ex => <option key={ex.id} value={ex.id}>{ex.name}</option>)}
            </select>
            <input value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="API Key"
              className="w-full bg-surface border border-line rounded-lg px-3 py-2.5 text-xs font-mono"/>
            <div className="relative">
              <input value={secret} onChange={e => setSecret(e.target.value)} type={show ? "text" : "password"} placeholder="Secret"
                className="w-full bg-surface border border-line rounded-lg px-3 py-2.5 pr-9 text-xs font-mono"/>
              <button onClick={() => setShow(!show)} className="absolute right-2 top-1/2 -translate-y-1/2 text-faint">
                {show ? <EyeOff size={14}/> : <Eye size={14}/>}
              </button>
            </div>
            {exchange === "okx" && (
              <input value={passphrase} onChange={e => setPassphrase(e.target.value)} type={show ? "text" : "password"}
                placeholder="Passphrase (OKX فقط)" className="w-full bg-surface border border-line rounded-lg px-3 py-2.5 text-xs font-mono"/>
            )}
            <button onClick={saveKeys} disabled={busy}
              className="w-full py-2.5 rounded-lg text-xs font-bold bg-line hover:bg-surface2 border border-line text-white flex items-center justify-center gap-2">
              <ShieldCheck size={12}/> حفظ مشفر
            </button>
          </div>
        </section>

        {/* Explicit consent + enable/disable */}
        <section className="rounded-xl border border-corona/30 bg-corona/[0.04] p-4">
          <h2 className="text-sm font-bold mb-2 flex items-center gap-2"><AlertTriangle size={14} className="text-corona"/> تفعيل LIVE — على مسؤوليتك الخاصة</h2>
          {liveStatus.enabled ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-profit"><CheckCircle2 size={14}/> LIVE مفعّل على {liveStatus.exchange}</div>
              <button onClick={disableLive} disabled={busy}
                className="w-full py-2.5 rounded-lg text-xs font-bold bg-loss text-void flex items-center justify-center gap-2">
                <Power size={12}/> إيقاف التداول الحقيقي الآن
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="rounded-lg border border-line bg-surface p-3 text-[11px] font-mono leading-relaxed" dir="ltr">
                {CONSENT_TEXT}
              </div>
              <textarea value={confirmText} onChange={e => setConfirmText(e.target.value)}
                placeholder="اكتب نص الموافقة بالكامل هنا"
                className="w-full bg-surface border border-line rounded-lg px-3 py-2.5 text-xs font-mono" rows={3} dir="ltr"/>
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={agreeChecked} onChange={e => setAgreeChecked(e.target.checked)}/>
                أوافق وأفهم المخاطر بالكامل
              </label>
              <button onClick={enableLive} disabled={busy || confirmText !== CONSENT_TEXT || !agreeChecked}
                className="w-full py-2.5 rounded-lg text-xs font-bold bg-corona text-void disabled:opacity-40">
                تفعيل LIVE على {exchange}
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

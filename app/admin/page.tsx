"use client"
import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { Activity, BarChart3, Bot, CircleDollarSign, ClipboardList, Gauge, History, LockKeyhole, Settings2, ShieldAlert, ShieldCheck, Users as UsersIcon, WalletCards } from "lucide-react"
import { Logo } from "@/components/Logo"
import { AppShell } from "@/components/AppShell"
import { PageHeader, Pill } from "@/components/ui"
import { LiveStrategies } from "@/components/LiveStrategies"
import { TIERS } from "@/lib/strategies"
import { apiIsAdmin } from "@/lib/api"
import { authHeaders } from "@/lib/supabase"

type Json = Record<string, any>
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const AUTO_REFRESH_MS = 30000

const sections: [string, string, React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>][] = [
  ["overview", "نظرة عامة", Gauge],
  ["users", "المستخدمون والباقات", UsersIcon],
  ["finance", "المالية", CircleDollarSign],
  ["live", "البوتات الحية", Bot],
  ["real", "التداول الحقيقي", WalletCards],
  ["strategies", "الاستراتيجيات", BarChart3],
  ["paper", "المحفظة الورقية", WalletCards],
  ["risk", "المخاطر والأمان", ShieldCheck],
  ["readiness", "جاهزية التشغيل", LockKeyhole],
  ["health", "صحة النظام", Activity],
  ["recovery", "Recovery & Reconciliation", ShieldAlert],
  ["timeline", "الخط الزمني", History],
  ["audit", "سجل التدقيق", ClipboardList],
  ["settings", "الإعدادات", Settings2],
]

/** Arabic labels for all 8 admin_control.STRATEGIES ids — the last one (default)
 *  has no running VPS service and must always show "no_service", never fabricated data. */
const STRATEGY_LABELS_AR: Record<string, string> = {
  trend_daily: "ترند يومي", listing_short: "شورت العملات الجديدة", momentum_ls: "مومنتم لونج/شورت",
  ratio_trend: "ترند النسبة", vol_breakout: "اختراق التقلب", rsi2_pullback: "RSI2 الارتداد",
  trend_breakout: "اختراق الترند", default: "Default",
}
const REAL_BOT_IDS = ["trend_daily", "listing_short", "momentum_ls", "ratio_trend", "vol_breakout", "rsi2_pullback", "trend_breakout"]
const NO_SERVICE_IDS = ["default"]
const ALL_STRATEGY_IDS = [...REAL_BOT_IDS, ...NO_SERVICE_IDS]

const STATUS_META: Record<string, [string, string]> = {
  running: ["يعمل", "bg-emerald-500/15 text-profit border-emerald-500/40"],
  stale: ["بيانات قديمة", "bg-yellow-500/15 text-yellow-300 border-yellow-500/40"],
  unavailable: ["غير متاح", "bg-loss/15 text-loss border-loss/40"],
  no_service: ["لا توجد خدمة", "bg-neutral-500/15 text-neutral-300 border-neutral-500/40"],
}

function StatusBadge({ status }: { status?: string }) {
  const [label, cls] = STATUS_META[status || ""] || ["—", "bg-neutral-500/15 text-neutral-300 border-neutral-500/40"]
  return <span className={`px-2 py-0.5 rounded-lg text-[10px] font-bold border whitespace-nowrap ${cls}`}>{label}</span>
}

function timeAgo(iso?: string | null): string {
  if (!iso) return "—"
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (!Number.isFinite(diff)) return "—"
  if (diff < 5) return "الآن"
  if (diff < 60) return `منذ ${Math.floor(diff)} ثانية`
  if (diff < 3600) return `منذ ${Math.floor(diff / 60)} دقيقة`
  if (diff < 86400) return `منذ ${Math.floor(diff / 3600)} ساعة`
  return `منذ ${Math.floor(diff / 86400)} يوم`
}

function pnlColor(v: number): string { return v >= 0 ? "text-profit" : "text-loss" }
function fmtNum(v: any, digits = 2): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : "—"
}

/** Cumulative-PnL equity sparkline built from a bot's own trade history — plain inline SVG, no chart library. */
function EquitySparkline({ points }: { points: number[] }) {
  if (!points.length) return <div className="text-[11px] text-muted">لا يوجد سجل صفقات كافٍ لرسم المنحنى</div>
  const w = 300, h = 64, pad = 6
  const min = Math.min(...points, 0), max = Math.max(...points, 0)
  const range = max - min || 1
  const step = points.length > 1 ? (w - pad * 2) / (points.length - 1) : 0
  const path = points.map((v, i) => {
    const x = pad + i * step
    const y = h - pad - ((v - min) / range) * (h - pad * 2)
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(" ")
  const last = points[points.length - 1]
  const color = last >= 0 ? "#34d399" : "#f87171"
  const zeroY = h - pad - ((0 - min) / range) * (h - pad * 2)
  return (
    <svg width={w} height={h} className="overflow-visible" role="img" aria-label="equity curve">
      <line x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} stroke="#444" strokeDasharray="2,2" />
      <path d={path} fill="none" stroke={color} strokeWidth={1.6} />
    </svg>
  )
}

type Column = { key: string; label: string; fmt?: (v: any, row: Json) => any }

/** Generic sortable + filterable table used for live-bot positions and trade history. */
function SortableTable({ columns, rows, filterKey }: { columns: Column[]; rows: Json[]; filterKey?: string }) {
  const [sortKey, setSortKey] = useState<string>(columns[0]?.key || "")
  const [sortDir, setSortDir] = useState<1 | -1>(-1)
  const [filter, setFilter] = useState("")
  const filtered = useMemo(() => {
    let r = rows
    if (filter) {
      const f = filter.toLowerCase()
      r = filterKey ? r.filter(x => String(x[filterKey] ?? "").toLowerCase().includes(f)) : r.filter(x => JSON.stringify(x).toLowerCase().includes(f))
    }
    return [...r].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir
      return String(av).localeCompare(String(bv)) * sortDir
    })
  }, [rows, sortKey, sortDir, filter, filterKey])
  return (
    <div>
      <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="تصفية..."
        className="mb-2 px-2 py-1 rounded-lg border border-line bg-void text-xs w-full max-w-[220px]" />
      <div className="overflow-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-muted">
              {columns.map(c => (
                <th key={c.key}
                  onClick={() => { if (sortKey === c.key) setSortDir(d => (d * -1) as 1 | -1); else { setSortKey(c.key); setSortDir(-1) } }}
                  className="p-1.5 text-right cursor-pointer select-none whitespace-nowrap">
                  {c.label}{sortKey === c.key ? (sortDir === 1 ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {columns.map(c => <td key={c.key} className="p-1.5 whitespace-nowrap">{c.fmt ? c.fmt(r[c.key], r) : String(r[c.key] ?? "—")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <div className="text-[11px] text-muted p-2">لا توجد بيانات</div>}
    </div>
  )
}

const POSITION_COLUMNS: Column[] = [
  { key: "symbol", label: "الرمز" }, { key: "side", label: "الجهة" },
  { key: "entry", label: "الدخول", fmt: v => fmtNum(v) }, { key: "price", label: "السعر", fmt: v => fmtNum(v) },
  { key: "qty", label: "الكمية", fmt: v => fmtNum(v, 4) },
  { key: "pnl", label: "PnL", fmt: v => <span className={pnlColor(Number(v) || 0)}>{fmtNum(v)}</span> },
  { key: "pnl_pct", label: "PnL%", fmt: v => fmtNum(v) }, { key: "sl", label: "SL", fmt: v => fmtNum(v) }, { key: "tp", label: "TP", fmt: v => fmtNum(v) },
]
const HISTORY_COLUMNS: Column[] = [
  { key: "symbol", label: "الرمز" }, { key: "side", label: "الجهة" },
  { key: "entry", label: "الدخول", fmt: v => fmtNum(v) }, { key: "exit", label: "الخروج", fmt: v => fmtNum(v) },
  { key: "qty", label: "الكمية", fmt: v => fmtNum(v, 4) },
  { key: "pnl", label: "PnL", fmt: v => <span className={pnlColor(Number(v) || 0)}>{fmtNum(v)}</span> },
]

function Mini({ label, value }: { label: string; value: any }) {
  return <div className="rounded-lg border border-line p-2"><div className="text-muted text-[10px]">{label}</div><div className="font-bold text-sm mt-1">{String(value)}</div></div>
}

/** One real (or no-service) VPS bot — expandable: positions table, history table, equity sparkline. */
function LiveBotCard({ id, entry }: { id: string; entry: Json | undefined }) {
  const [open, setOpen] = useState(false)
  const e = entry || {}
  const status: string = e.status || "unavailable"
  const stats = e.stats || {}
  const positions: Json[] = e.positions || []
  const history: Json[] = e.history || []
  const totalPnl = (Number(stats.realized) || 0) + (Number(stats.unrealized) || 0)
  const equity = useMemo(() => {
    let acc = 0
    return (history as Json[]).map(h => { acc += Number(h.pnl) || 0; return acc })
  }, [history])
  return (
    <div className="rounded-xl border border-line bg-surface/60 p-3">
      <button onClick={() => setOpen(o => !o)} className="w-full flex flex-wrap items-center justify-between gap-2 text-right">
        <div className="flex items-center gap-2"><span className="font-bold text-xs">{STRATEGY_LABELS_AR[id] || id}</span><StatusBadge status={status} /></div>
        <div className="flex items-center gap-3 text-[11px] text-muted">
          {status !== "no_service" && <>
            <span>مراكز: {positions.length}</span>
            <span className={pnlColor(totalPnl)}>PnL: {fmtNum(totalPnl)}</span>
            <span>{timeAgo(e.updated)}</span>
          </>}
          <span>{open ? "▲" : "▼"}</span>
        </div>
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          {status === "no_service" ? (
            <p className="text-xs text-muted">لا توجد خدمة تشغيل حقيقية (systemd) لهذه الاستراتيجية على الـ VPS — لا تتوفر بيانات مباشرة.</p>
          ) : status === "unavailable" ? (
            <p className="text-xs text-loss">تعذر الوصول إلى ملف الحالة العام لهذا البوت الآن{e.error ? ` (${e.error})` : ""}. لا تُعرض بيانات ملفّقة.</p>
          ) : (
            <>
              <div className="grid md:grid-cols-4 gap-2">
                <Mini label="صفقات مغلقة" value={stats.closed ?? "—"} />
                <Mini label="فوز/خسارة" value={`${stats.wins ?? "—"}/${stats.losses ?? "—"}`} />
                <Mini label="PnL محقق" value={fmtNum(stats.realized)} />
                <Mini label="PnL غير محقق" value={fmtNum(stats.unrealized)} />
              </div>
              <div>
                <div className="text-[11px] text-muted mb-1">منحنى الأرباح التراكمي (من سجل الصفقات)</div>
                <EquitySparkline points={equity} />
              </div>
              <div>
                <div className="text-[11px] text-muted mb-1">المراكز المفتوحة ({positions.length})</div>
                <SortableTable columns={POSITION_COLUMNS} rows={positions} filterKey="symbol" />
              </div>
              <div>
                <div className="text-[11px] text-muted mb-1">سجل الصفقات ({history.length})</div>
                <SortableTable columns={HISTORY_COLUMNS} rows={history} filterKey="symbol" />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function AdminPage() {
  const [section, setSection] = useState("overview")
  const [data, setData] = useState<Json>({})
  const [error, setError] = useState("")
  const [endpointErrors, setEndpointErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [access, setAccess] = useState<"checking" | "allowed" | "denied">("checking")
  const loadingRef = useRef(false)

  const load = async () => {
    if (loadingRef.current) return
    loadingRef.current = true
    setLoading(true)
    const endpoints: [string, string][] = [
      ["overview", "overview"], ["strategies", "strategies"], ["paper", "paper/portfolio"],
      ["risk", "risk"], ["readiness", "readiness"], ["health", "health"], ["recovery", "recovery"], ["activation", "activation"], ["audit", "audit"], ["users", "users"], ["finance", "finance"],
    ]
    try {
      const h = await authHeaders()
      const results = await Promise.all(endpoints.map(async ([key, path]) => {
        try {
          const response = await fetch(`${API}/api/admin/${path}`, { headers: h, cache: "no-store" })
          const payload = await response.json().catch(() => ({}))
          return { key, response, payload }
        } catch {
          return { key, response: null, payload: {}, message: "تعذر الاتصال بالمصدر" }
        }
      }))
      if (results.some(r => r.response?.status === 401 || r.response?.status === 403)) throw Error("ليس لديك صلاحية أدمن")
      const nextData: Json = {}
      const nextErrors: Record<string, string> = {}
      for (const result of results) {
        if (result.response?.ok) nextData[result.key] = result.payload
        else nextErrors[result.key] = result.message || result.payload?.detail || `تعذر تحميل ${result.key}`
      }
      setData((previous) => ({ ...previous, ...nextData }))
      setEndpointErrors(nextErrors)
      setError("")
      setLastRefreshed(new Date())
    } catch (e: any) {
      setError(e.message || "تعذر الاتصال")
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }
  const selectSection = (id: string) => {
    setSection(id)
    const url = new URL(window.location.href)
    url.searchParams.set("tab", id)
    window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`)
  }
  const sectionEndpoints: Record<string, string[]> = { overview: ["overview", "recovery"], users: ["users"], finance: ["finance"], live: ["paper"], real: [], strategies: ["strategies"], paper: ["paper"], risk: ["risk", "recovery"], readiness: ["readiness"], health: ["health", "recovery", "activation"], recovery: ["recovery"], timeline: ["audit", "recovery"], audit: ["audit"], settings: [] }
  const currentSectionErrors = sectionEndpoints[section]?.map(key => endpointErrors[key]).filter(Boolean) as string[] || []
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab")
    if (requested && sections.some(([id]) => id === requested)) setSection(requested)
    let active = true
    apiIsAdmin().then(isAdmin => {
      if (!active) return
      setAccess(isAdmin ? "allowed" : "denied")
      if (isAdmin) void load()
    })
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (!autoRefresh || access !== "allowed") return
    const t = setInterval(load, AUTO_REFRESH_MS)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, access])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen(o => !o) }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const action = async (path: string, method: string, body: Json) => {
    setBusy(true)
    try {
      const r = await fetch(API + path, { method, headers: { ...(await authHeaders()), "Content-Type": "application/json" }, body: JSON.stringify(body) })
      const j = await r.json()
      if (!r.ok) throw Error(j.detail || "فشل الإجراء")
      await load()
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  const confirmAction = (m: string, fn: () => void) => { if (window.confirm(m)) fn() }

  const o = data.overview || {}
  const risk = data.risk?.state || {}
  const recovery: Json = data.recovery || {}
  const liveBotsPortfolio: Json = data.paper?.live_bots || {}
  const liveStrategies: Json = liveBotsPortfolio.strategies || {}
  const liveSummaryOverview: Json = o.live_bots?.summary || liveBotsPortfolio.aggregate || {}
  const dashboardBot: Json = data.paper?.dashboard_bot || { positions: data.paper?.positions || [], history: data.paper?.history || [] }
  const recoveryRequired = recovery.recovery_required || {}
  const recoveryAlerts = Object.entries(recoveryRequired).map(([symbol, item]: [string, any]) => ({ title: `Recovery مطلوب · ${symbol}`, message: item?.reason || "يوجد وضع يحتاج مراجعة", severity: "critical", at: item?.at }))
  const reconciliationStale = recovery.reconciliation?.state && recovery.reconciliation.state !== "ok"
  if (reconciliationStale) recoveryAlerts.push({ title: "Reconciliation", message: `الحالة الحالية: ${recovery.reconciliation.state}`, severity: "warning", at: recovery.reconciliation?.at })
  const otherAlerts = [
    ...(Array.isArray(o.alerts) ? o.alerts : []),
    ...(Array.isArray(o.warnings) ? o.warnings : []),
    ...(Array.isArray(o.recovery_warnings) ? o.recovery_warnings : []),
    ...(Array.isArray(data.health?.alerts) ? data.health.alerts : []),
    ...(risk.kill_switch?.tripped ? [{ title: "Kill switch", message: "مفعل حاليًا ويمنع الإدخالات الجديدة.", severity: "critical" }] : []),
    ...(o.entry_paused?.paused ? [{ title: "إيقاف الإدخالات", message: "الإدخالات الجديدة متوقفة.", severity: "warning" }] : []),
  ]
  const operationalAlerts = [...recoveryAlerts, ...otherAlerts]
  const globalSeverity: "ok" | "warning" | "critical" = operationalAlerts.some(a => a.severity === "critical" || a.severity === "error")
    ? "critical" : operationalAlerts.length > 0 ? "warning" : "ok"
  const timelineEvents: TimelineEvent[] = [
    ...(data.audit?.items || []).map((x: Json) => ({ at: x.at, title: x.action || "إجراء إداري", detail: `${x.actor || "—"} · ${x.result || "—"}`, kind: "audit" as const })),
    ...otherAlerts.map((a: Json) => ({ title: a.title || "تنبيه", detail: a.message || "", kind: "alert" as const })),
    ...Object.entries(recoveryRequired).map(([symbol, item]: [string, any]) => ({ at: item?.at, title: `Recovery · ${symbol}`, detail: item?.reason || "مراجعة مطلوبة", kind: "recovery" as const })),
    ...(reconciliationStale ? [{ at: recovery.reconciliation?.at, title: "Reconciliation", detail: `الحالة الحالية: ${recovery.reconciliation.state}`, kind: "recovery" as const }] : []),
  ]
  const paletteItems: CommandItem[] = [
    ...sections.map(([id, label]) => ({ id: `tab-${id}`, label: `فتح تبويب: ${label}`, hint: "تبويب", onSelect: () => selectSection(id) })),
    ...ALL_STRATEGY_IDS.map(id => ({ id: `strategy-${id}`, label: STRATEGY_LABELS_AR[id] || id, hint: "استراتيجية · البوتات الحية", onSelect: () => selectSection("live") })),
  ]

  if (access !== "allowed") {
    return (
      <div dir="rtl" className="min-h-screen bg-void text-ink grid place-items-center p-6">
        <div className="max-w-md rounded-2xl border border-line bg-surface p-6 text-center">
          <Logo size="sm" />
          <h1 className="mt-5 text-xl font-black">{access === "checking" ? "جاري التحقق من الصلاحيات…" : "ليس لديك صلاحية أدمن"}</h1>
          {access === "denied" && <p className="mt-2 text-sm text-muted">هذه الصفحة متاحة لحسابات الإدارة فقط.</p>}
          {access === "denied" && <a href="/dashboard" className="mt-5 inline-block rounded-xl bg-corona px-4 py-2 text-sm font-bold text-void">العودة للوحة التحكم</a>}
        </div>
      </div>
    )
  }

  return (
    <>
    <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={paletteItems} />
    <AppShell active="/admin">
      <div className="space-y-5">
        <PageHeader title="مركز تحكم الإدارة" subtitle="تشغيل ومراقبة آمنة · بيانات حقيقية · التداول الحقيقي مقفول" alerts={false}
          status={<>
            <GlobalHealthDot severity={globalSeverity} />
            <Pill tone="profit"><span className="h-2 w-2 rounded-full bg-profit" />آخر تحديث <b className="font-mono tabular">{lastRefreshed ? lastRefreshed.toLocaleTimeString("en-GB") : "—"}</b></Pill>
            <label className="flex cursor-pointer items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-muted">
              <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} className="accent-corona" /> تحديث تلقائي
            </label>
            <button onClick={() => setPaletteOpen(true)} className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-muted hover:border-corona/50">بحث سريع <span className="mx-1 font-mono" dir="ltr">Ctrl+K</span></button>
            <button onClick={() => void load()} disabled={busy} className="rounded-xl bg-corona px-4 py-2 text-sm font-semibold text-void disabled:opacity-50">حدّث دلوقتي</button>
          </>} />
        {error && <div className="mb-4 rounded-xl border border-loss/40 bg-loss/10 p-3 text-sm text-loss">{error}</div>}
        <nav className="rounded-xl border border-line bg-surface p-1" aria-label="أقسام الإدارة">
          <div className="flex gap-1 overflow-x-auto">
            {sections.map(([id, label, Icon]) => (
              <button key={id} onClick={() => selectSection(id)} aria-current={section === id ? "page" : undefined}
                className={`flex items-center gap-2 whitespace-nowrap rounded-[9px] px-3.5 py-2 text-[13px] transition ${section === id ? "bg-surface2 font-semibold text-ink" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
                <Icon size={15} strokeWidth={1.8} className={section === id ? "text-corona" : ""} />{label}
              </button>
            ))}
          </div>
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted">
          <span>{loading ? "جاري تحديث بيانات المركز…" : lastRefreshed ? `آخر مزامنة كاملة: ${lastRefreshed.toLocaleTimeString("ar-EG")}` : "بانتظار أول مزامنة"}</span>
          {currentSectionErrors.length > 0 && <button onClick={() => void load()} className="text-loss hover:text-red-200">إعادة المحاولة</button>}
        </div>
        {currentSectionErrors.length > 0 && <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200">هذا القسم لم يستقبل تحديثًا جديدًا: {currentSectionErrors.join(" · ")}. البيانات السابقة، إن وُجدت، ما زالت معروضة.</div>}

        {section === "overview" && (
          <div className="space-y-4">
            <Panel title="التنبيهات التشغيلية"><AlertCenter alerts={operationalAlerts} /></Panel>
            <div className="grid md:grid-cols-4 gap-3">
            {[
              ["الحالة", o.health?.api || "unavailable"],
              ["بوتات VPS تعمل", `${liveSummaryOverview.running ?? "—"}/${REAL_BOT_IDS.length}`],
              ["مراكز مفتوحة (VPS الحقيقية)", liveSummaryOverview.open_positions ?? "—"],
              ["صافي PnL (VPS الحقيقية)", liveSummaryOverview.total_pnl ?? "—"],
              ["المحفظة الورقية (Dashboard bot)", `${o.paper?.open ?? "—"} مراكز مفتوحة`],
              ["الاستراتيجيات الكلية", o.strategies ?? "—"],
              ["الإدخالات", o.entry_paused?.paused ? "متوقفة" : "مسموحة"],
              ["Kill switch", o.kill_switch?.tripped ? "مفعل" : "غير مفعل"],
            ].map(([k, v]) => <Card key={k} title={k} value={String(v)} />)}
            </div>
          </div>
        )}

        {section === "users" && (
          <div className="space-y-3">
            <Panel title="المستخدمون — هوية Supabase + الباقة + إعدادات البوت المحلية">
              <p className="text-xs text-muted mb-1">
                الهوية (البريد، تاريخ التسجيل، الحظر) من Supabase Auth Admin API، والباقة من جدول profiles، وإعدادات البوت (رأس المال/الاستراتيجية) من قاعدة البيانات المحلية لهذه اللوحة. لا علاقة بهذه القائمة ببوتات VPS السبعة (خدمات مشتركة وليست لكل مستخدم).
              </p>
              {data.users && !data.users.available && (
                <div className="rounded-xl border border-loss/30 bg-loss/10 p-3 text-xs text-red-200 mt-2">
                  تعذر الوصول إلى Supabase الآن{data.users.error ? ` (${data.users.error})` : ""}. لا تُعرض بيانات ملفّقة — أعد المحاولة بعد قليل.
                </div>
              )}
            </Panel>
            <div className="grid sm:grid-cols-4 gap-3">
              {Object.entries((data.users?.plan_counts || {}) as Record<string, number>).map(([tier, count]) => (
                <Card key={tier} title={`باقة ${tier}`} value={String(count)} />
              ))}
              {!Object.keys(data.users?.plan_counts || {}).length && <Card title="إجمالي المستخدمين" value={String(data.users?.total ?? "—")} />}
            </div>
            <Panel title={`قائمة المستخدمين (${data.users?.total ?? 0})`}>
              <UsersTable users={data.users?.users || []} busy={busy}
                onToggleBan={(id, nextBanned) => confirmAction(
                  nextBanned ? "تأكيد حظر هذا المستخدم من تسجيل الدخول؟" : "تأكيد إلغاء حظر هذا المستخدم؟",
                  () => action(`/api/admin/users/${id}/ban`, "POST", { banned: nextBanned, confirm: true }))}
                onUpdateSettings={(id, patch) => confirmAction(
                  "تأكيد تعديل رأس المال/الاستراتيجية المخصصة لهذا المستخدم؟ (إعدادات محلية فقط — لا علاقة ببوتات VPS السبعة)",
                  () => action(`/api/admin/users/${id}/settings`, "PATCH", { ...patch, confirm: true }))} />
            </Panel>
          </div>
        )}

        {section === "finance" && (
          <div className="space-y-3">
            <Panel title="المالية — MRR وإيراد كل باقة">
              <p className="text-xs text-muted mb-1">
                محسوبة فقط من عدد المستخدمين في كل باقة (plan_counts) × سعر الباقة من lib/strategies.ts TIERS —
                لا يوجد اتصال حقيقي بـ Stripe هنا.
              </p>
              {data.finance && !data.finance.available && (
                <div className="rounded-xl border border-loss/30 bg-loss/10 p-3 text-xs text-red-200 mt-2">
                  تعذر الوصول إلى Supabase الآن{data.finance.error ? ` (${data.finance.error})` : ""}. لا تُعرض أرقام ملفّقة.
                </div>
              )}
            </Panel>
            <div className="grid sm:grid-cols-4 gap-3">
              <Card title="MRR (دولار/شهر)" value={String(data.finance?.finance?.mrr_usd ?? "—")} tone="profit" />
              <Card title="مستخدمون مدفوعون" value={String(data.finance?.finance?.paying_users ?? "—")} />
              <Card title="مستخدمون مجانيون" value={String(data.finance?.finance?.free_users ?? "—")} />
              <Card title="إجمالي المستخدمين" value={String(data.finance?.finance?.total_users ?? "—")} />
            </div>
            <Panel title="الإيراد حسب الباقة">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {TIERS.map(t => {
                  const row = data.finance?.finance?.per_tier?.[t.id]
                  return (
                    <div key={t.id} className="rounded-2xl border border-line bg-surface2 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <b className="text-sm">{t.name}</b>
                        <span className="text-[10px] text-muted font-mono" dir="ltr">{t.price}/شهر</span>
                      </div>
                      <div className="mt-2 text-xs text-muted">مستخدمون: <b className="text-ink">{row?.users ?? 0}</b></div>
                      <div className="mt-1 text-xs text-muted">الإيراد: <b className="text-profit font-mono" dir="ltr">${row?.revenue_usd ?? 0}</b></div>
                    </div>
                  )
                })}
              </div>
            </Panel>
          </div>
        )}

        {section === "real" && <LiveStrategies />}

        {section === "live" && (
          <div className="space-y-3">
            <Panel title="بوتات VPS الحية — ٧ خدمات systemd مستقلة + ٢ بدون خدمة">
              <p className="text-xs text-muted mb-1">
                هذه بيانات حقيقية (paper mode) تُقرأ مباشرة من ملفات JSON العامة التي ينشرها كل بوت على{" "}
                <code className="text-[11px]">{liveBotsPortfolio.base_url || "https://bot.da3m.io"}</code>.
              </p>
              <p className="text-xs text-amber-300/90">
                {liveBotsPortfolio.lifecycle_note || "لا يوجد تحكم في تشغيل/إيقاف/إيقاف مؤقت لهذه الخدمات من هذه اللوحة — يتم إدارتها مباشرة على الـ VPS عبر systemctl."}
              </p>
            </Panel>
            <div className="grid md:grid-cols-2 gap-3">
              {ALL_STRATEGY_IDS.map(id => <LiveBotCard key={id} id={id} entry={liveStrategies[id]} />)}
            </div>
          </div>
        )}

        {section === "strategies" && (
          <div className="space-y-4">
            <Panel title="مقارنة سريعة بين كل الاستراتيجيات — بيانات VPS الحقيقية">
              <StrategyComparisonTable strategyIds={ALL_STRATEGY_IDS} liveStrategies={liveStrategies} />
            </Panel>
            <Panel title="تسع استراتيجيات · Paper only · التحكم هنا للبوت الذي تديره هذه اللوحة فقط">
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-muted"><th className="p-2 text-right">الاستراتيجية</th><th>حالة Dashboard</th><th>حالة VPS الحقيقية</th><th>آخر تحديث VPS</th><th>النمط</th><th>إجراء Dashboard</th></tr></thead>
                <tbody>
                  {(data.strategies || []).map((x: Json) => (
                    <tr key={x.id} className="border-t border-line">
                      <td className="p-2 font-bold">{STRATEGY_LABELS_AR[x.id] || x.name}</td>
                      <td>{x.status}</td>
                      <td><StatusBadge status={x.live?.status} /></td>
                      <td className="text-muted">{timeAgo(x.live?.updated)}</td>
                      <td>{x.mode}</td>
                      <td>
                        <button disabled={busy} onClick={() => confirmAction(`تأكيد ${x.status === "enabled" ? "إيقاف" : "تشغيل"} بوت Dashboard لاستراتيجية ${STRATEGY_LABELS_AR[x.id] || x.name}؟`, () => action(`/api/admin/strategies/${x.id}/lifecycle`, "POST", { action: x.status === "enabled" ? "stop" : "start", confirm: true }))} className="px-2 py-1 rounded-lg border border-line">{x.status === "enabled" ? "إيقاف" : "تشغيل"}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-amber-300/90 mt-3">هذا التحكم (تشغيل/إيقاف) يخص فقط بوت Dashboard التجريبي (bot_loop/SQL) — لا يوجد تحكم في بوتات VPS الحقيقية السبعة من هنا؛ راجع تبويب "البوتات الحية".</p>
          </Panel>
          </div>
        )}

        {section === "paper" && (
          <div className="space-y-3">
            <Panel title="Dashboard bot — المحفظة الورقية التي تديرها هذه اللوحة (SQL Trade / bot_loop)">
              <div className="flex gap-2 mb-3">
                <button disabled={busy} onClick={() => action("/api/bot/start", "POST", { paper: true })} className="px-3 py-2 rounded-xl bg-corona text-void text-xs font-bold">تشغيل البوت الورقي</button>
                <button disabled={busy} onClick={() => action("/api/bot/stop", "POST", {})} className="px-3 py-2 rounded-xl border border-line text-xs">إيقاف</button>
              </div>
              <div className="mb-2 text-[11px] text-muted">المراكز المفتوحة ({(dashboardBot.positions || []).length})</div>
              <SortableTable columns={POSITION_COLUMNS} rows={dashboardBot.positions || []} filterKey="symbol" />
              <div className="mb-2 mt-4 text-[11px] text-muted">سجل الصفقات ({(dashboardBot.history || []).length})</div>
              <SortableTable columns={HISTORY_COLUMNS} rows={dashboardBot.history || []} filterKey="symbol" />
            </Panel>
            <Panel title="تنبيه">
              <p className="text-xs text-muted">هذا القسم يخص فقط بوت Dashboard التجريبي، وهو منفصل تمامًا عن بوتات VPS الحقيقية السبعة (systemd) المعروضة في تبويب "البوتات الحية (VPS)".</p>
            </Panel>
          </div>
        )}

        {section === "risk" && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Card title="Kill switch" value={risk.kill_switch?.tripped ? "مفعل" : "غير مفعل"} tone={risk.kill_switch?.tripped ? "loss" : "profit"} />
              <Card title="الإدخالات الجديدة" value={o.entry_paused?.paused ? "متوقفة" : "مسموحة"} tone={o.entry_paused?.paused ? "loss" : "neutral"} />
              <Card title="حالة إدارة المخاطر" value={risk.status || risk.state || "غير متاحة"} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="حدود المخاطر الحالية">
                <KeyValueGrid value={risk.limits || {}} empty="لا توجد حدود متاحة" />
                <div className="mt-4 flex flex-wrap gap-2">
                  <button disabled={busy} onClick={() => confirmAction("تأكيد تغيير Kill switch؟", () => action("/api/admin/risk/kill-switch", "POST", { action: risk.kill_switch?.tripped ? "reset" : "trip", reason: "operator action", confirm: true }))} className="rounded-xl border border-loss/50 bg-loss/10 px-3 py-2 text-xs text-loss disabled:opacity-50">{risk.kill_switch?.tripped ? "إعادة ضبط Kill switch" : "تفعيل Kill switch"}</button>
                  <button disabled={busy} onClick={() => confirmAction("تأكيد تغيير إيقاف الإدخالات؟", () => action("/api/admin/controls/entry-pause", "POST", { paused: !o.entry_paused?.paused, reason: "operator action", confirm: true }))} className="rounded-xl border border-line px-3 py-2 text-xs disabled:opacity-50">{o.entry_paused?.paused ? "استئناف الإدخالات" : "إيقاف الإدخالات"}</button>
                </div>
              </Panel>
              <Panel title="معنى إجراءات الأمان">
                <div className="space-y-3 text-xs text-muted leading-6">
                  <p><b className="text-ink">Kill switch:</b> يمنع المسارات الجديدة ويحتاج تأكيدًا وسجل تدقيق.</p>
                  <p><b className="text-ink">إيقاف الإدخالات:</b> يوقف الصفقات الجديدة ولا يغلق المراكز تلقائيًا.</p>
                  <p><b className="text-ink">بوتات VPS:</b> لا تتأثر بهذه الأزرار؛ ما زالت تُقرأ read-only فقط.</p>
                </div>
              </Panel>
            </div>
          </div>
        )}

        {section === "readiness" && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Card title="Paper" value={data.readiness?.paper_ready ? "جاهز" : "مقفل"} tone={data.readiness?.paper_ready ? "profit" : "loss"} />
              <Card title="Testnet" value={data.readiness?.testnet_ready ? "جاهز" : "مقفل"} tone={data.readiness?.testnet_ready ? "profit" : "loss"} />
              <Card title="Live" value="مقفل افتراضيًا" tone="loss" />
            </div>
            <Panel title="مصفوفة الجاهزية لكل استراتيجية">
              <div className="mb-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200">البيئة الحالية: <b>{data.readiness?.environment || "غير متاحة"}</b> · لا يوجد زر لتفعيل التداول الحقيقي من الواجهة.</div>
              {Object.keys(data.readiness?.strategies || {}).length ? <ReadinessMatrix strategies={data.readiness.strategies} /> : <KeyValueGrid value={data.readiness?.checks || {}} empty="لا توجد أدلة جاهزية متاحة" />}
            </Panel>
          </div>
        )}

        {section === "health" && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="حالة الخدمات">
              <HealthGrid components={data.health?.components || data.health || {}} />
            </Panel>
            <Panel title="حالة التفعيل">
              <KeyValueGrid value={data.activation || {}} empty="لا توجد بيانات تفعيل متاحة" />
            </Panel>
          </div>
        )}

        {section === "recovery" && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Card title="Recovery مطلوب" value={String(Object.keys(recovery.recovery_required || {}).length)} tone={Object.keys(recovery.recovery_required || {}).length ? "loss" : "profit"} />
              <Card title="Reconciliation" value={recovery.reconciliation?.state || "غير متاح"} tone={recovery.reconciliation?.state === "ok" ? "profit" : "loss"} />
              <Card title="Risk reservations" value={String(Object.keys(recovery.risk_reservations || {}).length)} />
            </div>
            <Panel title="حالات تحتاج مراجعة">
              {Object.entries(recovery.recovery_required || {}).map(([symbol, item]: [string, any]) => <div key={symbol} className="rounded-xl border border-loss/30 bg-loss/10 p-3 text-xs text-red-200"><b>{symbol}</b><span className="mx-2">·</span>{item?.reason || "مراجعة مطلوبة"}</div>)}
              {!Object.keys(recovery.recovery_required || {}).length && <div className="rounded-xl border border-profit/20 bg-profit/5 p-4 text-xs text-profit">لا توجد حالات Recovery معلقة.</div>}
            </Panel>
            <Panel title="تفاصيل Reconciliation وRisk reservations"><KeyValueGrid value={{ reconciliation: recovery.reconciliation || {}, risk_reservations: recovery.risk_reservations || {} }} empty="لا توجد بيانات" /></Panel>
          </div>
        )}

        {section === "timeline" && (
          <Panel title="الخط الزمني الموحّد — تدقيق + تنبيهات + Recovery">
            <UnifiedTimeline events={timelineEvents} />
          </Panel>
        )}

        {section === "audit" && (
          <Panel title="سجل التدقيق الإداري">
            <div className="mb-4 rounded-xl border border-line bg-surface2 p-3 text-xs text-muted">كل إجراء حساس يجب أن يظهر هنا مع المنفذ والنتيجة. السجل للقراءة فقط من هذه الصفحة.</div>
            <AuditList items={data.audit?.items || []} />
          </Panel>
        )}

        {section === "settings" && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="الباقات المنشورة">
              <div className="grid gap-2 sm:grid-cols-2">{Object.entries(TIERS).map(([key, tier]: [string, any]) => <div key={key} className="rounded-xl border border-line bg-surface2 p-3"><div className="flex items-center justify-between"><b className="text-sm">{key}</b><span className="font-mono text-corona" dir="ltr">{tier?.price ?? "—"}</span></div><div className="mt-1 text-xs text-muted">{tier?.description || tier?.name || "إعداد منشور"}</div></div>)}</div>
            </Panel>
            <Panel title="التكاملات والأمان">
              <p className="text-xs text-muted leading-6">الأسرار لا تُعرض في الواجهة. حالة المفاتيح تُدار عبر API مصادق، وأي تغيير حساس يُسجل في سجل التدقيق.</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button onClick={() => action("/api/telegram/test", "POST", {})} className="px-3 py-2 rounded-xl bg-[#229ED9] text-white text-xs">اختبار تليجرام</button>
                <button onClick={async () => { try { const r = await fetch(API + "/api/telegram/status", { headers: await authHeaders() }); const j = await r.json(); setError(j.configured ? "تليجرام مربوط" : "تليجرام غير مربوط") } catch (e: any) { setError(e.message) } }} className="px-3 py-2 rounded-xl border border-line text-xs">حالة تليجرام</button>
              </div>
            </Panel>
          </div>
        )}
      </div>
    </AppShell>
    </>
  )
}

function Card({ title, value, tone = "neutral" }: { title: string; value: string; tone?: "profit" | "loss" | "neutral" }) {
  const color = tone === "profit" ? "text-profit" : tone === "loss" ? "text-loss" : "text-ink"
  return <div className="min-w-0 rounded-2xl border border-line bg-surface px-5 py-[18px]"><div className="text-[13px] text-muted">{title}</div><div className={`mt-1.5 font-mono text-[22px] font-bold leading-tight tabular ${color}`}>{value}</div></div>
}
function KeyValueGrid({ value, empty }: { value: Json; empty: string }) {
  const entries = Object.entries(value || {})
  if (!entries.length) return <div className="rounded-xl border border-dashed border-line p-4 text-xs text-muted">{empty}</div>
  return <div className="grid gap-2 sm:grid-cols-2">{entries.map(([key, val]) => <div key={key} className="rounded-xl border border-line bg-surface2 p-3"><div className="text-[10px] text-muted">{key.replaceAll("_", " ")}</div><div className="mt-1 font-mono text-sm font-bold tabular" dir="ltr">{typeof val === "object" ? JSON.stringify(val) : String(val ?? "—")}</div></div>)}</div>
}
function CheckPill({ label, value }: { label: string; value: any }) {
  const ok = value === true
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-bold ${ok ? "border-profit/30 bg-profit/10 text-profit" : "border-loss/30 bg-loss/10 text-loss"}`}><span>{ok ? "✓" : "×"}</span>{label}</span>
}
/** A small always-visible dot in the header summarizing worst-case operational state across the whole center. */
function GlobalHealthDot({ severity }: { severity: "ok" | "warning" | "critical" }) {
  const meta = { ok: ["bg-profit", "سليم"], warning: ["bg-amber-400", "تحذير"], critical: ["bg-loss", "حرج"] }[severity]
  return <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-muted"><span className={`inline-block h-2 w-2 rounded-full ${meta[0]} ${severity !== "ok" ? "animate-pulse" : ""}`} />{meta[1]}</span>
}
type CommandItem = { id: string; label: string; hint?: string; onSelect: () => void }
/** Ctrl/Cmd+K palette: jump to any tab or strategy without hunting through nav. Pure client-side, no network calls. */
function CommandPalette({ open, onClose, items }: { open: boolean; onClose: () => void; items: CommandItem[] }) {
  const [query, setQuery] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { if (open) { setQuery(""); setTimeout(() => inputRef.current?.focus(), 0) } }, [open])
  if (!open) return null
  const visible = items.filter(item => !query || item.label.toLowerCase().includes(query.toLowerCase()) || item.hint?.toLowerCase().includes(query.toLowerCase()))
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-24" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-line bg-surface p-3 shadow-2xl" onClick={e => e.stopPropagation()}>
        <input ref={inputRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="بحث سريع · تبويب أو استراتيجية... (Esc للإغلاق)"
          onKeyDown={e => { if (e.key === "Escape") onClose(); if (e.key === "Enter" && visible[0]) { visible[0].onSelect(); onClose() } }}
          className="w-full rounded-xl border border-line bg-surface2 px-3 py-2 text-sm outline-none focus:border-corona/50" />
        <div className="mt-2 max-h-80 overflow-auto space-y-1">
          {visible.map(item => (
            <button key={item.id} onClick={() => { item.onSelect(); onClose() }} className="w-full flex items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-right text-xs hover:bg-surface2">
              <span className="font-bold">{item.label}</span>{item.hint && <span className="text-muted">{item.hint}</span>}
            </button>
          ))}
          {!visible.length && <div className="p-4 text-center text-xs text-muted">لا توجد نتائج.</div>}
        </div>
      </div>
    </div>
  )
}
/** Side-by-side comparison of every strategy's live PnL/positions/trade count — faster than opening each card. */
function StrategyComparisonTable({ strategyIds, liveStrategies }: { strategyIds: string[]; liveStrategies: Json }) {
  const [sortKey, setSortKey] = useState<"pnl" | "open" | "closed">("pnl")
  const rows = strategyIds.map(id => {
    const e = liveStrategies[id] || {}
    const stats = e.stats || {}
    const pnl = (Number(stats.realized) || 0) + (Number(stats.unrealized) || 0)
    return { id, status: e.status || "unavailable", pnl, open: (e.positions || []).length, closed: stats.closed ?? 0, winRate: stats.closed ? Math.round((Number(stats.wins) || 0) / stats.closed * 100) : null }
  }).sort((a, b) => (b[sortKey] || 0) - (a[sortKey] || 0))
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead><tr className="text-muted"><th className="p-2 text-right">الاستراتيجية</th><th>الحالة</th>
          {(["open", "closed", "pnl"] as const).map(k => <th key={k} onClick={() => setSortKey(k)} className="cursor-pointer select-none">{k === "open" ? "مفتوحة" : k === "closed" ? "مغلقة" : "PnL"}{sortKey === k ? " ▼" : ""}</th>)}
          <th>نسبة الفوز</th></tr></thead>
        <tbody>
          {rows.map(r => <tr key={r.id} className="border-t border-line"><td className="p-2 font-bold">{STRATEGY_LABELS_AR[r.id] || r.id}</td><td><StatusBadge status={r.status} /></td><td>{r.open}</td><td>{r.closed}</td><td className={pnlColor(r.pnl)}>{fmtNum(r.pnl)}</td><td>{r.winRate != null ? `${r.winRate}%` : "—"}</td></tr>)}
        </tbody>
      </table>
    </div>
  )
}
function AlertCenter({ alerts }: { alerts: any[] }) {
  const [filter, setFilter] = useState<"all" | "critical" | "warning">("all")
  const normalized = alerts.filter(Boolean).map(item => typeof item === "string" ? { message: item, severity: "warning" } : item)
  const visible = normalized.filter(item => filter === "all" || (item.severity === filter || (filter === "critical" && item.severity === "error")))
  if (!normalized.length) return <div className="rounded-2xl border border-profit/20 bg-profit/5 p-4 text-xs text-profit">لا توجد تنبيهات تشغيلية حالية.</div>
  return <div className="space-y-3"><div className="flex flex-wrap items-center gap-2"><span className="text-[11px] text-muted">{normalized.length} تنبيه</span>{(["all", "critical", "warning"] as const).map(item => <button key={item} onClick={() => setFilter(item)} className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${filter === item ? "bg-corona text-void" : "border border-line text-muted"}`}>{item === "all" ? "الكل" : item === "critical" ? "حرج" : "تحذير"}</button>)}</div>{visible.slice(0, 8).map((item, i) => <div key={i} className={`rounded-xl border p-3 text-xs ${item.severity === "error" || item.severity === "critical" ? "border-loss/30 bg-loss/10 text-red-200" : "border-amber-400/30 bg-amber-400/10 text-amber-200"}`}><b>{item.title || (item.severity === "error" ? "خطأ تشغيلي" : "تنبيه")}</b><span className="mx-2">·</span>{item.message || item.reason || JSON.stringify(item)}</div>)}{!visible.length && <div className="rounded-xl border border-dashed border-line p-4 text-center text-xs text-muted">لا توجد تنبيهات بهذا التصنيف.</div>}</div>
}
function ReadinessMatrix({ strategies }: { strategies: Json }) {
  const [filter, setFilter] = useState<"all" | "ready" | "blocked">("all")
  const entries = Object.entries(strategies || {})
  const visible = entries.filter(([, item]: [string, any]) => filter === "all" || (filter === "ready" ? item.live_ready === true : item.live_ready !== true))
  return <div className="space-y-3"><div className="flex flex-wrap items-center gap-2"><span className="text-[11px] text-muted">{entries.length} استراتيجية</span>{(["all", "ready", "blocked"] as const).map(item => <button key={item} onClick={() => setFilter(item)} className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${filter === item ? "bg-corona text-void" : "border border-line text-muted"}`}>{item === "all" ? "الكل" : item === "ready" ? "جاهزة" : "مقفلة"}</button>)}</div>{visible.map(([id, item]: [string, any]) => <div key={id} className="rounded-2xl border border-line bg-surface2 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><b>{STRATEGY_LABELS_AR[id] || id}</b><span className={`rounded-full px-2 py-1 text-[10px] font-bold ${item.live_ready ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{item.live_ready ? "Live-ready" : "مقفل"}</span></div><div className="mt-3 flex flex-wrap gap-2"><CheckPill label="Adapter" value={item.adapter_implemented} /><CheckPill label="Recovery" value={item.recovery_tests} /><CheckPill label="Security" value={item.security_approved} /><CheckPill label="Testnet" value={item.testnet_validated} /></div>{Array.isArray(item.reasons) && item.reasons.length > 0 && <div className="mt-3 text-xs text-muted">السبب: {item.reasons.join(" · ")}</div>}</div>)}{!visible.length && <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-muted">لا توجد نتائج بهذا التصنيف.</div>}</div>
}
function AuditList({ items }: { items: Json[] }) {
  const [query, setQuery] = useState("")
  const visible = items.filter(item => !query || JSON.stringify(item).toLowerCase().includes(query.toLowerCase()))
  return <div className="space-y-3"><input value={query} onChange={e => setQuery(e.target.value)} placeholder="ابحث في سجل التدقيق..." className="w-full max-w-sm rounded-xl border border-line bg-surface2 px-3 py-2 text-xs outline-none focus:border-corona/50" />{visible.map((x: Json) => <div key={x.id} className="rounded-xl border border-line bg-surface2 p-3 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><b>{x.action}</b><span className="text-muted font-mono" dir="ltr">{x.at}</span></div><div className="mt-1 text-muted">المنفذ: {x.actor || "—"} · النتيجة: {x.result || "—"}</div></div>)}{!visible.length && <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-muted">لا توجد نتائج.</div>}</div>
}
/** Per-user admin edit form for LOCAL bot allocation (capital + strategy in user_settings).
 *  Explicitly distinct from the 7 shared VPS paper bots: saving here never starts/stops a real bot. */
function UserSettingsEditRow({ user, busy, onSave }: { user: Json; busy: boolean; onSave: (patch: { capital?: number; strategy?: string }) => void }) {
  const [capital, setCapital] = useState(user.capital != null ? String(user.capital) : "")
  const [strategy, setStrategy] = useState(user.strategy || "")
  const strategies = ["trend_daily", "momentum_ls", "listing_short", "ratio_trend"]
  return (
    <tr className="border-t border-line bg-surface2/40">
      <td colSpan={8} className="p-3">
        <div className="rounded-xl border border-dashed border-line p-3 space-y-2">
          <p className="text-[11px] text-amber-300/90">
            هذا تعديل لإعدادات رأس المال/الاستراتيجية المخصصة لهذا المستخدم فقط في قاعدة البيانات المحلية —
            منفصل تمامًا عن بوتات VPS الحقيقية السبعة (خدمات مشتركة)، ولا يشغّل أو يوقف أي بوت حقيقي.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-[11px] text-muted">
              رأس المال
              <input type="number" min={0} value={capital} onChange={e => setCapital(e.target.value)}
                className="mt-1 block w-28 rounded-lg border border-line bg-void px-2 py-1 text-xs" />
            </label>
            <label className="text-[11px] text-muted">
              الاستراتيجية
              <select value={strategy} onChange={e => setStrategy(e.target.value)}
                className="mt-1 block rounded-lg border border-line bg-void px-2 py-1 text-xs">
                <option value="">— بدون تغيير —</option>
                {strategies.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <button disabled={busy || (!capital && !strategy)} onClick={() => {
              const patch: { capital?: number; strategy?: string } = {}
              if (capital !== "") patch.capital = Number(capital)
              if (strategy) patch.strategy = strategy
              onSave(patch)
            }} className="px-3 py-1.5 rounded-lg bg-corona text-void text-xs font-bold disabled:opacity-50">حفظ</button>
          </div>
        </div>
      </td>
    </tr>
  )
}

/** Users & Plans table: identity + tier + local bot settings, with a confirm-gated ban/unban action per row. */
function UsersTable({ users, busy, onToggleBan, onUpdateSettings }: { users: Json[]; busy: boolean; onToggleBan: (id: string, nextBanned: boolean) => void; onUpdateSettings: (id: string, patch: { capital?: number; strategy?: string }) => void }) {
  const [query, setQuery] = useState("")
  const [tierFilter, setTierFilter] = useState<string>("all")
  const [expanded, setExpanded] = useState<string | null>(null)
  const tiers = useMemo(() => Array.from(new Set(users.map(u => u.tier || "free"))), [users])
  const visible = users.filter(u =>
    (tierFilter === "all" || u.tier === tierFilter) &&
    (!query || JSON.stringify(u).toLowerCase().includes(query.toLowerCase())))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="ابحث بالبريد أو المعرف..."
          className="rounded-xl border border-line bg-surface2 px-3 py-2 text-xs outline-none focus:border-corona/50 max-w-[240px]" />
        <button onClick={() => setTierFilter("all")} className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${tierFilter === "all" ? "bg-corona text-void" : "border border-line text-muted"}`}>الكل</button>
        {tiers.map(t => <button key={t} onClick={() => setTierFilter(t)} className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${tierFilter === t ? "bg-corona text-void" : "border border-line text-muted"}`}>{t}</button>)}
      </div>
      <div className="overflow-auto">
        <table className="w-full text-[11px]">
          <thead><tr className="text-muted">
            <th className="p-1.5 text-right">البريد</th><th>الباقة</th><th>تاريخ التسجيل</th><th>آخر دخول</th>
            <th>رأس المال</th><th>استراتيجية البوت</th><th>الحالة</th><th>إجراء</th>
          </tr></thead>
          <tbody>
            {visible.map(u => (
              <Fragment key={u.id}>
                <tr className="border-t border-line">
                  <td className="p-1.5 whitespace-nowrap">{u.email || "—"}</td>
                  <td><span className="rounded-full border border-line px-2 py-0.5 text-[10px]">{u.tier || "free"}</span></td>
                  <td className="text-muted whitespace-nowrap">{timeAgo(u.created_at)}</td>
                  <td className="text-muted whitespace-nowrap">{u.last_sign_in_at ? timeAgo(u.last_sign_in_at) : "—"}</td>
                  <td>{u.capital != null ? fmtNum(u.capital) : "—"}</td>
                  <td>{u.strategy || "—"}</td>
                  <td>{u.banned
                    ? <span className="rounded-full border border-loss/30 bg-loss/10 px-2 py-0.5 text-[10px] font-bold text-loss">محظور</span>
                    : <span className="rounded-full border border-profit/30 bg-profit/10 px-2 py-0.5 text-[10px] font-bold text-profit">نشط</span>}</td>
                  <td className="flex gap-1">
                    <button disabled={busy} onClick={() => onToggleBan(u.id, !u.banned)}
                      className="px-2 py-1 rounded-lg border border-line disabled:opacity-50">{u.banned ? "إلغاء الحظر" : "حظر"}</button>
                    <button disabled={busy} onClick={() => setExpanded(expanded === u.id ? null : u.id)}
                      className="px-2 py-1 rounded-lg border border-line disabled:opacity-50">{expanded === u.id ? "إغلاق" : "تعديل البوت"}</button>
                  </td>
                </tr>
                {expanded === u.id && (
                  <UserSettingsEditRow user={u} busy={busy}
                    onSave={patch => onUpdateSettings(u.id, patch)} />
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {!visible.length && <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-muted">لا توجد نتائج.</div>}
    </div>
  )
}
type TimelineEvent = { at?: string; title: string; detail: string; kind: "audit" | "alert" | "recovery" }
/** Merges audit log + operational alerts + recovery items into one chronological, filterable feed. */
function UnifiedTimeline({ events }: { events: TimelineEvent[] }) {
  const [kind, setKind] = useState<"all" | "audit" | "alert" | "recovery">("all")
  const dated = events.filter(e => e.at).sort((a, b) => (b.at || "").localeCompare(a.at || ""))
  const undated = events.filter(e => !e.at)
  const sorted = [...dated, ...undated]
  const visible = sorted.filter(e => kind === "all" || e.kind === kind)
  const kindMeta: Record<string, [string, string]> = { audit: ["سجل تدقيق", "border-line bg-surface2 text-ink"], alert: ["تنبيه", "border-amber-400/30 bg-amber-400/10 text-amber-200"], recovery: ["Recovery", "border-loss/30 bg-loss/10 text-red-200"] }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><span className="text-[11px] text-muted">{visible.length} حدث</span>
        {(["all", "audit", "alert", "recovery"] as const).map(k => <button key={k} onClick={() => setKind(k)} className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${kind === k ? "bg-corona text-void" : "border border-line text-muted"}`}>{k === "all" ? "الكل" : kindMeta[k][0]}</button>)}
      </div>
      <div className="space-y-2">
        {visible.slice(0, 50).map((e, i) => <div key={i} className={`rounded-xl border p-3 text-xs ${kindMeta[e.kind][1]}`}>
          <div className="flex flex-wrap items-center justify-between gap-2"><b>{e.title}</b>{e.at && <span className="font-mono text-muted" dir="ltr">{e.at}</span>}</div>
          <div className="mt-1 text-muted">{e.detail}</div>
        </div>)}
        {!visible.length && <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-muted">لا توجد أحداث لهذا التصنيف.</div>}
      </div>
    </div>
  )
}
function HealthGrid({ components }: { components: Json }) {
  const entries = Object.entries(components || {})
  if (!entries.length) return <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-muted">لا توجد بيانات صحة متاحة.</div>
  return <div className="grid gap-3 sm:grid-cols-2">{entries.map(([name, value]) => { const healthy = ["healthy", "available", "locked", "ok", "running"].includes(String(value)); return <div key={name} className="rounded-2xl border border-line bg-surface2 p-4"><div className="flex items-center justify-between gap-2"><b className="text-sm">{name.replaceAll("_", " ")}</b><span className={`rounded-full px-2 py-1 text-[10px] font-bold ${healthy ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{String(value)}</span></div><div className="mt-2 text-[11px] text-muted">آخر فحص من endpoint صحة النظام المصادق.</div></div>})}</div>
}
function Panel({ title, children }: { title: string; children: any }) {
  return <section className="min-w-0 rounded-2xl border border-line bg-surface p-5"><h2 className="mb-4 text-[17px] font-bold leading-snug">{title}</h2>{children}</section>
}

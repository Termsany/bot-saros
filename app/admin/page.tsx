"use client"
import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { Activity, BarChart3, Bot, ChevronDown, CircleDollarSign, ClipboardList, Gauge, History, LockKeyhole, Settings2, ShieldAlert, ShieldCheck, Users as UsersIcon, WalletCards } from "lucide-react"
import { Logo } from "@/components/Logo"
import { AppShell } from "@/components/AppShell"
import { CardHeader, Dot, PageHeader, Pill, Toggle, btn, field, label, type Tone } from "@/components/ui"
import { LiveStrategies } from "@/components/LiveStrategies"
import { AdminUserBots } from "@/components/AdminUserBots"
import { AdminOverview } from "@/components/AdminOverview"
import { AdminInvites, PlanPrices } from "@/components/AdminInvites"
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
// the design's main tabs (Figma "04 · الإدارة"); the rest open from "المزيد"
const PRIMARY_TABS = ["overview", "real", "live", "strategies", "risk", "users", "finance", "health", "audit"]
const REAL_BOT_IDS = ["trend_daily", "listing_short", "momentum_ls", "ratio_trend", "vol_breakout", "rsi2_pullback", "trend_breakout"]
const NO_SERVICE_IDS = ["default"]
const ALL_STRATEGY_IDS = [...REAL_BOT_IDS, ...NO_SERVICE_IDS]

const STATUS_META: Record<string, [string, Tone]> = {
  running: ["يعمل", "profit"],
  stale: ["بيانات قديمة", "corona"],
  unavailable: ["غير متاح", "loss"],
  no_service: ["لا توجد خدمة", "neutral"],
}

function StatusBadge({ status }: { status?: string }) {
  const [text, tone] = STATUS_META[status || ""] || ["—", "neutral" as Tone]
  return <Pill tone={tone}><Dot tone={tone} />{text}</Pill>
}

// the admin tables, chips, buttons and notices share these, so every tab reads the same (ui.tsx tokens)
const TH = "whitespace-nowrap px-2 py-2 text-right text-[12px] font-semibold text-faint"
const TD = "px-2 py-3"
const BTN_SM = "inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-line bg-surface2 px-3 py-1.5 text-[13px] font-semibold text-ink transition hover:border-corona/40 disabled:opacity-40"
const BTN_DANGER = "inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-loss/40 bg-loss/10 px-[18px] py-2.5 text-sm font-semibold text-loss transition hover:bg-loss/20 disabled:opacity-40"

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className={`rounded-full border px-3 py-1 text-[12px] font-semibold transition ${active ? "border-corona/40 bg-corona/10 text-corona" : "border-line text-muted hover:text-ink"}`}>{children}</button>
}

function Notice({ tone = "neutral", children, className = "" }: { tone?: "loss" | "corona" | "profit" | "neutral"; children: React.ReactNode; className?: string }) {
  const cls = { loss: "border-loss/30 bg-loss/10 text-loss", corona: "border-corona/30 bg-corona/10 text-corona", profit: "border-profit/30 bg-profit/10 text-profit", neutral: "border-line bg-surface2 text-muted" }[tone]
  return <div className={`rounded-[10px] border px-3.5 py-2.5 text-[13px] leading-6 ${cls} ${className}`}>{children}</div>
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-[10px] border border-dashed border-line p-6 text-center text-[13px] text-faint">{children}</div>
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

function pnlColor(v: number): string { return v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted" }
function fmtNum(v: any, digits = 2): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : "—"
}

/** Cumulative-PnL equity sparkline built from a bot's own trade history — plain inline SVG, no chart library. */
function EquitySparkline({ points }: { points: number[] }) {
  if (!points.length) return <div className="text-[12px] text-faint">لا يوجد سجل صفقات كافٍ لرسم المنحنى</div>
  const w = 600, h = 72, pad = 6
  const min = Math.min(...points, 0), max = Math.max(...points, 0)
  const range = max - min || 1
  const step = points.length > 1 ? (w - pad * 2) / (points.length - 1) : 0
  const path = points.map((v, i) => {
    const x = pad + i * step
    const y = h - pad - ((v - min) / range) * (h - pad * 2)
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(" ")
  const last = points[points.length - 1]
  const color = last >= 0 ? "#22D3A0" : "#FF5470"   // profit / loss tokens
  const zeroY = h - pad - ((0 - min) / range) * (h - pad * 2)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-[72px] w-full overflow-visible" role="img" aria-label="equity curve">
      <line x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} stroke="#232838" strokeDasharray="3,3" vectorEffect="non-scaling-stroke" />
      <path d={path} fill="none" stroke={color} strokeWidth={1.8} vectorEffect="non-scaling-stroke" />
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
      <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="تصفية بالرمز..." className={`${field} mb-3 max-w-[240px] py-2`} />
      <div className="overflow-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr>
              {columns.map(c => (
                <th key={c.key}
                  onClick={() => { if (sortKey === c.key) setSortDir(d => (d * -1) as 1 | -1); else { setSortKey(c.key); setSortDir(-1) } }}
                  className={`${TH} cursor-pointer select-none hover:text-muted`}>
                  {c.label}{sortKey === c.key ? (sortDir === 1 ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {columns.map(c => <td key={c.key} className={`${TD} whitespace-nowrap ${typeof r[c.key] === "number" ? "font-mono tabular" : ""}`}>{c.fmt ? c.fmt(r[c.key], r) : String(r[c.key] ?? "—")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <div className="py-6 text-center text-[13px] text-faint">لا توجد بيانات</div>}
    </div>
  )
}

const SIDE = (v: any) => String(v).toLowerCase() === "short" || String(v).toLowerCase() === "sell" ? <Pill tone="loss">SHORT</Pill> : v ? <Pill tone="profit">LONG</Pill> : "—"
const POSITION_COLUMNS: Column[] = [
  { key: "symbol", label: "الرمز" }, { key: "side", label: "الجهة", fmt: SIDE },
  { key: "entry", label: "الدخول", fmt: v => fmtNum(v) }, { key: "price", label: "السعر", fmt: v => fmtNum(v) },
  { key: "qty", label: "الكمية", fmt: v => fmtNum(v, 4) },
  { key: "pnl", label: "PnL", fmt: v => <span className={pnlColor(Number(v) || 0)}>{fmtNum(v)}</span> },
  { key: "pnl_pct", label: "PnL%", fmt: v => fmtNum(v) }, { key: "sl", label: "SL", fmt: v => fmtNum(v) }, { key: "tp", label: "TP", fmt: v => fmtNum(v) },
]
const HISTORY_COLUMNS: Column[] = [
  { key: "symbol", label: "الرمز" }, { key: "side", label: "الجهة", fmt: SIDE },
  { key: "entry", label: "الدخول", fmt: v => fmtNum(v) }, { key: "exit", label: "الخروج", fmt: v => fmtNum(v) },
  { key: "qty", label: "الكمية", fmt: v => fmtNum(v, 4) },
  { key: "pnl", label: "PnL", fmt: v => <span className={pnlColor(Number(v) || 0)}>{fmtNum(v)}</span> },
]

function Mini({ label, value, tone }: { label: string; value: any; tone?: string }) {
  return <div className="min-w-0 rounded-[10px] bg-surface2 px-3 py-2.5"><div className="truncate text-[11px] text-muted">{label}</div><div className={`mt-0.5 truncate font-mono text-[15px] font-semibold tabular ${tone || ""}`} dir="ltr" style={{ textAlign: "right" }}>{String(value)}</div></div>
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
    <section className={`min-w-0 rounded-2xl border bg-surface p-5 transition ${open ? "border-corona/30 md:col-span-2" : "border-line"}`}>
      <button onClick={() => setOpen(o => !o)} aria-expanded={open} className="flex w-full flex-wrap items-center justify-between gap-3 text-right">
        <div className="flex items-center gap-2.5"><span className="text-[16px] font-bold">{STRATEGY_LABELS_AR[id] || id}</span><StatusBadge status={status} /></div>
        <div className="flex items-center gap-4 text-[12px] text-muted">
          {status !== "no_service" && <>
            <span>مراكز <b className="font-mono text-ink">{positions.length}</b></span>
            <span>PnL <b className={`font-mono tabular ${pnlColor(totalPnl)}`} dir="ltr">{fmtNum(totalPnl)}</b></span>
            <span className="text-faint">{timeAgo(e.updated)}</span>
          </>}
          <ChevronDown size={16} className={`transition ${open ? "rotate-180 text-corona" : ""}`} />
        </div>
      </button>
      {open && (
        <div className="mt-4 space-y-4 border-t border-line pt-4">
          {status === "no_service" ? (
            <Notice>لا توجد خدمة تشغيل حقيقية (systemd) لهذه الاستراتيجية على الـ VPS — لا تتوفر بيانات مباشرة.</Notice>
          ) : status === "unavailable" ? (
            <Notice tone="loss">تعذر الوصول إلى ملف الحالة العام لهذا البوت الآن{e.error ? ` (${e.error})` : ""}. لا تُعرض بيانات ملفّقة.</Notice>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                <Mini label="صفقات مغلقة" value={stats.closed ?? "—"} />
                <Mini label="فوز / خسارة" value={`${stats.wins ?? "—"} / ${stats.losses ?? "—"}`} />
                <Mini label="PnL محقق" value={fmtNum(stats.realized)} tone={pnlColor(Number(stats.realized) || 0)} />
                <Mini label="PnL غير محقق" value={fmtNum(stats.unrealized)} tone={pnlColor(Number(stats.unrealized) || 0)} />
              </div>
              <div className="rounded-[10px] bg-surface2 p-3">
                <div className="mb-1 text-[12px] text-muted">منحنى الأرباح التراكمي (من سجل الصفقات)</div>
                <EquitySparkline points={equity} />
              </div>
              <div>
                <h3 className="mb-2 text-[14px] font-bold">المراكز المفتوحة <span className="font-mono text-faint">({positions.length})</span></h3>
                <SortableTable columns={POSITION_COLUMNS} rows={positions} filterKey="symbol" />
              </div>
              <div>
                <h3 className="mb-2 text-[14px] font-bold">سجل الصفقات <span className="font-mono text-faint">({history.length})</span></h3>
                <SortableTable columns={HISTORY_COLUMNS} rows={history} filterKey="symbol" />
              </div>
            </>
          )}
        </div>
      )}
    </section>
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
  const [moreOpen, setMoreOpen] = useState(false)
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
  const sectionEndpoints: Record<string, string[]> = { overview: ["overview", "recovery", "finance"], users: ["users", "finance"], finance: ["finance"], live: ["paper"], real: [], strategies: ["strategies"], paper: ["paper"], risk: ["risk", "recovery"], readiness: ["readiness"], health: ["health", "recovery", "activation"], recovery: ["recovery"], timeline: ["audit", "recovery"], audit: ["audit"], settings: [] }
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
  const prices: Record<string, number> = data.finance?.prices || Object.fromEntries(TIERS.map(t => [t.id, parseInt(t.price)]))
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
            <span className="flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-muted"><Toggle on={autoRefresh} onChange={setAutoRefresh} label="تحديث تلقائي" /> تحديث تلقائي</span>
            <button onClick={() => setPaletteOpen(true)} className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-muted hover:border-corona/50">بحث سريع <span className="mx-1 font-mono" dir="ltr">Ctrl+K</span></button>
            <button onClick={() => void load()} disabled={busy} className={btn.primary}>حدّث دلوقتي</button>
          </>} />
        {error && <Notice tone="loss">{error}</Notice>}
        <nav className="relative rounded-xl border border-line bg-surface p-1" aria-label="أقسام الإدارة">
          <div className="flex gap-1 overflow-x-auto">
            {PRIMARY_TABS.map(id => sections.find(s => s[0] === id)!).map(([id, label, Icon]) => (
              <button key={id} onClick={() => { selectSection(id); setMoreOpen(false) }} aria-current={section === id ? "page" : undefined}
                className={`flex items-center gap-2 whitespace-nowrap rounded-[9px] px-3.5 py-2 text-[13px] transition ${section === id ? "bg-surface2 font-semibold text-ink" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
                <Icon size={15} strokeWidth={1.8} className={section === id ? "text-corona" : ""} />{label}
              </button>
            ))}
            {(() => { const more = sections.filter(s => !PRIMARY_TABS.includes(s[0])); const cur = more.find(s => s[0] === section); return (
              <button onClick={() => setMoreOpen(v => !v)} aria-expanded={moreOpen}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-[9px] px-3.5 py-2 text-[13px] transition ${cur ? "bg-surface2 font-semibold text-ink" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
                {cur ? cur[1] : "المزيد"} <span aria-hidden>▾</span>
              </button>) })()}
          </div>
          {moreOpen && (
            <div className="absolute left-1 top-full z-20 mt-1 min-w-[220px] rounded-xl border border-line bg-surface2 p-1 shadow-xl">
              {sections.filter(s => !PRIMARY_TABS.includes(s[0])).map(([id, label, Icon]) => (
                <button key={id} onClick={() => { selectSection(id); setMoreOpen(false) }}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-[13px] ${section === id ? "bg-surface font-semibold text-ink" : "text-muted hover:bg-surface hover:text-ink"}`}>
                  <Icon size={15} strokeWidth={1.8} />{label}
                </button>
              ))}
            </div>
          )}
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-faint">
          <span>{loading ? "جاري تحديث بيانات المركز…" : lastRefreshed ? `آخر مزامنة كاملة: ${lastRefreshed.toLocaleTimeString("ar-EG")}` : "بانتظار أول مزامنة"}</span>
          {currentSectionErrors.length > 0 && <button onClick={() => void load()} className="font-semibold text-corona hover:text-corona-soft">إعادة المحاولة</button>}
        </div>
        {currentSectionErrors.length > 0 && <Notice tone="corona">هذا القسم لم يستقبل تحديثًا جديدًا: {currentSectionErrors.join(" · ")}. البيانات السابقة، إن وُجدت، ما زالت معروضة.</Notice>}

        {section === "overview" && (
          <AdminOverview finance={data.finance?.finance} killTripped={!!o.kill_switch?.tripped} operationalAlerts={operationalAlerts} onOpen={selectSection} />
        )}

        {section === "users" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <Card title="إجمالي المستخدمين" value={String(data.users?.total ?? "—")} hint="من Supabase Auth" />
              {Object.entries((data.users?.plan_counts || {}) as Record<string, number>).slice(0, 3).map(([tier, count]) => (
                <Card key={tier} title={`باقة ${tier}`} value={String(count)} hint="من جدول profiles" />
              ))}
            </div>
            <Panel title="المستخدمون" sub="الهوية والحظر من Supabase · الباقة من profiles · راس المال والاستراتيجية من إعدادات البوت المحلية (مش بوتات VPS)">
              {data.users && !data.users.available && (
                <Notice tone="loss" className="mb-4">تعذر الوصول إلى Supabase الآن{data.users.error ? ` (${data.users.error})` : ""}. لا تُعرض بيانات ملفّقة — أعد المحاولة بعد قليل.</Notice>
              )}
              <UsersTable users={data.users?.users || []} busy={busy}
                onToggleBan={(id, nextBanned) => confirmAction(
                  nextBanned ? "تأكيد حظر هذا المستخدم من تسجيل الدخول؟" : "تأكيد إلغاء حظر هذا المستخدم؟",
                  () => action(`/api/admin/users/${id}/ban`, "POST", { banned: nextBanned, confirm: true }))}
                onUpdateSettings={(id, patch) => confirmAction(
                  "تأكيد تعديل رأس المال/الاستراتيجية المخصصة لهذا المستخدم؟ (إعدادات محلية فقط — لا علاقة ببوتات VPS السبعة)",
                  () => action(`/api/admin/users/${id}/settings`, "PATCH", { ...patch, confirm: true }))} />
            </Panel>
            <AdminInvites prices={prices} />
          </div>
        )}

        {section === "finance" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <Card title="الإيراد الشهري (MRR)" value={data.finance?.finance?.mrr_usd != null ? `$${data.finance.finance.mrr_usd}` : "—"} tone="profit" hint="دولار / شهر" />
              <Card title="مستخدمون مدفوعون" value={String(data.finance?.finance?.paying_users ?? "—")} hint="باقة مدفوعة" />
              <Card title="مستخدمون مجانيون" value={String(data.finance?.finance?.free_users ?? "—")} hint="الباقة المجانية" />
              <Card title="إجمالي المستخدمين" value={String(data.finance?.finance?.total_users ?? "—")} hint="كل الحسابات" />
            </div>
            {data.finance && !data.finance.available && (
              <Notice tone="loss">تعذر الوصول إلى Supabase الآن{data.finance.error ? ` (${data.finance.error})` : ""}. لا تُعرض أرقام ملفّقة.</Notice>
            )}
            <PlanPrices onSaved={() => void load()} />
            <Panel title="الإيراد حسب الباقة" sub="المشتركين في كل باقة × سعرها الحالي — تقدير، مش أرقام Stripe الفعلية (الهدايا مش محسوبة)">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[480px] text-[13px]">
                  <thead><tr>{["الباقة", "السعر", "المستخدمون", "الإيراد الشهري"].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
                  <tbody>
                    {TIERS.map(t => {
                      const row = data.finance?.finance?.per_tier?.[t.id]
                      return (
                        <tr key={t.id} className="border-t border-line">
                          <td className={`${TD} text-[14px] font-semibold`}>{t.name}</td>
                          <td className={`${TD} font-mono tabular text-muted`} dir="ltr" style={{ textAlign: "right" }}>${prices[t.id] ?? parseInt(t.price)}/mo</td>
                          <td className={`${TD} font-mono tabular`}>{row?.users ?? 0}</td>
                          <td className={`${TD} font-mono font-semibold tabular text-profit`} dir="ltr" style={{ textAlign: "right" }}>${row?.revenue_usd ?? 0}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        )}

        {section === "real" && <><LiveStrategies /><div className="mt-5"><AdminUserBots /></div></>}

        {section === "live" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <Card title="بوتات VPS شغالة" value={`${ALL_STRATEGY_IDS.filter(id => liveStrategies[id]?.status === "running").length} / ${REAL_BOT_IDS.length}`} hint="خدمات systemd" />
              <Card title="صفقات مفتوحة" value={String(ALL_STRATEGY_IDS.reduce((a, id) => a + (liveStrategies[id]?.positions?.length || 0), 0))} hint="كل البوتات" />
              <Card title="صفقات مغلقة" value={String(ALL_STRATEGY_IDS.reduce((a, id) => a + (Number(liveStrategies[id]?.stats?.closed) || 0), 0))} hint="من سجل كل بوت" />
              {(() => { const pnl = ALL_STRATEGY_IDS.reduce((a, id) => a + (Number(liveStrategies[id]?.stats?.realized) || 0) + (Number(liveStrategies[id]?.stats?.unrealized) || 0), 0); return <Card title="صافي PnL" value={fmtNum(pnl)} tone={pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral"} hint="محقق + غير محقق" /> })()}
            </div>
            <Notice>
              بيانات paper حقيقية من ملفات JSON العامة اللي بينشرها كل بوت على <code className="font-mono text-ink" dir="ltr">{liveBotsPortfolio.base_url || "https://bot.da3m.io"}</code>.{" "}
              <span className="text-corona">{liveBotsPortfolio.lifecycle_note || "التشغيل والإيقاف من الـ VPS مباشرة (systemctl) — مش من اللوحة دي."}</span>
            </Notice>
            <div className="grid gap-4 md:grid-cols-2">
              {ALL_STRATEGY_IDS.map(id => <LiveBotCard key={id} id={id} entry={liveStrategies[id]} />)}
            </div>
          </div>
        )}

        {section === "strategies" && (
          <div className="space-y-5">
            <Panel title="مقارنة الاستراتيجيات" sub="بيانات بوتات VPS الحقيقية · اضغط على عنوان العمود للترتيب">
              <StrategyComparisonTable strategyIds={ALL_STRATEGY_IDS} liveStrategies={liveStrategies} />
            </Panel>
            <Panel title="بوت Dashboard" sub="Paper only · التشغيل والإيقاف هنا للبوت اللي اللوحة دي بتديره بس">
              <div className="overflow-auto">
                <table className="w-full min-w-[640px] text-[13px]">
                  <thead><tr>{["الاستراتيجية", "حالة Dashboard", "حالة VPS", "آخر تحديث VPS", "النمط", ""].map((h, i) => <th key={i} className={TH}>{h}</th>)}</tr></thead>
                  <tbody>
                    {(data.strategies || []).map((x: Json) => (
                      <tr key={x.id} className="border-t border-line">
                        <td className={`${TD} text-[14px] font-semibold`}>{STRATEGY_LABELS_AR[x.id] || x.name}</td>
                        <td className={TD}><Pill tone={x.status === "enabled" ? "profit" : "neutral"}>{x.status === "enabled" ? "شغال" : x.status || "—"}</Pill></td>
                        <td className={TD}><StatusBadge status={x.live?.status} /></td>
                        <td className={`${TD} text-muted`}>{timeAgo(x.live?.updated)}</td>
                        <td className={`${TD} font-mono text-[12px] text-muted`}>{x.mode}</td>
                        <td className={`${TD} text-left`}>
                          <button disabled={busy} onClick={() => confirmAction(`تأكيد ${x.status === "enabled" ? "إيقاف" : "تشغيل"} بوت Dashboard لاستراتيجية ${STRATEGY_LABELS_AR[x.id] || x.name}؟`, () => action(`/api/admin/strategies/${x.id}/lifecycle`, "POST", { action: x.status === "enabled" ? "stop" : "start", confirm: true }))} className={BTN_SM}>{x.status === "enabled" ? "إيقاف" : "تشغيل"}</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!(data.strategies || []).length && <Empty>لا توجد استراتيجيات متاحة.</Empty>}
              <Notice tone="corona" className="mt-4">التحكم ده يخص بوت Dashboard التجريبي (bot_loop/SQL) بس — بوتات VPS السبعة مش بتتشغل أو تتوقف من هنا؛ شوف تبويب "البوتات الحية".</Notice>
            </Panel>
          </div>
        )}

        {section === "paper" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <Card title="مراكز مفتوحة" value={String((dashboardBot.positions || []).length)} hint="المحفظة الورقية" />
              <Card title="صفقات مغلقة" value={String((dashboardBot.history || []).length)} hint="سجل الصفقات" />
              {(() => { const pnl = (dashboardBot.history || []).reduce((a: number, h: Json) => a + (Number(h.pnl) || 0), 0); return <Card title="PnL محقق" value={fmtNum(pnl)} tone={pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral"} hint="من سجل الصفقات" /> })()}
              {(() => { const pnl = (dashboardBot.positions || []).reduce((a: number, h: Json) => a + (Number(h.pnl) || 0), 0); return <Card title="PnL غير محقق" value={fmtNum(pnl)} tone={pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral"} hint="المراكز المفتوحة" /> })()}
            </div>
            <Panel title="المحفظة الورقية — بوت Dashboard" sub="SQL Trade / bot_loop · منفصلة تمامًا عن بوتات VPS السبعة"
              action={<>
                <button disabled={busy} onClick={() => action("/api/bot/start", "POST", { paper: true })} className={btn.primary}>تشغيل البوت الورقي</button>
                <button disabled={busy} onClick={() => action("/api/bot/stop", "POST", {})} className={btn.secondary}>إيقاف</button>
              </>}>
              <h3 className="mb-2 text-[14px] font-bold">المراكز المفتوحة <span className="font-mono text-faint">({(dashboardBot.positions || []).length})</span></h3>
              <SortableTable columns={POSITION_COLUMNS} rows={dashboardBot.positions || []} filterKey="symbol" />
              <h3 className="mb-2 mt-6 text-[14px] font-bold">سجل الصفقات <span className="font-mono text-faint">({(dashboardBot.history || []).length})</span></h3>
              <SortableTable columns={HISTORY_COLUMNS} rows={dashboardBot.history || []} filterKey="symbol" />
            </Panel>
          </div>
        )}

        {section === "risk" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-3">
              <Card title="قفل الطوارئ (Kill switch)" value={risk.kill_switch?.tripped ? "شغال" : "مش شغال"} tone={risk.kill_switch?.tripped ? "loss" : "profit"} hint="بيمنع أي دخول جديد" />
              <Card title="الدخول الجديد" value={o.entry_paused?.paused ? "متوقف" : "مسموح"} tone={o.entry_paused?.paused ? "loss" : "profit"} hint="المراكز المفتوحة مش بتتقفل" />
              <Card title="إدارة المخاطر" value={risk.status || risk.state || "غير متاحة"} hint="آخر حالة من الـ API" />
            </div>
            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_372px]">
              <Panel title="حدود المخاطر الحالية" sub="كل تغيير محتاج تأكيد وبيتسجل في سجل التدقيق"
                action={<>
                  <button disabled={busy} onClick={() => confirmAction("تأكيد تغيير إيقاف الإدخالات؟", () => action("/api/admin/controls/entry-pause", "POST", { paused: !o.entry_paused?.paused, reason: "operator action", confirm: true }))} className={btn.secondary}>{o.entry_paused?.paused ? "استئناف الدخول" : "إيقاف الدخول"}</button>
                  <button disabled={busy} onClick={() => confirmAction("تأكيد تغيير Kill switch؟", () => action("/api/admin/risk/kill-switch", "POST", { action: risk.kill_switch?.tripped ? "reset" : "trip", reason: "operator action", confirm: true }))} className={BTN_DANGER}>{risk.kill_switch?.tripped ? "إعادة ضبط قفل الطوارئ" : "تفعيل قفل الطوارئ"}</button>
                </>}>
                <KeyValueGrid value={risk.limits || {}} empty="لا توجد حدود متاحة" />
              </Panel>
              <Panel title="معنى إجراءات الأمان">
                <div className="divide-y divide-line text-[13px] leading-6">
                  <p className="pb-3"><b className="text-ink">قفل الطوارئ:</b> <span className="text-muted">بيمنع المسارات الجديدة ومحتاج تأكيد وسجل تدقيق.</span></p>
                  <p className="py-3"><b className="text-ink">إيقاف الدخول:</b> <span className="text-muted">بيوقف الصفقات الجديدة ومش بيقفل المراكز لوحده.</span></p>
                  <p className="pt-3"><b className="text-ink">بوتات VPS:</b> <span className="text-muted">مش بتتأثر بالأزرار دي؛ بتتقري read-only بس.</span></p>
                </div>
              </Panel>
            </div>
          </div>
        )}

        {section === "readiness" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-3">
              <Card title="Paper" value={data.readiness?.paper_ready ? "جاهز" : "مقفل"} tone={data.readiness?.paper_ready ? "profit" : "loss"} hint="تداول ورقي" />
              <Card title="Testnet" value={data.readiness?.testnet_ready ? "جاهز" : "مقفل"} tone={data.readiness?.testnet_ready ? "profit" : "loss"} hint="Binance testnet" />
              <Card title="Live" value="مقفل افتراضيًا" tone="loss" hint="مفيش زر تفعيل من الواجهة" />
            </div>
            <Panel title="مصفوفة الجاهزية لكل استراتيجية" sub={`البيئة الحالية: ${data.readiness?.environment || "غير متاحة"}`}>
              {Object.keys(data.readiness?.strategies || {}).length ? <ReadinessMatrix strategies={data.readiness.strategies} /> : <KeyValueGrid value={data.readiness?.checks || {}} empty="لا توجد أدلة جاهزية متاحة" />}
            </Panel>
          </div>
        )}

        {section === "health" && (
          <div className="grid items-start gap-5 xl:grid-cols-2">
            <Panel title="حالة الخدمات" sub="آخر فحص من endpoint صحة النظام المصادق">
              <HealthGrid components={data.health?.components || data.health || {}} />
            </Panel>
            <Panel title="حالة التفعيل">
              <KeyValueGrid value={data.activation || {}} empty="لا توجد بيانات تفعيل متاحة" />
            </Panel>
          </div>
        )}

        {section === "recovery" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-3">
              <Card title="Recovery مطلوب" value={String(Object.keys(recovery.recovery_required || {}).length)} tone={Object.keys(recovery.recovery_required || {}).length ? "loss" : "profit"} hint="حالات معلقة" />
              <Card title="Reconciliation" value={recovery.reconciliation?.state || "غير متاح"} tone={recovery.reconciliation?.state === "ok" ? "profit" : "loss"} hint="مطابقة الحساب" />
              <Card title="Risk reservations" value={String(Object.keys(recovery.risk_reservations || {}).length)} hint="حجوزات مخاطرة" />
            </div>
            <Panel title="حالات محتاجة مراجعة">
              {Object.keys(recovery.recovery_required || {}).length ? (
                <div className="divide-y divide-line">
                  {Object.entries(recovery.recovery_required || {}).map(([symbol, item]: [string, any]) => (
                    <div key={symbol} className="flex items-start gap-2 py-2.5 text-[13px]"><span className="mt-1.5"><Dot tone="loss" /></span><b className="font-mono" dir="ltr">{symbol}</b><span className="text-muted">{item?.reason || "مراجعة مطلوبة"}</span></div>
                  ))}
                </div>
              ) : <Notice tone="profit">لا توجد حالات Recovery معلقة.</Notice>}
            </Panel>
            <Panel title="تفاصيل Reconciliation وRisk reservations"><KeyValueGrid value={{ reconciliation: recovery.reconciliation || {}, risk_reservations: recovery.risk_reservations || {} }} empty="لا توجد بيانات" /></Panel>
          </div>
        )}

        {section === "timeline" && (
          <Panel title="الخط الزمني الموحّد" sub="سجل التدقيق + التنبيهات + Recovery في مكان واحد">
            <UnifiedTimeline events={timelineEvents} />
          </Panel>
        )}

        {section === "audit" && (
          <Panel title="سجل التدقيق الإداري" sub="كل إجراء حساس بيظهر هنا مع المنفذ والنتيجة · للقراءة بس">
            <AuditList items={data.audit?.items || []} />
          </Panel>
        )}

        {section === "settings" && (
          <div className="grid items-start gap-5 xl:grid-cols-2">
            <Panel title="الباقات المنشورة">
              <div className="grid gap-3 sm:grid-cols-2">{Object.entries(TIERS).map(([key, tier]: [string, any]) => <div key={key} className="rounded-[12px] bg-surface2 p-4"><div className="flex items-center justify-between gap-2"><b className="text-[14px]">{tier?.name || key}</b><span className="font-mono text-[13px] text-corona" dir="ltr">${prices[tier?.id] ?? "—"}/mo</span></div><div className="mt-1 text-[12px] text-muted">{(tier?.features || []).join(" · ") || "إعداد منشور"}</div></div>)}</div>
            </Panel>
            <Panel title="التكاملات والأمان" sub="الأسرار مش بتظهر في الواجهة · أي تغيير حساس بيتسجل في سجل التدقيق">
              <div className="flex flex-wrap gap-2">
                <button onClick={() => action("/api/telegram/test", "POST", {})} className={btn.primary}>ابعت رسالة تجربة على تليجرام</button>
                <button onClick={async () => { try { const r = await fetch(API + "/api/telegram/status", { headers: await authHeaders() }); const j = await r.json(); setError(j.configured ? "تليجرام مربوط" : "تليجرام غير مربوط") } catch (e: any) { setError(e.message) } }} className={btn.secondary}>حالة تليجرام</button>
              </div>
            </Panel>
          </div>
        )}
      </div>
    </AppShell>
    </>
  )
}

function Card({ title, value, tone = "neutral", hint }: { title: string; value: string; tone?: "profit" | "loss" | "neutral"; hint?: string }) {
  const color = tone === "profit" ? "text-profit" : tone === "loss" ? "text-loss" : "text-ink"
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface px-5 py-[18px]">
      <div className="truncate text-[13px] text-muted">{title}</div>
      <div className={`mt-1.5 truncate font-mono text-[22px] font-bold leading-tight tabular ${color}`} dir="ltr" style={{ textAlign: "right" }}>{value}</div>
      {hint && <div className="mt-1.5 truncate text-[12px] text-faint">{hint}</div>}
    </div>
  )
}
function KeyValueGrid({ value, empty }: { value: Json; empty: string }) {
  const entries = Object.entries(value || {})
  if (!entries.length) return <Empty>{empty}</Empty>
  return <div className="grid gap-2 sm:grid-cols-2">{entries.map(([key, val]) => <div key={key} className="min-w-0 rounded-[10px] bg-surface2 px-3 py-2.5"><div className="truncate text-[11px] text-muted">{key.replaceAll("_", " ")}</div><div className="mt-0.5 break-all font-mono text-[13px] font-semibold tabular" dir="ltr" style={{ textAlign: "right" }}>{typeof val === "object" ? JSON.stringify(val) : String(val ?? "—")}</div></div>)}</div>
}
function CheckPill({ label, value }: { label: string; value: any }) {
  const ok = value === true
  return <Pill tone={ok ? "profit" : "loss"}>{ok ? "✓" : "×"} {label}</Pill>
}
/** A small always-visible dot in the header summarizing worst-case operational state across the whole center. */
function GlobalHealthDot({ severity }: { severity: "ok" | "warning" | "critical" }) {
  const [tone, text] = ({ ok: ["profit", "سليم"], warning: ["corona", "تحذير"], critical: ["loss", "حرج"] } as const)[severity]
  return <Pill tone={tone}><Dot tone={tone} pulse={severity !== "ok"} />{text}</Pill>
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
    <div dir="rtl" className="fixed inset-0 z-50 flex items-start justify-center bg-void/80 p-4 pt-24 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-line bg-surface p-3 shadow-2xl" onClick={e => e.stopPropagation()}>
        <input ref={inputRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="بحث سريع · تبويب أو استراتيجية... (Esc للإغلاق)"
          onKeyDown={e => { if (e.key === "Escape") onClose(); if (e.key === "Enter" && visible[0]) { visible[0].onSelect(); onClose() } }}
          className={field} />
        <div className="mt-2 max-h-80 space-y-0.5 overflow-auto">
          {visible.map(item => (
            <button key={item.id} onClick={() => { item.onSelect(); onClose() }} className="flex w-full items-center justify-between gap-2 rounded-[10px] px-3 py-2.5 text-right text-[13px] hover:bg-surface2">
              <span className="font-semibold">{item.label}</span>{item.hint && <span className="text-[12px] text-faint">{item.hint}</span>}
            </button>
          ))}
          {!visible.length && <div className="p-4 text-center text-[13px] text-faint">لا توجد نتائج.</div>}
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
      <table className="w-full min-w-[600px] text-[13px]">
        <thead><tr><th className={TH}>الاستراتيجية</th><th className={TH}>الحالة</th>
          {(["open", "closed", "pnl"] as const).map(k => <th key={k} onClick={() => setSortKey(k)} className={`${TH} cursor-pointer select-none hover:text-muted ${sortKey === k ? "text-corona" : ""}`}>{k === "open" ? "مفتوحة" : k === "closed" ? "مغلقة" : "PnL"}{sortKey === k ? " ▼" : ""}</th>)}
          <th className={TH}>نسبة الفوز</th></tr></thead>
        <tbody>
          {rows.map(r => <tr key={r.id} className="border-t border-line">
            <td className={`${TD} text-[14px] font-semibold`}>{STRATEGY_LABELS_AR[r.id] || r.id}</td>
            <td className={TD}><StatusBadge status={r.status} /></td>
            <td className={`${TD} font-mono tabular`}>{r.open}</td>
            <td className={`${TD} font-mono tabular`}>{r.closed}</td>
            <td className={`${TD} font-mono font-semibold tabular ${pnlColor(r.pnl)}`} dir="ltr" style={{ textAlign: "right" }}>{fmtNum(r.pnl)}</td>
            <td className={TD}>{r.winRate != null ? <div className="flex items-center gap-2"><div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface2"><div className={`h-full rounded-full ${r.winRate >= 50 ? "bg-profit" : "bg-loss"}`} style={{ width: `${r.winRate}%` }} /></div><span className="font-mono tabular">{r.winRate}%</span></div> : <span className="text-faint">—</span>}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
  )
}
function AlertCenter({ alerts }: { alerts: any[] }) {
  const [filter, setFilter] = useState<"all" | "critical" | "warning">("all")
  const normalized = alerts.filter(Boolean).map(item => typeof item === "string" ? { message: item, severity: "warning" } : item)
  const visible = normalized.filter(item => filter === "all" || (item.severity === filter || (filter === "critical" && item.severity === "error")))
  if (!normalized.length) return <Notice tone="profit">لا توجد تنبيهات تشغيلية حالية.</Notice>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><span className="text-[12px] text-faint">{normalized.length} تنبيه</span>{(["all", "critical", "warning"] as const).map(item => <Chip key={item} active={filter === item} onClick={() => setFilter(item)}>{item === "all" ? "الكل" : item === "critical" ? "حرج" : "تحذير"}</Chip>)}</div>
      <div className="divide-y divide-line">
        {visible.slice(0, 8).map((item, i) => { const bad = item.severity === "error" || item.severity === "critical"; return (
          <div key={i} className="flex items-start gap-2 py-2.5 text-[13px]"><span className="mt-1.5"><Dot tone={bad ? "loss" : "corona"} /></span><span><b>{item.title || (item.severity === "error" ? "خطأ تشغيلي" : "تنبيه")}</b> <span className="text-muted">· {item.message || item.reason || JSON.stringify(item)}</span></span></div>
        ) })}
      </div>
      {!visible.length && <Empty>لا توجد تنبيهات بهذا التصنيف.</Empty>}
    </div>
  )
}
function ReadinessMatrix({ strategies }: { strategies: Json }) {
  const [filter, setFilter] = useState<"all" | "ready" | "blocked">("all")
  const entries = Object.entries(strategies || {})
  const visible = entries.filter(([, item]: [string, any]) => filter === "all" || (filter === "ready" ? item.live_ready === true : item.live_ready !== true))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><span className="text-[12px] text-faint">{entries.length} استراتيجية</span>{(["all", "ready", "blocked"] as const).map(item => <Chip key={item} active={filter === item} onClick={() => setFilter(item)}>{item === "all" ? "الكل" : item === "ready" ? "جاهزة" : "مقفلة"}</Chip>)}</div>
      <div className="grid gap-3 lg:grid-cols-2">
        {visible.map(([id, item]: [string, any]) => (
          <div key={id} className="rounded-[12px] bg-surface2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><b className="text-[14px]">{STRATEGY_LABELS_AR[id] || id}</b><Pill tone={item.live_ready ? "profit" : "loss"}>{item.live_ready ? "جاهزة للحقيقي" : "مقفلة"}</Pill></div>
            <div className="mt-3 flex flex-wrap gap-1.5"><CheckPill label="Adapter" value={item.adapter_implemented} /><CheckPill label="Recovery" value={item.recovery_tests} /><CheckPill label="Security" value={item.security_approved} /><CheckPill label="Testnet" value={item.testnet_validated} /></div>
            {Array.isArray(item.reasons) && item.reasons.length > 0 && <div className="mt-3 text-[12px] text-muted">السبب: {item.reasons.join(" · ")}</div>}
          </div>
        ))}
      </div>
      {!visible.length && <Empty>لا توجد نتائج بهذا التصنيف.</Empty>}
    </div>
  )
}
function AuditList({ items }: { items: Json[] }) {
  const [query, setQuery] = useState("")
  const visible = items.filter(item => !query || JSON.stringify(item).toLowerCase().includes(query.toLowerCase()))
  return (
    <div className="space-y-3">
      <input value={query} onChange={e => setQuery(e.target.value)} placeholder="ابحث في سجل التدقيق..." className={`${field} max-w-sm`} />
      {visible.length > 0 && <div className="overflow-auto">
        <table className="w-full min-w-[560px] text-[13px]">
          <thead><tr>{["الإجراء", "المنفذ", "النتيجة", "الوقت"].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
          <tbody>{visible.map((x: Json, i) => { const ok = /ok|success|done|نجح/i.test(String(x.result || "")); return (
            <tr key={x.id ?? i} className="border-t border-line">
              <td className={`${TD} font-semibold`}>{x.action}</td>
              <td className={`${TD} text-muted`}>{x.actor || "—"}</td>
              <td className={TD}>{x.result ? <Pill tone={ok ? "profit" : "neutral"}>{x.result}</Pill> : "—"}</td>
              <td className={`${TD} whitespace-nowrap font-mono text-[12px] text-faint`} dir="ltr" style={{ textAlign: "right" }}>{x.at}</td>
            </tr>
          ) })}</tbody>
        </table>
      </div>}
      {!visible.length && <Empty>لا توجد نتائج.</Empty>}
    </div>
  )
}
/** Per-user admin edit form for LOCAL bot allocation (capital + strategy in user_settings).
 *  Explicitly distinct from the 7 shared VPS paper bots: saving here never starts/stops a real bot. */
function UserSettingsEditRow({ user, busy, onSave }: { user: Json; busy: boolean; onSave: (patch: { capital?: number; strategy?: string }) => void }) {
  const [capital, setCapital] = useState(user.capital != null ? String(user.capital) : "")
  const [strategy, setStrategy] = useState(user.strategy || "")
  const strategies = ["trend_daily", "momentum_ls", "listing_short", "ratio_trend"]
  return (
    <tr className="border-t border-line">
      <td colSpan={8} className="px-2 py-3">
        <div className="space-y-3 rounded-[12px] bg-surface2 p-4">
          <p className="text-[12px] text-corona">
            ده تعديل لإعدادات راس المال/الاستراتيجية المخصصة للمستخدم ده بس في قاعدة البيانات المحلية —
            منفصل تمامًا عن بوتات VPS السبعة، ومش بيشغّل أو يوقف أي بوت حقيقي.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="w-36"><span className={label}>راس المال</span>
              <input type="number" min={0} value={capital} onChange={e => setCapital(e.target.value)} dir="ltr" className={`${field} py-2 font-mono`} />
            </label>
            <label className="w-48"><span className={label}>الاستراتيجية</span>
              <select value={strategy} onChange={e => setStrategy(e.target.value)} className={`${field} py-2`}>
                <option value="">— بدون تغيير —</option>
                {strategies.map(s => <option key={s} value={s}>{STRATEGY_LABELS_AR[s] || s}</option>)}
              </select>
            </label>
            <button disabled={busy || (!capital && !strategy)} onClick={() => {
              const patch: { capital?: number; strategy?: string } = {}
              if (capital !== "") patch.capital = Number(capital)
              if (strategy) patch.strategy = strategy
              onSave(patch)
            }} className={`${btn.primary} py-2`}>حفظ</button>
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
    (tierFilter === "all" || (u.tier || "free") === tierFilter) &&
    (!query || JSON.stringify(u).toLowerCase().includes(query.toLowerCase())))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="ابحث بالبريد أو المعرف..." className={`${field} max-w-[260px] py-2`} />
        <Chip active={tierFilter === "all"} onClick={() => setTierFilter("all")}>الكل</Chip>
        {tiers.map(t => <Chip key={t} active={tierFilter === t} onClick={() => setTierFilter(t)}>{t}</Chip>)}
      </div>
      <div className="overflow-auto">
        <table className="w-full min-w-[860px] text-[13px]">
          <thead><tr>{["البريد", "الباقة", "التسجيل", "آخر دخول", "راس المال", "استراتيجية البوت", "الحالة", ""].map((h, i) => <th key={i} className={TH}>{h}</th>)}</tr></thead>
          <tbody>
            {visible.map(u => (
              <Fragment key={u.id}>
                <tr className="border-t border-line">
                  <td className={`${TD} whitespace-nowrap font-semibold`} dir="ltr" style={{ textAlign: "right" }}>{u.email || "—"}</td>
                  <td className={TD}><div className="flex flex-wrap items-center gap-1"><Pill tone={(u.tier || "free") === "free" ? "neutral" : "corona"}>{u.tier || "free"}</Pill>{u.gift_tier && <Pill tone="signal" className="text-[11px]">هدية {u.gift_tier} · لحد {new Date(u.gift_expires_at).toLocaleDateString("ar-EG", { day: "numeric", month: "short" })}</Pill>}</div></td>
                  <td className={`${TD} whitespace-nowrap text-muted`}>{timeAgo(u.created_at)}</td>
                  <td className={`${TD} whitespace-nowrap text-muted`}>{u.last_sign_in_at ? timeAgo(u.last_sign_in_at) : "—"}</td>
                  <td className={`${TD} font-mono tabular`}>{u.capital != null ? fmtNum(u.capital) : "—"}</td>
                  <td className={`${TD} text-muted`}>{u.strategy ? STRATEGY_LABELS_AR[u.strategy] || u.strategy : "—"}</td>
                  <td className={TD}>{u.banned ? <Pill tone="loss">محظور</Pill> : <Pill tone="profit">نشط</Pill>}</td>
                  <td className={TD}>
                    <div className="flex justify-end gap-1.5">
                      <button disabled={busy} onClick={() => setExpanded(expanded === u.id ? null : u.id)} className={BTN_SM}>{expanded === u.id ? "إغلاق" : "تعديل البوت"}</button>
                      <button disabled={busy} onClick={() => onToggleBan(u.id, !u.banned)} className={u.banned ? BTN_SM : `${BTN_SM} text-loss hover:border-loss/40`}>{u.banned ? "إلغاء الحظر" : "حظر"}</button>
                    </div>
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
      {!visible.length && <Empty>لا توجد نتائج.</Empty>}
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
  const kindMeta: Record<string, [string, Tone]> = { audit: ["سجل تدقيق", "signal"], alert: ["تنبيه", "corona"], recovery: ["Recovery", "loss"] }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2"><span className="text-[12px] text-faint">{visible.length} حدث</span>
        {(["all", "audit", "alert", "recovery"] as const).map(k => <Chip key={k} active={kind === k} onClick={() => setKind(k)}>{k === "all" ? "الكل" : kindMeta[k][0]}</Chip>)}
      </div>
      <ol className="relative space-y-1 border-r border-line pr-5">
        {visible.slice(0, 50).map((e, i) => <li key={i} className="relative py-2">
          <span className="absolute -right-[25px] top-[15px]"><Dot tone={kindMeta[e.kind][1]} /></span>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]"><span className="flex items-center gap-2"><b>{e.title}</b><Pill tone={kindMeta[e.kind][1]}>{kindMeta[e.kind][0]}</Pill></span>{e.at && <span className="font-mono text-[12px] text-faint" dir="ltr">{e.at}</span>}</div>
          <div className="mt-0.5 text-[12px] text-muted">{e.detail}</div>
        </li>)}
      </ol>
      {!visible.length && <Empty>لا توجد أحداث لهذا التصنيف.</Empty>}
    </div>
  )
}
function HealthGrid({ components }: { components: Json }) {
  const entries = Object.entries(components || {})
  if (!entries.length) return <Empty>لا توجد بيانات صحة متاحة.</Empty>
  return (
    <div className="divide-y divide-line">
      {entries.map(([name, raw]) => { const value = raw && typeof raw === "object" ? (raw as any).status ?? (raw as any).state ?? "—" : raw; const healthy = ["healthy", "available", "locked", "ok", "running"].includes(String(value)); return (
        <div key={name} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
          <span className="flex items-center gap-2"><Dot tone={healthy ? "profit" : "loss"} /><b className="font-semibold">{name.replaceAll("_", " ")}</b></span>
          <Pill tone={healthy ? "profit" : "loss"}>{String(value)}</Pill>
        </div>
      ) })}
    </div>
  )
}
function Panel({ title, sub, action, children }: { title: string; sub?: string; action?: React.ReactNode; children: any }) {
  return <section className="min-w-0 rounded-2xl border border-line bg-surface p-5"><CardHeader title={title} sub={sub} action={action} />{children}</section>
}

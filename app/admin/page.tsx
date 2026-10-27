"use client"
import { useEffect, useMemo, useRef, useState } from "react"
import { Activity, BarChart3, Bot, ClipboardList, Gauge, LockKeyhole, Settings2, ShieldCheck, WalletCards } from "lucide-react"
import { Logo } from "@/components/Logo"
import { TIERS } from "@/lib/strategies"
import { apiIsAdmin } from "@/lib/api"
import { authHeaders } from "@/lib/supabase"

type Json = Record<string, any>
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const AUTO_REFRESH_MS = 30000

const sections: [string, string, React.ComponentType<{ size?: number; strokeWidth?: number }>][] = [
  ["overview", "نظرة عامة", Gauge],
  ["live", "البوتات الحية", Bot],
  ["strategies", "الاستراتيجيات", BarChart3],
  ["paper", "المحفظة الورقية", WalletCards],
  ["risk", "المخاطر والأمان", ShieldCheck],
  ["readiness", "جاهزية التشغيل", LockKeyhole],
  ["health", "صحة النظام", Activity],
  ["audit", "سجل التدقيق", ClipboardList],
  ["settings", "الإعدادات", Settings2],
]

/** Arabic labels for all 9 admin_control.STRATEGIES ids — the last two (wave_flats, default)
 *  have no running VPS service and must always show "no_service", never fabricated data. */
const STRATEGY_LABELS_AR: Record<string, string> = {
  trend_daily: "ترند يومي", listing_short: "شورت العملات الجديدة", momentum_ls: "مومنتم لونج/شورت",
  ratio_trend: "ترند النسبة", vol_breakout: "اختراق التقلب", rsi2_pullback: "RSI2 الارتداد",
  trend_breakout: "اختراق الترند", wave_flats: "Wave Flats", default: "Default",
}
const REAL_BOT_IDS = ["trend_daily", "listing_short", "momentum_ls", "ratio_trend", "vol_breakout", "rsi2_pullback", "trend_breakout"]
const NO_SERVICE_IDS = ["wave_flats", "default"]
const ALL_STRATEGY_IDS = [...REAL_BOT_IDS, ...NO_SERVICE_IDS]

const STATUS_META: Record<string, [string, string]> = {
  running: ["يعمل", "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"],
  stale: ["بيانات قديمة", "bg-yellow-500/15 text-yellow-300 border-yellow-500/40"],
  unavailable: ["غير متاح", "bg-red-500/15 text-red-300 border-red-500/40"],
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

function pnlColor(v: number): string { return v >= 0 ? "text-emerald-400" : "text-red-400" }
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
            <p className="text-xs text-red-300">تعذر الوصول إلى ملف الحالة العام لهذا البوت الآن{e.error ? ` (${e.error})` : ""}. لا تُعرض بيانات ملفّقة.</p>
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
      ["risk", "risk"], ["readiness", "readiness"], ["health", "health"], ["activation", "activation"], ["audit", "audit"],
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
  const sectionEndpoints: Record<string, string[]> = { overview: ["overview"], live: ["paper"], strategies: ["strategies"], paper: ["paper"], risk: ["risk"], readiness: ["readiness"], health: ["health", "activation"], audit: ["audit"], settings: [] }
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
  const liveBotsPortfolio: Json = data.paper?.live_bots || {}
  const liveStrategies: Json = liveBotsPortfolio.strategies || {}
  const liveSummaryOverview: Json = o.live_bots?.summary || liveBotsPortfolio.aggregate || {}
  const dashboardBot: Json = data.paper?.dashboard_bot || { positions: data.paper?.positions || [], history: data.paper?.history || [] }

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
    <div dir="rtl" className="min-h-screen bg-void text-ink p-4 lg:p-8">
      <div className="max-w-[1480px] mx-auto space-y-5">
        <header className="rounded-2xl border border-line bg-surface p-4 sm:p-5">
          <div className="flex flex-wrap gap-4 justify-between items-center">
            <div className="flex items-center gap-3">
              <Logo size="sm" />
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-black">مركز تحكم الإدارة</h1>
                  <span className="rounded-full border border-corona/40 bg-corona/10 px-2 py-0.5 text-[10px] font-bold text-corona">ADMIN ONLY</span>
                </div>
                <p className="text-xs text-muted mt-1">تشغيل ومراقبة آمنة · بيانات حقيقية · التداول الحقيقي مقفول</p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="rounded-xl border border-line bg-surface2 px-3 py-2 text-[11px] text-muted flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
                <span>آخر تحديث</span><b className="font-mono tabular text-ink">{lastRefreshed ? lastRefreshed.toLocaleTimeString("ar-EG") : "—"}</b>
              </div>
              <label className="rounded-xl border border-line bg-surface2 px-3 py-2 text-[11px] text-muted flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} /> تحديث تلقائي
              </label>
              <a href="/dashboard" className="px-3 py-2 rounded-xl border border-line text-xs hover:border-corona/50">المنصة</a>
              <button onClick={() => void load()} disabled={busy} className="px-3 py-2 rounded-xl bg-corona text-void text-xs font-bold disabled:opacity-50">تحديث الآن</button>
            </div>
          </div>
        </header>
        {error && <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>}
        <nav className="rounded-2xl border border-line bg-surface p-2">
          <div className="flex gap-1 overflow-x-auto">
            {sections.map(([id, label, Icon]) => (
              <button key={id} onClick={() => selectSection(id)} className={`flex items-center gap-2 whitespace-nowrap px-3 py-2.5 rounded-xl text-xs transition ${section === id ? "bg-corona text-void font-bold shadow-sm" : "text-muted hover:bg-surface2 hover:text-ink"}`}>
                <Icon size={15} strokeWidth={2} />{label}
              </button>
            ))}
          </div>
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted">
          <span>{loading ? "جاري تحديث بيانات المركز…" : lastRefreshed ? `آخر مزامنة كاملة: ${lastRefreshed.toLocaleTimeString("ar-EG")}` : "بانتظار أول مزامنة"}</span>
          {currentSectionErrors.length > 0 && <button onClick={() => void load()} className="text-red-300 hover:text-red-200">إعادة المحاولة</button>}
        </div>
        {currentSectionErrors.length > 0 && <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200">هذا القسم لم يستقبل تحديثًا جديدًا: {currentSectionErrors.join(" · ")}. البيانات السابقة، إن وُجدت، ما زالت معروضة.</div>}

        {section === "overview" && (
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
        )}

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
                  <button disabled={busy} onClick={() => confirmAction("تأكيد تغيير Kill switch؟", () => action("/api/admin/risk/kill-switch", "POST", { action: risk.kill_switch?.tripped ? "reset" : "trip", reason: "operator action", confirm: true }))} className="rounded-xl border border-red-400/50 bg-red-500/10 px-3 py-2 text-xs text-red-300 disabled:opacity-50">{risk.kill_switch?.tripped ? "إعادة ضبط Kill switch" : "تفعيل Kill switch"}</button>
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
              <KeyValueGrid value={data.readiness?.checks || {}} empty="لا توجد أدلة جاهزية متاحة" />
            </Panel>
          </div>
        )}

        {section === "health" && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="حالة الخدمات">
              <KeyValueGrid value={data.health || {}} empty="لا توجد بيانات صحة متاحة" />
            </Panel>
            <Panel title="حالة التفعيل">
              <KeyValueGrid value={data.activation || {}} empty="لا توجد بيانات تفعيل متاحة" />
            </Panel>
          </div>
        )}

        {section === "audit" && (
          <Panel title="سجل التدقيق الإداري">
            <div className="mb-4 rounded-xl border border-line bg-surface2 p-3 text-xs text-muted">كل إجراء حساس يجب أن يظهر هنا مع المنفذ والنتيجة. السجل للقراءة فقط من هذه الصفحة.</div>
            <div className="space-y-2">
              {(data.audit?.items || []).map((x: Json) => (
                <div key={x.id} className="rounded-xl border border-line bg-surface2 p-3 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><b>{x.action}</b><span className="text-muted font-mono" dir="ltr">{x.at}</span></div><div className="mt-1 text-muted">المنفذ: {x.actor || "—"} · النتيجة: {x.result || "—"}</div></div>
              ))}
              {!(data.audit?.items || []).length && <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-muted">لا توجد أحداث تدقيق متاحة.</div>}
            </div>
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
    </div>
  )
}

function Card({ title, value, tone = "neutral" }: { title: string; value: string; tone?: "profit" | "loss" | "neutral" }) {
  const color = tone === "profit" ? "text-emerald-400" : tone === "loss" ? "text-red-400" : "text-ink"
  return <div className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5"><div className="text-xs text-muted">{title}</div><div className={`text-xl font-black mt-2 ${color}`}>{value}</div></div>
}
function KeyValueGrid({ value, empty }: { value: Json; empty: string }) {
  const entries = Object.entries(value || {})
  if (!entries.length) return <div className="rounded-xl border border-dashed border-line p-4 text-xs text-muted">{empty}</div>
  return <div className="grid gap-2 sm:grid-cols-2">{entries.map(([key, val]) => <div key={key} className="rounded-xl border border-line bg-surface2 p-3"><div className="text-[10px] text-muted">{key.replaceAll("_", " ")}</div><div className="mt-1 font-mono text-sm font-bold tabular" dir="ltr">{typeof val === "object" ? JSON.stringify(val) : String(val ?? "—")}</div></div>)}</div>
}
function Panel({ title, children }: { title: string; children: any }) {
  return <section className="rounded-2xl border border-line bg-surface p-4 sm:p-5 shadow-[0_8px_30px_rgba(0,0,0,0.12)]"><div className="mb-4 flex items-center justify-between gap-3 border-b border-line pb-3"><h2 className="font-black text-sm">{title}</h2><span className="h-1.5 w-1.5 rounded-full bg-corona" /></div>{children}</section>
}

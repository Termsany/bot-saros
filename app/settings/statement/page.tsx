"use client"
import { useEffect, useState } from "react"
import { AppShell } from "@/components/AppShell"
import { Card, CardHeader, PageHeader } from "@/components/ui"
import { apiUserStatement, type Statement, type StatementTrade } from "@/lib/api"
import { NAME_AR } from "@/lib/strategies"
import { getUser } from "@/lib/supabase"

/**
 * The monthly statement (owner, 2026-11-08): every trade the user's own bots closed in one month, per bot and in total,
 * real money and Demo apart, and the month's trades as a CSV file. The numbers are the bot's own books: net of
 * Binance's fees and funding; the funding column shows only what the bot recorded.
 */
const usd = (v: number | null | undefined) => v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}$`
const tone = (v: number | null | undefined) => v == null ? "text-muted" : v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const day = (iso: string | null) => { const d = iso ? new Date(iso) : null; return d && !isNaN(d.getTime()) ? d.toLocaleDateString("ar-EG", { day: "numeric", month: "short" }) : "—" }
const monthName = (m: string) => { const d = new Date(`${m}-01T00:00:00Z`); return isNaN(d.getTime()) ? m : d.toLocaleDateString("ar-EG", { month: "long", year: "numeric", timeZone: "UTC" }) }

function csv(s: Statement){
  const cols: (keyof StatementTrade)[] = ["time", "opened", "strategy", "env", "symbol", "side", "entry", "exit", "qty", "pnl", "funding_pnl", "reason"]
  const cell = (v: unknown) => { const t = v == null ? "" : String(v); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t }
  const body = [cols.join(","), ...s.trades.map(t => cols.map(c => cell(t[c])).join(","))].join("\n")
  const url = URL.createObjectURL(new Blob(["﻿" + body], { type: "text/csv;charset=utf-8" }))
  const a = document.createElement("a"); a.href = url; a.download = `raqm-statement-${s.env || "all"}-${s.month}.csv`; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function StatementPage(){
  const [env, setEnv] = useState<"live" | "demo">("live")
  const [month, setMonth] = useState("")
  const [data, setData] = useState<Statement | null | undefined>(undefined)
  const [signedIn, setSignedIn] = useState<boolean | null>(null)
  useEffect(() => { getUser().then(u => setSignedIn(!!u)).catch(() => setSignedIn(false)) }, [])
  useEffect(() => {
    if (!signedIn) return
    let live = true
    setData(undefined)
    apiUserStatement(month, env).then(d => { if (live) setData(d) })
    return () => { live = false }
  }, [signedIn, month, env])

  const tab = (v: "live" | "demo", label: string) => (
    <button onClick={() => { setEnv(v); setMonth("") }} aria-pressed={env === v} data-testid={`statement-env-${v}`}
      className={`rounded-[10px] px-3 py-1.5 text-[13px] font-semibold transition ${env === v ? "bg-corona/15 text-corona" : "text-muted hover:text-ink"}`}>{label}</button>
  )
  const t = data?.total
  return (
    <AppShell active="/settings/statement">
      <PageHeader title="كشف الحساب الشهري" subtitle="كل صفقة قفلتها بوتاتك في الشهر، بعد رسوم Binance والـ funding"/>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="flex rounded-xl border border-line bg-surface p-1">{tab("live", "فلوس حقيقية")}{tab("demo", "Demo")}</div>
        {data && data.months.length > 0 && (
          <select value={data.month} onChange={e => setMonth(e.target.value)} data-testid="statement-month" aria-label="الشهر"
            className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink">
            {(data.months.includes(data.month) ? data.months : [data.month, ...data.months]).map(m => <option key={m} value={m}>{monthName(m)}</option>)}
          </select>
        )}
        {data && data.trades.length > 0 && (
          <button onClick={() => csv(data)} data-testid="statement-csv"
            className="rounded-xl border border-line bg-surface2 px-3 py-2 text-[13px] font-semibold text-ink transition hover:border-line2">نزّل CSV</button>
        )}
      </div>

      {signedIn === false && <Card className="mt-4"><p className="text-[14px] text-muted">سجّل دخول علشان تشوف كشف حسابك.</p></Card>}
      {signedIn && data === undefined && <Card className="mt-4"><p className="text-[14px] text-muted">بيحمّل…</p></Card>}
      {signedIn && data === null && <Card className="mt-4"><p className="text-[14px] text-loss">مقدرناش نجيب الكشف دلوقتي. جرّب تاني بعد شوية.</p></Card>}
      {data && t && (
        <>
          <Card className="mt-4">
            <CardHeader title={monthName(data.month)} sub={t.trades ? `${t.trades} صفقة مقفولة` : undefined}/>
            {t.trades === 0 ? <p className="text-[14px] text-muted">مفيش صفقات مقفولة في الشهر ده.</p> : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="statement-total">
                {[["الصافي", <span key="n" className={tone(t.net_usdt)}>{usd(t.net_usdt)}</span>],
                  ["كسبانة / خسرانة", `${t.wins} / ${t.losses}`],
                  ["الـ funding", <span key="f" className={tone(t.funding_usdt)}>{usd(t.funding_usdt)}</span>],
                  ["أحسن / أسوأ صفقة", <span key="b" dir="ltr">{usd(t.best_usdt)} / {usd(t.worst_usdt)}</span>]].map(([k, v], i) => (
                  <div key={i} className="rounded-xl bg-surface2 px-3 py-2.5">
                    <div className="text-[12px] text-muted">{k}</div><div className="mt-0.5 font-mono text-[16px] font-bold">{v}</div>
                  </div>
                ))}
              </div>
            )}
            {t.unknown > 0 && <p className="mt-3 text-[12px] text-muted">{t.unknown} صفقة نتيجتها لسه مش معروفة ومش محسوبة في الصافي.</p>}
          </Card>
          {Object.keys(data.strategies).length > 0 && (
            <Card className="mt-4">
              <CardHeader title="لكل بوت"/>
              <ul className="divide-y divide-line" data-testid="statement-bots">
                {Object.entries(data.strategies).map(([s, v]) => (
                  <li key={s} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[14px]">
                    <span className="font-semibold">{NAME_AR[s] || s}</span>
                    <span className="text-[13px] text-muted">{v.trades} صفقة · {v.wins} / {v.losses}</span>
                    <span className={`font-mono font-bold ${tone(v.net_usdt)}`} dir="ltr">{usd(v.net_usdt)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {data.trades.length > 0 && (
            <Card className="mt-4">
              <CardHeader title="الصفقات" sub="الأحدث فوق"/>
              <ul className="divide-y divide-line" data-testid="statement-trades">
                {data.trades.map((x, i) => (
                  <li key={i} data-testid="statement-trade" className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2 text-[13px]">
                    <span className="w-14 text-muted">{day(x.time)}</span>
                    <span className="font-mono font-semibold" dir="ltr">{x.symbol}</span>
                    <span className={x.side === "short" ? "text-loss" : "text-profit"}>{x.side === "short" ? "شورت" : "لونج"}</span>
                    <span className="text-faint">{NAME_AR[x.strategy] || x.strategy}</span>
                    <span className={`ms-auto font-mono font-bold ${tone(x.pnl)}`} dir="ltr">{usd(x.pnl)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </AppShell>
  )
}

"use client"
import { useEffect, useState } from "react"
import { STRATEGIES, TIERS, sharpeTone } from "@/lib/strategies"
import { apiGetSettings, apiSaveSettings, type UserSettings } from "@/lib/api"
import { pickSetup, personalPortfolio, smallestCapital } from "@/lib/personal"
import { ago, type LiveBot } from "@/lib/live-bots"

const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const tone = (v: number) => v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const usd = (v: number) => `$${v < 10 ? v.toFixed(2) : Math.floor(v).toLocaleString("en-US")}`

/** The user's capital → the size of the bot that fits it, and their personal paper portfolio following that bot. */
export function MyAccount({ tier, bots }: { tier: string, bots: LiveBot[] }){
  const unlocked = STRATEGIES.slice(0, TIERS.find(t => t.id === tier)?.count ?? 1)
  const [saved, setSaved] = useState<UserSettings|null>(null)
  const [signedIn, setSignedIn] = useState(true)
  const [capital, setCapital] = useState("")
  const [strategy, setStrategy] = useState(unlocked[0].id)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  useEffect(() => {
    apiGetSettings().then(s => {
      if (s === null) { setSignedIn(false); return }
      setSaved(s)
      if (s.capital) setCapital(String(s.capital))
      if (s.strategy) setStrategy(s.strategy)
    })
  }, [])

  const cap = Number(capital) || 0
  const s = STRATEGIES.find(x => x.id === strategy) || unlocked[0]
  const setup = cap > 0 ? pickSetup(s, cap) : null
  const fitting = unlocked.filter(x => cap >= smallestCapital(x))
  const dirty = !saved || saved.capital !== cap || saved.strategy !== strategy

  // personal portfolio = what's saved, never the unsaved edit
  const savedS = STRATEGIES.find(x => x.id === saved?.strategy)
  const savedSetup = savedS && saved?.capital ? pickSetup(savedS, saved.capital) : null
  const bot = bots.find(b => b.strategy.id === savedS?.id)
  const mine = savedS && savedSetup && saved?.started_at && bot?.raw ? personalPortfolio(savedS, bot.raw, savedSetup, saved.started_at) : null

  const save = async () => {
    setBusy(true); setMsg("")
    try { const r = await apiSaveSettings({ capital: cap, strategy }); setSaved(r); setMsg("✅ اتحفظ") }
    catch (e: any) { setMsg(`⚠️ ${e.message}`) }
    finally { setBusy(false) }
  }

  if (!signedIn) return null
  return (
    <section id="my-account" className="scroll-mt-6 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold">حسابي</h2>
          <p className="text-[13px] text-muted">اكتب رأس مالك واختار البوت — الموقع بيحدد عدد الصفقات وهامش كل صفقة على أساس الاختبار</p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs font-semibold text-muted">رأس المال (USDT)</span>
            <input type="number" min={10} inputMode="decimal" value={capital} onChange={e => setCapital(e.target.value)} placeholder="مثلا 500"
              className="mt-1 w-full rounded-lg border border-line bg-surface2 px-3 py-2 font-mono text-base outline-none focus:border-corona/50" dir="ltr"/>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-muted">البوت</span>
            <select value={strategy} onChange={e => setStrategy(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface2 px-3 py-2 text-sm outline-none focus:border-corona/50">
              {unlocked.map(x => <option key={x.id} value={x.id}>{x.nameAr}{x.risk === "high" ? " (High Risk)" : ""} — من {usd(smallestCapital(x))}</option>)}
            </select>
          </label>
          <button onClick={save} disabled={busy || !setup || !dirty}
            className="w-full rounded-lg bg-corona px-4 py-2 text-sm font-bold text-void transition disabled:opacity-40">{busy ? "بيحفظ…" : dirty ? "احفظ وابدأ المتابعة" : "محفوظ"}</button>
          {msg && <div className="text-xs text-muted">{msg}</div>}
          {saved?.started_at && dirty && <p className="text-[11px] leading-5 text-faint">لو غيّرت رأس المال أو البوت، محفظتك الشخصية هتبدأ من جديد من وقت الحفظ.</p>}
        </div>

        <div className="min-w-0">
          {cap <= 0 ? <div className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-faint">اكتب رأس مالك عشان تشوف الحجم المناسب</div>
          : !setup ? (
            <div className="rounded-xl border border-loss/30 bg-loss/5 p-4 text-sm leading-6">
              <b>{s.nameAr}</b> محتاج على الأقل <b className="font-mono">{usd(smallestCapital(s))}</b> في أصغر حجم اتختبر.
              {fitting.length ? <> رأس مالك يكفي: {fitting.map(x => x.nameAr).join("، ")}.</> : <> رأس مالك أقل من أصغر حد لكل البوتات في باقتك — جرّب بـ Paper لحد ما يكبر.</>}
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-surface2/50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-base font-bold">{setup.profile.label}</div>
                <span className="rounded-full bg-line px-2.5 py-0.5 text-[11px] font-bold text-muted">حجم {setup.profile.id === "full" ? "كامل" : setup.profile.id === "medium" ? "متوسط" : "صغير"}</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat k="هامش الصفقة" v={usd(setup.margin)} sub="رافعة x2"/>
                <Stat k="أقصى صفقات مفتوحة" v={`${setup.profile.maxOpen}`} sub={s.live === "ratio" ? "رجل (لونج/شورت)" : "في نفس الوقت"}/>
                <Stat k="أقصى تراجع متوقع" v={usd(setup.profile.maxDD / 20 * setup.margin)} sub="على حجمك، من الاختبار"/>
                <Stat k="Sharpe بعد 2024" v={setup.profile.sharpeOut.toFixed(2)} cls={sharpeTone(setup.profile.sharpeOut)} sub={`${setup.profile.trades} صفقة في الاختبار`}/>
              </div>
              <p className="mt-3 text-[11px] leading-5 text-faint">
                الحجم ده هو أكبر حجم اتختبر رأس مالك يكفيه (الحد الأدنى {usd(setup.profile.minCapital)}). الهامش = رأس المال ÷ (الصفقات المفتوحة + احتياطي لأكبر تراجع). نتايج سابقة، مش ضمان، ومش نصيحة استثمار.
              </p>
            </div>
          )}
        </div>
      </div>

      {saved?.started_at && savedS && savedSetup && (
        <div className="mt-5 border-t border-line pt-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="text-base font-bold">محفظتي (Paper)</h3>
              <p className="text-xs text-muted">{savedS.nameAr} · {savedSetup.profile.label} · هامش {usd(savedSetup.margin)} — نفس صفقات البوت الشغال بحجمك، {ago(saved.started_at)}</p>
            </div>
            {mine && <div className="flex gap-4 font-mono text-sm tabular" dir="ltr">
              <span>Realized <b className={tone(mine.realized)}>{money(mine.realized)}</b></span>
              <span>Open <b className={tone(mine.unrealized)}>{money(mine.unrealized)}</b></span>
            </div>}
          </div>
          {!mine ? <div className="mt-3 text-sm text-faint">بيحمّل بيانات البوت…</div>
          : !mine.open.length && !mine.closed.length ? (
            <div className="mt-3 rounded-xl border border-dashed border-line p-4 text-center text-sm text-faint">لسه مفيش صفقات — محفظتك بتبدأ من أول صفقة يفتحها البوت بعد ما حفظت</div>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead><tr className="text-right text-[11px] text-faint"><th className="py-1.5 font-semibold">العملة</th><th className="font-semibold">الاتجاه</th><th className="font-semibold">الحالة</th><th className="text-left font-semibold">الربح</th></tr></thead>
                <tbody>
                  {[...mine.open.map(t => ({ ...t, st: "مفتوحة" })), ...mine.closed.slice(0, 20).map(t => ({ ...t, st: `اتقفلت ${ago(t.closed)}` }))].map((t, i) => (
                    <tr key={i} className="border-t border-line/60">
                      <td className="py-1.5 font-mono font-bold" dir="ltr" style={{ textAlign: "right" }}>{t.label}</td>
                      <td className="text-xs">{t.side === "long" ? "لونج" : t.side === "short" ? "شورت" : "زوج"}</td>
                      <td className="text-xs text-muted">{t.st}</td>
                      <td className={`text-left font-mono tabular ${tone(t.pnl)}`} dir="ltr">{money(t.pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {savedS.live === "status" && <p className="mt-2 text-[11px] leading-5 text-faint">بوت الترند الشغال على x5 بوقف 16%، والمحفظة دي محسوبة بنسبة حجمك لحجمه (x2) — تقريب.</p>}
        </div>
      )}
    </section>
  )
}

function Stat({ k, v, sub, cls }: { k: string, v: string, sub: string, cls?: string }){
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-faint">{k}</div>
      <div className={`font-mono text-lg font-bold tabular ${cls || ""}`} dir="ltr" style={{ textAlign: "right" }}>{v}</div>
      <div className="text-[10px] text-faint">{sub}</div>
    </div>
  )
}

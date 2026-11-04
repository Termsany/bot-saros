"use client"
import { useEffect, useState } from "react"
import { STRATEGIES, TIERS, sharpeTone } from "@/lib/strategies"
import { apiGetSettings, apiPortfolioClose, apiSaveSettings, type UserSettings } from "@/lib/api"
import { pickSetup, personalPortfolio, profileLabelEn, smallestCapital } from "@/lib/personal"
import { type LiveBot } from "@/lib/live-bots"
import { strategyName } from "@/lib/strategies"
import { agoText, useLocale, useT } from "@/lib/i18n/locale"

const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const tone = (v: number) => v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const usd = (v: number) => `$${v < 10 ? v.toFixed(2) : Math.floor(v).toLocaleString("en-US")}`

const T = {
  ar: {
    confirm: (l: string) => `تقفل ${l} في محفظتك بالسعر الحالي؟\nده بيقفلها ليك إنت بس — البوت نفسه ما بيتغيرش.`, saved: "✅ اتحفظ",
    title: "حسابي", sub: "اكتب رأس مالك واختار البوت — الموقع بيحدد عدد الصفقات وهامش كل صفقة على أساس الاختبار",
    capital: "رأس المال (USDT)", eg: "مثلا 500", bot: "البوت", from: "من", saving: "بيحفظ…", save: "احفظ وابدأ المتابعة", isSaved: "محفوظ",
    restart: "لو غيّرت رأس المال أو البوت، محفظتك الشخصية هتبدأ من جديد من وقت الحفظ.", typeCapital: "اكتب رأس مالك عشان تشوف الحجم المناسب",
    needs: "محتاج على الأقل", smallest: "في أصغر حجم اتختبر.", fits: "رأس مالك يكفي:", none: "رأس مالك أقل من أصغر حد لكل البوتات في باقتك — جرّب بـ Paper لحد ما يكبر.",
    size: (id: string) => `حجم ${id === "full" ? "كامل" : id === "medium" ? "متوسط" : "صغير"}`,
    margin: "هامش الصفقة", lev: "رافعة x2", maxOpen: "أقصى صفقات مفتوحة", legs: "رجل (لونج/شورت)", atOnce: "في نفس الوقت", dd: "أقصى تراجع متوقع", ddSub: "على حجمك، من الاختبار",
    sharpe: "Sharpe بعد 2024", trades: (n: number) => `${n} صفقة في الاختبار`,
    note: (m: string) => `الحجم ده هو أكبر حجم اتختبر رأس مالك يكفيه (الحد الأدنى ${m}). الهامش = رأس المال ÷ (الصفقات المفتوحة + احتياطي لأكبر تراجع). نتايج سابقة، مش ضمان، ومش نصيحة استثمار.`,
    mine: "محفظتي (Paper)", mineSub: (n: string, l: string, m: string, a: string) => `${n} · ${l} · هامش ${m} — نفس صفقات البوت الشغال بحجمك، ${a}`,
    loadingBot: "بيحمّل بيانات البوت…", noTrades: "لسه مفيش صفقات — محفظتك بتبدأ من أول صفقة يفتحها البوت بعد ما حفظت",
    head: ["العملة", "الاتجاه", "الحالة", "الربح"], long: "لونج", short: "شورت", pair: "زوج", open: "مفتوحة", closedAgo: (a: string) => `اتقفلت ${a}`, close: "اقفل",
    closeNote: "«اقفل» بيقفل الصفقة في محفظتك إنت بس، بسعر البوت الحالي — البوت وباقي المستخدمين ما بيتأثروش.",
  },
  en: {
    confirm: (l: string) => `Close ${l} in your portfolio at the current price?\nIt closes it for you only — the bot itself doesn't change.`, saved: "✅ Saved",
    title: "My account", sub: "Enter your capital and pick a bot — the site sets the number of trades and each trade's margin from the backtest",
    capital: "Capital (USDT)", eg: "e.g. 500", bot: "Bot", from: "from", saving: "Saving…", save: "Save and start following", isSaved: "Saved",
    restart: "If you change the capital or the bot, your personal portfolio starts again from the time you save.", typeCapital: "Enter your capital to see the size that fits",
    needs: "needs at least", smallest: "at its smallest tested size.", fits: "Your capital fits:", none: "Your capital is under the smallest size of every bot in your plan — try it on paper until it grows.",
    size: (id: string) => `${id === "full" ? "Full" : id === "medium" ? "Medium" : "Small"} size`,
    margin: "Margin per trade", lev: "x2 leverage", maxOpen: "Most open at once", legs: "legs (long/short)", atOnce: "at the same time", dd: "Expected worst drawdown", ddSub: "at your size, from the backtest",
    sharpe: "Sharpe after 2024", trades: (n: number) => `${n} trades in the backtest`,
    note: (m: string) => `This is the largest tested size your capital covers (minimum ${m}). Margin = capital ÷ (open trades + a reserve for the worst drawdown). Past results, no promise, not investment advice.`,
    mine: "My portfolio (paper)", mineSub: (n: string, l: string, m: string, a: string) => `${n} · ${l} · margin ${m} — the live bot's trades at your size, started ${a}`,
    loadingBot: "Loading the bot's data…", noTrades: "No trades yet — your portfolio starts with the bot's first trade after you saved",
    head: ["Coin", "Side", "Status", "P&L"], long: "Long", short: "Short", pair: "Pair", open: "Open", closedAgo: (a: string) => `closed ${a}`, close: "Close",
    closeNote: "\"Close\" closes the trade in your portfolio only, at the bot's current price — the bot and other users aren't affected.",
  },
}

/** The user's capital → the size of the bot that fits it, and their personal paper portfolio following that bot. */
export function MyAccount({ tier, bots }: { tier: string, bots: LiveBot[] }){
  const t = useT(T)
  const locale = useLocale(), en = locale === "en"
  const lbl = (l: string) => en ? profileLabelEn(l) : l
  const unlocked = STRATEGIES.slice(0, TIERS.find(t => t.id === tier)?.count ?? 1)
  const [saved, setSaved] = useState<UserSettings|null>(null)
  const [signedIn, setSignedIn] = useState(true)
  const [capital, setCapital] = useState("")
  const [strategy, setStrategy] = useState(unlocked[0].id)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [closing, setClosing] = useState("")
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
  const mine = savedS && savedSetup && saved?.started_at && bot?.raw ? personalPortfolio(savedS, bot.raw, savedSetup, saved.started_at, saved.closes || []) : null

  const closeMine = async (label: string, opened: string) => {
    if (!confirm(t.confirm(label))) return
    setClosing(label + opened)
    try { await apiPortfolioClose(label, opened); const s = await apiGetSettings(); if (s) setSaved(s) }
    catch (e: any) { alert(`⚠️ ${e.message}`) }
    finally { setClosing("") }
  }

  const save = async () => {
    setBusy(true); setMsg("")
    try { const r = await apiSaveSettings({ capital: cap, strategy }); setSaved(r); setMsg(t.saved) }
    catch (e: any) { setMsg(`⚠️ ${e.message}`) }
    finally { setBusy(false) }
  }

  if (!signedIn) return null
  return (
    <section id="my-account" className="scroll-mt-6 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold">{t.title}</h2>
          <p className="text-[13px] text-muted">{t.sub}</p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs font-semibold text-muted">{t.capital}</span>
            <input type="number" min={10} inputMode="decimal" value={capital} onChange={e => setCapital(e.target.value)} placeholder={t.eg}
              className="mt-1 w-full rounded-lg border border-line bg-surface2 px-3 py-2 font-mono text-base outline-none focus:border-corona/50" dir="ltr"/>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-muted">{t.bot}</span>
            <select value={strategy} onChange={e => setStrategy(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface2 px-3 py-2 text-sm outline-none focus:border-corona/50">
              {unlocked.map(x => <option key={x.id} value={x.id}>{strategyName(x, locale)}{x.risk === "high" ? " (High Risk)" : ""} — {t.from} {usd(smallestCapital(x))}</option>)}
            </select>
          </label>
          <button onClick={save} disabled={busy || !setup || !dirty}
            className="w-full rounded-lg bg-corona px-4 py-2 text-sm font-bold text-on-corona transition hover:bg-corona-soft disabled:opacity-40">{busy ? t.saving : dirty ? t.save : t.isSaved}</button>
          {msg && <div className="text-xs text-muted">{msg}</div>}
          {saved?.started_at && dirty && <p className="text-[11px] leading-5 text-faint">{t.restart}</p>}
        </div>

        <div className="min-w-0">
          {cap <= 0 ? <div className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-faint">{t.typeCapital}</div>
          : !setup ? (
            <div className="rounded-xl border border-loss/30 bg-loss/5 p-4 text-sm leading-6">
              <b>{strategyName(s, locale)}</b> {t.needs} <b className="font-mono">{usd(smallestCapital(s))}</b> {t.smallest}
              {fitting.length ? <> {t.fits} {fitting.map(x => strategyName(x, locale)).join(en ? ", " : "، ")}.</> : <> {t.none}</>}
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-surface2/50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-base font-bold">{lbl(setup.profile.label)}</div>
                <span className="rounded-full bg-line px-2.5 py-0.5 text-[11px] font-bold text-muted">{t.size(setup.profile.id)}</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat k={t.margin} v={usd(setup.margin)} sub={t.lev}/>
                <Stat k={t.maxOpen} v={`${setup.profile.maxOpen}`} sub={s.live === "ratio" ? t.legs : t.atOnce}/>
                <Stat k={t.dd} v={usd(setup.profile.maxDD / 20 * setup.margin)} sub={t.ddSub}/>
                <Stat k={t.sharpe} v={setup.profile.sharpeOut.toFixed(2)} cls={sharpeTone(setup.profile.sharpeOut)} sub={t.trades(setup.profile.trades)}/>
              </div>
              <p className="mt-3 text-[11px] leading-5 text-faint">
                {t.note(usd(setup.profile.minCapital))}
              </p>
            </div>
          )}
        </div>
      </div>

      {saved?.started_at && savedS && savedSetup && (
        <div className="mt-5 border-t border-line pt-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="text-base font-bold">{t.mine}</h3>
              <p className="text-xs text-muted">{t.mineSub(strategyName(savedS, locale), lbl(savedSetup.profile.label), usd(savedSetup.margin), agoText(saved.started_at, locale))}</p>
            </div>
            {mine && <div className="flex gap-4 font-mono text-sm tabular" dir="ltr">
              <span>Realized <b className={tone(mine.realized)}>{money(mine.realized)}</b></span>
              <span>Open <b className={tone(mine.unrealized)}>{money(mine.unrealized)}</b></span>
            </div>}
          </div>
          {!mine ? <div className="mt-3 text-sm text-faint">{t.loadingBot}</div>
          : !mine.open.length && !mine.closed.length ? (
            <div className="mt-3 rounded-xl border border-dashed border-line p-4 text-center text-sm text-faint">{t.noTrades}</div>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead><tr className="text-start text-[11px] text-faint"><th className="py-1.5 text-start font-semibold">{t.head[0]}</th><th className="text-start font-semibold">{t.head[1]}</th><th className="text-start font-semibold">{t.head[2]}</th><th className="text-end font-semibold">{t.head[3]}</th><th></th></tr></thead>
                <tbody>
                  {[...mine.open.map(x => ({ ...x, isOpen: true, st: t.open })), ...mine.closed.slice(0, 20).map(x => ({ ...x, isOpen: false, st: t.closedAgo(agoText(x.closed, locale)) }))].map((tr, i) => (
                    <tr key={i} className="border-t border-line/60">
                      <td className="py-1.5 font-mono font-bold" dir="ltr" style={{ textAlign: en ? "left" : "right" }}>{tr.label}</td>
                      <td className="text-xs">{tr.side === "long" ? t.long : tr.side === "short" ? t.short : t.pair}</td>
                      <td className="text-xs text-muted">{tr.st}</td>
                      <td className={`text-end font-mono tabular ${tone(tr.pnl)}`} dir="ltr">{money(tr.pnl)}</td>
                      <td className="ps-1 text-end">{tr.isOpen && (
                        <button onClick={() => closeMine(tr.label, tr.opened)} disabled={closing === tr.label + tr.opened}
                          className="rounded-md border border-loss/50 px-2 py-0.5 text-[11px] font-bold text-loss hover:bg-loss/10 disabled:opacity-50">
                          {closing === tr.label + tr.opened ? "…" : t.close}</button>)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-2 text-[11px] leading-5 text-faint">{t.closeNote}</p>
        </div>
      )}
    </section>
  )
}

function Stat({ k, v, sub, cls }: { k: string, v: string, sub: string, cls?: string }){
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-faint">{k}</div>
      <div className={`font-mono text-lg font-bold tabular ${cls || ""}`} dir="ltr" style={{ textAlign: useLocale() === "en" ? "left" : "right" }}>{v}</div>
      <div className="text-[10px] text-faint">{sub}</div>
    </div>
  )
}

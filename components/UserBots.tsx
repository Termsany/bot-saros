"use client"
import { useCallback, useEffect, useState } from "react"
import { apiSetUserBots, apiUserBotClose, apiUserBots } from "@/lib/api"
import { NAME_AR, NAME_EN } from "@/lib/strategies"
import type { Locale } from "@/lib/i18n/landing"
import { Card, CardHeader, Pill, btn, field, label, type Tone } from "@/components/ui"

/** What the provisioner (root, on the server) answered for this user — docs/phase2-design.md. */
const ANSWER_EN: Record<string, [string, string]> = {
  running: ["Running", "Your bots are running on your Binance Demo account."],
  waiting_approval: ["Waiting for approval", "Your request arrived — the admin hasn't approved your account yet. Your bots start on their own once they do."],
  no_consent: ["Consent missing", "Type the consent text in step 3 first."],
  no_keys: ["Keys missing", "Save your Binance Demo keys in step 1 first."],
  owner_key: ["Not your key", "This key belongs to the admin account. Create a key on your own Binance Demo account and save it in step 1."],
  no_place: ["No room right now", "The server has reached its account limit. Your request is saved and starts as soon as a place frees up."],
  off: ["Stopped", "Your bots are stopped. Open trades exit on their own rule and stop."],
  refused: ["Refused", "The server doesn't accept these settings."],
  live_off: ["Real money not open yet", "Real money for users isn't switched on on the server yet. Your request is saved and starts on its own once it is."],
  key_refused: ["Key refused", "Your Binance key didn't pass the server's checks:"],
}
const T = {
  ar: { na: "مش متاح دلوقتي", pickOne: "اختار استراتيجية واحدة على الأقل", marginRule: "المارجن لكل صفقة لازم يكون أكبر من صفر ومش أكبر من راس المال",
    confirmOn: (names: string, cap: number, m: number) => `تشغيل على Binance Demo (فلوس وهمية):\n${names}\nراس المال ${cap}$ · مارجن ${m}$ لكل صفقة`, confirmOff: "إيقاف البوتات؟ الصفقات المفتوحة بتخرج على قاعدتها.",
    savedOn: "✅ اتحفظ — السيرفر بيطبّقه خلال دقيقة", savedOff: "✅ اتوقفت", confirmClose: (s: string) => `قفل ${s} دلوقتي بسعر السوق؟`, closeSent: "✅ طلب القفل اتبعت — بيتنفّذ خلال دقيقة",
    title: "4 · البوتات بتاعتك", sub: (max: number) => `على Binance Demo بس (فلوس وهمية) · لحد ${max} استراتيجيات · نفس كود بوت الإدارة`,
    needConsent: "محتاج الموافقة (الخطوة 3) قبل ما البوتات تشتغل.", capital: "راس المال ($) — مش أكتر من رصيد الـ Demo", margin: "المارجن لكل صفقة ($)",
    saveChanges: "احفظ التغييرات", start: "شغّل البوتات", stop: "وقّف البوتات", running: "شغال", notRunning: "مش شغال", blocked: "الدخول متوقف: ",
    noOpen: "مفيش صفقات مفتوحة", head: ["العملة", "الاتجاه", "الدخول", "الربح", ""], close: "اقفل",
    liveTitle: "4 · البوت بتاعك (فلوس حقيقية)", liveSub: "momentum بس · بالمبلغ والمارجن اللي في الخطوة 2 · بيفتح السلة أول ما يشتغل، والتبديل كل اتنين",
    liveConfirm: (cap: number, m: number) => `⚠️ فلوس حقيقية على حسابك في Binance:\nmomentum · راس المال ${cap}$ · مارجن ${m}$ للصفقة\nبيفتح السلة أول ما يشتغل.`,
    liveNeedConsent: "وافق على الفلوس الحقيقية بالأرقام دي في الخطوة 3 الأول.", liveStart: "شغّل momentum بفلوس حقيقية" },
  en: { na: "Not available right now", pickOne: "Pick at least one strategy", marginRule: "The margin per trade must be above zero and not more than the capital",
    confirmOn: (names: string, cap: number, m: number) => `Run on Binance Demo (play money):\n${names}\nCapital $${cap} · margin $${m} per trade`, confirmOff: "Stop the bots? Open trades exit on their own rule.",
    savedOn: "✅ Saved — the server applies it within a minute", savedOff: "✅ Stopped", confirmClose: (s: string) => `Close ${s} now at the market price?`, closeSent: "✅ Close request sent — it runs within a minute",
    title: "4 · Your bots", sub: (max: number) => `Binance Demo only (play money) · up to ${max} strategies · the same code as the admin's bot`,
    needConsent: "Needs your consent (step 3) before the bots can run.", capital: "Capital ($) — not more than your Demo balance", margin: "Margin per trade ($)",
    saveChanges: "Save changes", start: "Start the bots", stop: "Stop the bots", running: "Running", notRunning: "Not running", blocked: "Entries stopped: ",
    noOpen: "No open trades", head: ["Coin", "Side", "Entry", "P&L", ""], close: "Close",
    liveTitle: "4 · Your bot (real money)", liveSub: "momentum only · with step 2's amount and margin · opens its basket as soon as it starts, rebalances every Monday",
    liveConfirm: (cap: number, m: number) => `⚠️ Real money on your Binance account:\nmomentum · capital $${cap} · margin $${m} per trade\nIt opens its basket as soon as it starts.`,
    liveNeedConsent: "Agree to real money with these numbers in step 3 first.", liveStart: "Start momentum with real money" },
}
const ANSWER: Record<string, [string, Tone, string]> = {
  running: ["شغّالة", "profit", "البوتات بتاعتك شغالة على حساب Binance Demo بتاعك."],
  waiting_approval: ["مستنية الموافقة", "corona", "طلبك وصل — الإدارة لسه ما وافقتش على حسابك. أول ما توافق البوتات بتشتغل لوحدها."],
  no_consent: ["ناقص الموافقة", "loss", "اكتب نص الموافقة في الخطوة 3 الأول."],
  no_keys: ["ناقص المفاتيح", "loss", "احفظ مفاتيح Binance Demo في الخطوة 1 الأول."],
  owner_key: ["المفتاح مش بتاعك", "loss", "المفتاح ده بتاع حساب الإدارة. اعمل مفتاح من حساب Binance Demo بتاعك انت واحفظه في الخطوة 1."],
  no_place: ["مفيش مكان دلوقتي", "corona", "عدد الحسابات على السيرفر وصل للحد. طلبك محفوظ وهيشتغل أول ما يفضى مكان."],
  off: ["متوقفة", "neutral", "البوتات متوقفة. الصفقات المفتوحة بتخرج على قاعدتها ووقفها."],
  refused: ["اترفض", "loss", "الإعدادات مش مقبولة على السيرفر."],
  live_off: ["الفلوس الحقيقية لسه مش مفتوحة", "corona", "الفلوس الحقيقية للمستخدمين لسه ما اتفتحتش على السيرفر. طلبك محفوظ وهيشتغل لوحده أول ما تتفتح."],
  key_refused: ["المفتاح اترفض", "loss", "مفتاح Binance بتاعك ما عدّاش فحص السيرفر:"],
}
const money = (v?: number|null) => v == null ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`

/** A user's own strategies on their own Binance Demo account: choose up to the allowed number, capital and margin;
 *  the server's provisioner runs each as the owner's bot does, after the owner approves the account. */
export function UserBots({ consent, locale = "ar", money: mode = "demo", liveCapital = 0, liveMargin = 0, liveConsented = false }: {
  consent: { enabled: boolean, leverage?: number, risk_per_trade_pct?: number, max_aggregate_risk_pct?: number }, locale?: Locale,
  money?: "demo" | "live", liveCapital?: number, liveMargin?: number, liveConsented?: boolean }){
  const live = mode === "live"
  const t = T[locale], en = locale === "en"
  const LABELS = en ? NAME_EN : NAME_AR
  const align = { textAlign: en ? "left" : "right" } as const
  const [data, setData] = useState<any|null|undefined>(undefined)
  const [chosen, setChosen] = useState<string[]>([])
  const [capital, setCapital] = useState("1000")
  const [margin, setMargin] = useState("20")
  const [msg, setMsg] = useState("")
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const d = await apiUserBots(); setData(d)
    if(d?.desired){ setChosen(d.desired.strategies || []); setCapital(String(d.desired.capital_usdt ?? "")); setMargin(String(d.desired.capital_margin_override_usdt ?? "")) }
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t) }, [load])

  if(data === undefined) return null
  if(data === null) return <Card><p className="py-6 text-center text-[13px] text-faint">{t.na}</p></Card>
  const max = live ? 1 : data.rules?.max_strategies ?? 2
  const base = ANSWER[data.provision?.state], ansEn = ANSWER_EN[data.provision?.state]
  const ans0: [string, Tone, string] | null = base ? (en && ansEn ? [ansEn[0], base[1], ansEn[1]] : base) : null
  // the reason the server gives with a refused key (which of the preflight's checks failed), after the sentence
  const ans: [string, Tone, string] | null = ans0 && data.provision?.why ? [ans0[0], ans0[1], `${ans0[2]} ${data.provision.why}`] : ans0
  const offered: string[] = live ? (data.rules?.live?.strategies || ["momentum_ls"]) : (data.rules?.strategies || [])
  const shown = chosen.filter(s => offered.includes(s))
  const enabled = !!data.desired?.enabled && (data.desired?.env === "live") === live

  function toggle(s: string){
    setChosen(c => { const cur = c.filter(x => offered.includes(x)); return cur.includes(s) ? cur.filter(x => x !== s) : cur.length < max ? [...cur, s] : cur })
  }
  async function save(on: boolean){
    if(live){                 // real money: momentum, step 2's numbers (the server computes the limits from them)
      if(on && !liveConsented){ setMsg(t.liveNeedConsent); return }
      if(!confirm(on ? t.liveConfirm(liveCapital, liveMargin) : t.confirmOff)) return
      setBusy(true); setMsg("")
      try{
        await apiSetUserBots({ env: "live", enabled: on, strategies: ["momentum_ls"], leverage: 2, risk_per_trade_pct: 1, max_aggregate_risk_pct: 3,
          capital_usdt: liveCapital, capital_margin_override_usdt: liveMargin })
        setMsg(on ? t.savedOn : t.savedOff); load()
      }catch(e: any){ setMsg(`⚠️ ${e.message}`) }
      finally{ setBusy(false) }
      return
    }
    const cap = Number(capital) || 0, m = Number(margin) || 0
    if(on && !shown.length){ setMsg(t.pickOne); return }
    if(on && !(m > 0 && m <= cap)){ setMsg(t.marginRule); return }
    const text = on ? t.confirmOn(shown.map(s => LABELS[s] || s).join("\n"), cap, m) : t.confirmOff
    if(!confirm(text)) return
    setBusy(true); setMsg("")
    try{
      await apiSetUserBots({ env: "demo", enabled: on, strategies: shown, leverage: consent.leverage ?? 2,
        risk_per_trade_pct: consent.risk_per_trade_pct ?? 0.25, max_aggregate_risk_pct: consent.max_aggregate_risk_pct ?? 1,
        capital_usdt: cap, capital_margin_override_usdt: m })
      setMsg(on ? t.savedOn : t.savedOff); load()
    }catch(e: any){ setMsg(`⚠️ ${e.message}`) }
    finally{ setBusy(false) }
  }
  async function close(s: string, symbol: string){
    if(!confirm(t.confirmClose(symbol))) return
    try{ await apiUserBotClose(s, symbol); setMsg(t.closeSent); setTimeout(load, 70_000) }
    catch(e: any){ setMsg(`⚠️ ${e.message}`) }
  }

  const bots = Object.entries(data.bots || {}) as [string, any][]
  return (
    <Card className={live ? "border-loss/30" : "border-signal/30"}>
      <CardHeader title={live ? t.liveTitle : t.title} sub={live ? t.liveSub : t.sub(max)}
        action={ans && <Pill tone={ans[1]}>{ans[0]}</Pill>} />
      {ans && <p className="mb-4 rounded-xl bg-surface2 px-4 py-3 text-[13px] text-muted">{ans[2]}</p>}
      {(live ? !liveConsented : !consent.enabled) && <p className="mb-4 text-[12px] text-loss">{live ? t.liveNeedConsent : t.needConsent}</p>}

      {!live && <>
      <div className="mb-4 grid gap-2 sm:grid-cols-2">
        {offered.map((s: string) => {
          const on = shown.includes(s), full = !on && shown.length >= max
          return (
            <button key={s} type="button" onClick={() => toggle(s)} disabled={full}
              className={`rounded-xl border px-3 py-2.5 text-start text-[14px] ${on ? "border-signal bg-signal/10 font-semibold" : "border-line"} ${full ? "opacity-40" : ""}`}>
              {on ? "✓ " : ""}{LABELS[s] || s}
            </button>
          )
        })}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block"><span className={label}>{t.capital}</span>
          <input type="number" min={0} value={capital} onChange={e => setCapital(e.target.value)} className={`${field} font-mono`} dir="ltr"/></label>
        <label className="block"><span className={label}>{t.margin}</span>
          <input type="number" min={0} value={margin} onChange={e => setMargin(e.target.value)} className={`${field} font-mono`} dir="ltr"/></label>
      </div>
      </>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button onClick={() => save(true)} disabled={busy || (live && !liveConsented)}
          className={live ? "inline-flex items-center justify-center gap-2 rounded-xl bg-loss px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40" : btn.primary}>
          {enabled ? t.saveChanges : live ? t.liveStart : t.start}</button>
        {enabled && <button onClick={() => save(false)} disabled={busy} className={btn.secondary}>{t.stop}</button>}
        {msg && <span className="text-[12px] text-muted">{msg}</span>}
      </div>

      {bots.length > 0 && (
        <div className="mt-5 space-y-4">
          {bots.map(([s, b]) => (
            <div key={s} className="rounded-xl border border-line p-3">
              <div className="mb-2 flex items-center justify-between">
                <b className="text-[14px]">{LABELS[s] || s}</b>
                <Pill tone={b.running ? "profit" : "neutral"}>{b.running ? t.running : t.notRunning}</Pill>
              </div>
              {b.entry_block && <p className="mb-2 text-[12px] text-corona">{t.blocked}{b.entry_block}</p>}
              {(b.positions || []).length === 0 ? <p className="text-[12px] text-faint">{t.noOpen}</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[480px] text-[13px]">
                    <thead className="text-[12px] text-faint"><tr>{t.head.map(h => <th key={h} className="px-2 py-1.5 text-start font-semibold">{h}</th>)}</tr></thead>
                    <tbody>
                      {b.positions.map((p: any) => (
                        <tr key={p.symbol} className="border-t border-line">
                          <td className="px-2 py-2 font-mono" dir="ltr" style={align}>{p.symbol}</td>
                          <td className="px-2 py-2"><Pill tone={p.side === "short" ? "loss" : "profit"}>{p.side === "short" ? "SHORT" : "LONG"}</Pill></td>
                          <td className="px-2 py-2 font-mono" dir="ltr" style={align}>{p.entry}</td>
                          <td className={`px-2 py-2 font-mono ${(p.pnl ?? 0) >= 0 ? "text-profit" : "text-loss"}`} dir="ltr" style={align}>{p.pnl_estimated ? "≈ " : ""}{money(p.pnl)}</td>
                          <td className="px-2 py-2"><button onClick={() => close(s, p.symbol)} className="text-[12px] text-loss underline">{t.close}</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

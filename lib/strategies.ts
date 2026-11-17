import BOT_STATS from "./bot-stats.json"
import CATALOG from "./strategies.json"
import EXTRA_STATS from "./extra-stats.json"

/** Measured by research/bots_stats.py on every Binance USDT-M perpetual since 2019 (delisted included), coins chosen
 *  by volume at the time, fees + real funding, $20 x2 per position — never edit these numbers by hand. */
export type BotStats = { trades: number; winRate: number; pf: number; pnl: number; maxDD: number; sharpeIn: number; sharpeOut: number;
  pnlOut: number; years: Record<string, number>; equity: [string, number][]
  /** smallest capital that runs it as tested (x2) on Binance: margin per trade large enough for every order to meet the
   *  exchange minimum ($5, ETH $20, BTC $50) × most positions open at once + worst drawdown at that size */
  minCapital: number; minMargin: number; maxOpen: number; testedCapital: number
  /** smaller tested sizes (fewer coins / positions) for the capital-based setup — see lib/personal.ts */
  profiles?: import("./personal").Profile[] }
/** `live` = the file the bot writes on the VPS (https://demo.da3m.io/<live>.json). `perCoin` = can be backtested on one coin. */
export type Strategy = { id: string; name: string; nameAr: string; desc: string; method: string; tier: "free"|"starter"|"pro"|"elite"; icon: string
  risk: "normal" | "high"; live: string; perCoin: boolean; sides: string } & BotStats
export const STATS_META = BOT_STATS.meta
export const COMBINED = BOT_STATS.combined as unknown as { core: Omit<BotStats, "trades"|"winRate"|"pf">, all: Omit<BotStats, "trades"|"winRate"|"pf"> }
export const BOT_PAGE = "https://demo.da3m.io"   // was bot.da3m.io until 2026-11-06

/** The one list (lib/strategies.json, development-plan 3.4): ids, names, status files, order. The API and the scripts read
 *  the same file. Order matters: a plan unlocks the first N planned ones (see TIERS.count). */
export type CatalogEntry = { id: string; name: string; nameAr: string; live: string; planned: boolean; demoSample: number | null }
export const CATALOG_STRATEGIES = CATALOG.strategies as CatalogEntry[]

// What only the site says about each: description, method, plan, icon, risk.
type Details = Omit<Strategy, keyof BotStats | "id" | "name" | "nameAr" | "live">
const DETAILS: Record<string, Details> = {
  trend_daily: { desc:"لونج على العملات اللي في ترند صاعد",
    method:"كل يوم عند الإغلاق، على أعلى 10 عملات فوليوم: لو السعر أعلى من سعره من 20 و60 و120 يوم في 2 من 3 = يشتري، ولو الترند وقف يبيع. حجم الصفقة يصغر لما السوق يهيج، ووقف حماية قبل التصفية. مبنية على أبحاث الـ Time-Series Momentum.",
    tier:"free", icon:"⟋", risk:"normal", perCoin:true, sides:"لونج" },
  momentum_ls: { desc:"لونج الأقوى وشورت الأضعف كل أسبوع",
    method:"كل أسبوع بيرتّب أعلى 50 عملة فوليوم حسب أدائها آخر أسبوعين: لونج على أقوى 5 وشورت على أضعف 5، ويبدّلهم بعد أسبوع (وقف 40%). مبنية على أبحاث الزخم بين العملات (Liu, Tsyvinski & Wu 2022).",
    tier:"starter", icon:"⇅", risk:"normal", perCoin:false, sides:"لونج + شورت" },
  listing_short: { desc:"شورت العملة الجديدة بعد ما الهوجة تهدى",
    method:"شورت على العملة الجديدة على Binance بعد 30 يوم من إدراجها، ويقفل بعد 90 يوم أو لو السعر طلع 40% فوق الدخول، بحد أقصى 10 صفقات. مبنية على أبحاث إن العملات الجديدة بتنزل بعد الهوجة (Benedetti & Kostovetsky 2021).",
    tier:"pro", icon:"↘", risk:"normal", perCoin:false, sides:"شورت" },
  ratio_trend: { desc:"لونج/شورت على أزواج أكبر 7 عملات",
    method:"كل الأزواج بين أعلى 7 عملات فوليوم (21 زوج): لو نسبة سعر العملتين فوق متوسط 50 يوم = لونج الأولى وشورت التانية، والعكس. أقصى تراجع كبير، ولما اتضاف للبوتات التلاتة التانية قلّل نتيجتهم في آخر سنتين — عشان كده High Risk.",
    tier:"elite", icon:"⚖", risk:"high", perCoin:false, sides:"لونج + شورت" },
}
const MEASURED = BOT_STATS.bots as unknown as Record<string, BotStats>
export const STRATEGIES: Strategy[] = CATALOG_STRATEGIES.filter(c => c.planned)
  .map(c => ({ id: c.id, name: c.name, nameAr: c.nameAr, live: c.live, ...DETAILS[c.id], ...MEASURED[c.id] }))

/** The rest of the paper bots on the backtest page (owner, 2026-11-17): research/extra_bots_stats.py, the same data and
 *  costs, x2 only. Open to every plan (the plan's day limit still applies): they are not in TIERS.count, which stays the
 *  four above. */
const EXTRA_DETAILS: Record<string, { name: string; nameAr: string; live: string } & Details> = {
  momentum_daily: { name: "Momentum daily", nameAr: "مومنتم يومي", live: "momentum_daily", desc: "سلة المومنتم بتتبدل كل يوم",
    method: "كل يوم 00:00 UTC بيرتّب أعلى 50 عملة فوليوم حسب أدائها آخر أسبوعين: لونج أقوى 5 وشورت أضعف 5. العملة اللي لسه في السلة بتفضل مفتوحة، واللي خرجت بتتقفل (وقف 40%). ده اللي شغال على الحسابات الحقيقية.",
    tier: "free", icon: "⇅", risk: "normal", perCoin: false, sides: "لونج + شورت" },
  momentum_daily_b7: { name: "Momentum daily · buffer 7", nameAr: "مومنتم يومي · هامش 7", live: "momentum_daily_b7", desc: "المومنتم اليومي، والعملة بتفضل طول ما هي من أقوى 7",
    method: "نفس المومنتم اليومي، والفرق إن العملة المفتوحة بتفضل طول ما هي من أقوى 7 (للونج) أو أضعف 7 (للشورت)، مش 5 بس. تبديلات أقل وأكبر هبوط أصغر، بربح أقل شوية (research §37).",
    tier: "free", icon: "⇅", risk: "normal", perCoin: false, sides: "لونج + شورت" },
  momentum_daily_vol: { name: "Momentum daily · vol-sized", nameAr: "مومنتم يومي · حجم بالتذبذب", live: "momentum_daily_vol", desc: "المومنتم اليومي، وحجم كل صفقة على قد تذبذب العملة",
    method: "نفس المومنتم اليومي، والفرق إن هامش كل صفقة جديدة على قد تذبذب العملة آخر 60 يوم: العنيفة بتاخد هامش أصغر (لحد الربع) والهادية أكبر (لحد الضعف). أكبر هبوط أقل من النص بنفس رأس المال (research §39).",
    tier: "free", icon: "⇅", risk: "normal", perCoin: false, sides: "لونج + شورت" },
  rsi2_pullback: { name: "RSI-2 Pullback", nameAr: "RSI-2 شراء الهبوط", live: "rsi2", desc: "شراء الهبوط الحاد في ترند صاعد",
    method: "على أعلى 10 عملات فوليوم: لو العملة فوق متوسط 200 يوم وRSI-2 نزل تحت 5، بيشتري افتتاح بكرة. بيخرج بعد أول إغلاق فوق متوسط 5 أيام، أو بعد 10 أيام (Connors 2008).",
    tier: "free", icon: "↗", risk: "normal", perCoin: false, sides: "لونج" },
  rsi2_btc: { name: "RSI-2 + BTC filter", nameAr: "RSI-2 + فلتر BTC", live: "rsi2_btc", desc: "RSI-2، بس لما BTC يكون فوق متوسط 200 يوم",
    method: "نفس RSI-2، والفرق إنه مش بيدخل غير لما BTC يكون مقفل فوق متوسط 200 يوم. صفقات أقل ونسبة كسب أعلى (research §28).",
    tier: "free", icon: "↗", risk: "normal", perCoin: false, sides: "لونج" },
  vol_breakout: { name: "Volatility Breakout", nameAr: "بريك أوت التذبذب (Williams)", live: "breakout", desc: "شراء اختراق الافتتاح + 0.7 من مدى امبارح",
    method: "على أعلى 10 عملات فوليوم، لو إغلاق امبارح فوق متوسط 20 يوم: بيشتري لما السعر يطلع فوق الافتتاح بـ 0.7 من مدى امبارح، ويبيع افتتاح بكرة (Larry Williams).",
    tier: "free", icon: "⤴", risk: "normal", perCoin: false, sides: "لونج" },
  trend_breakout: { name: "Trend Breakout", nameAr: "اختراق الترند", live: "tbreak", desc: "كسر أعلى 20 يوم في ترند صاعد",
    method: "على أعلى 100 عملة فوليوم في ترند صاعد (السعر فوق متوسط 50 فوق 150 فوق 200 يوم): بيشتري لما الإغلاق يكسر أعلى سعر في 20 يوم، ويبيع بعد إغلاق تحت متوسط 20 يوم، ووقف 40% (Minervini/Darvas).",
    tier: "free", icon: "⤴", risk: "normal", perCoin: false, sides: "لونج" },
  ratio_nobtc: { name: "Ratio · no BTC/ETH", nameAr: "Ratio من غير BTC/ETH", live: "ratio_nobtc", desc: "ترند النسبة على أعلى 7 عملات من غير BTC وETH",
    method: "زي ترند النسبة، على الأزواج بين أعلى 7 عملات فوليوم من غير BTC وETH: لو نسبة العملتين فوق متوسط 50 يوم = لونج الأولى وشورت التانية، والعكس (research §25).",
    tier: "free", icon: "⚖", risk: "high", perCoin: false, sides: "لونج + شورت" },
  ratio_trail: { name: "Ratio · no BTC/ETH · trail 20%", nameAr: "Ratio من غير BTC/ETH · trailing 20%", live: "ratio_trail", desc: "Ratio من غير BTC/ETH، وبيقفل لو النسبة رجعت 20% من أحسن نقطة",
    method: "نفس Ratio من غير BTC/ETH، والفرق إن الزوج بيتقفل لو النسبة رجعت 20% من أحسن مستوى من وقت الدخول، ويفضل مقفول لحد ما الترند يتقلب (research §35).",
    tier: "free", icon: "⚖", risk: "high", perCoin: false, sides: "لونج + شورت" },
  ratio_trail_btc: { name: "Ratio · trail 20%", nameAr: "Ratio · trailing 20%", live: "ratio_trail_btc", desc: "ترند النسبة على أعلى 7 عملات، مع trailing 20%",
    method: "ترند النسبة على أعلى 7 عملات فوليوم (BTC وETH جوا)، والزوج بيتقفل لو النسبة رجعت 20% من أحسن مستوى من وقت الدخول (research §35).",
    tier: "free", icon: "⚖", risk: "high", perCoin: false, sides: "لونج + شورت" },
}
const EXTRA_MEASURED = EXTRA_STATS.bots as unknown as Record<string, BotStats>
export const BACKTEST_EXTRA: Strategy[] = Object.entries(EXTRA_DETAILS).map(([id, d]) => ({ id, ...d, ...EXTRA_MEASURED[id] }))
/** Every strategy the backtest page lists: the plans' four first, then the open ones. */
export const BACKTEST_ALL: Strategy[] = [...STRATEGIES, ...BACKTEST_EXTRA]
export const isOpenBacktest = (id: string) => BACKTEST_EXTRA.some(s => s.id === id)

/** What the live bots section needs about a bot. */
export type LiveStrategy = Pick<Strategy, "id" | "name" | "nameAr" | "desc" | "sides" | "risk" | "live"> & { experimental?: boolean }
const EXPERIMENT_DETAILS: Record<string, Pick<Strategy, "desc" | "sides" | "risk">> = {
  vol_breakout: { desc: "شراء اختراق الافتتاح + 0.7 من مدى امبارح، خروج افتتاح بكرة", sides: "لونج", risk: "normal" },
  rsi2_pullback: { desc: "شراء الهبوط الحاد في ترند صاعد، خروج فوق متوسط 5 أيام", sides: "لونج", risk: "normal" },
  trend_breakout: { desc: "كسر أعلى 20 يوم في ترند صاعد، خروج تحت متوسط 20 يوم", sides: "لونج", risk: "normal" },
}
/** Paper experiments running on the server next to the four bots — not in the plans or the backtest until they prove
 *  themselves (research/traders_study.py, traders_robustness.py). */
export const EXPERIMENTS: LiveStrategy[] = CATALOG_STRATEGIES.filter(c => !c.planned)
  .map(c => ({ id: c.id, name: c.name, nameAr: c.nameAr, live: c.live, ...EXPERIMENT_DETAILS[c.id], experimental: true }))
export const LIVE_BOTS: LiveStrategy[] = [...STRATEGIES, ...EXPERIMENTS]
/** A strategy's name in the page's language. */
export const strategyName = (s: { name: string; nameAr: string }, locale: "en" | "ar") => locale === "en" ? s.name : s.nameAr
/** Every strategy's Arabic name, by id (for pages that only have the id). */
export const NAME_AR: Record<string, string> = Object.fromEntries(CATALOG_STRATEGIES.map(c => [c.id, c.nameAr]))
/** …and its English name. */
export const NAME_EN: Record<string, string> = Object.fromEntries(CATALOG_STRATEGIES.map(c => [c.id, c.name]))

/** Text colour for a profit factor / Sharpe: green good, gold roughly flat, red losing. */
export const pfTone = (pf: number) => pf >= 1.05 ? "text-profit" : pf >= 0.95 ? "text-corona" : "text-loss"
export const sharpeTone = (s: number) => s >= 1 ? "text-profit" : s >= 0.5 ? "text-corona" : "text-loss"

export const TIERS = [
  { id:"free", name:"Free", price:"0$", per:"/شهر", cta:"ابدأ مجانا", features:["Backtest الترند اليومي · لحد 7 أيام","صفقات الاختبار وحاسبة راس المال للترند","متابعة كل البوتات مباشر (Paper)"], count:1, color:"#8B91A7" },
  { id:"starter", name:"Starter", price:"29$", per:"/شهر", cta:"اشترك", features:["Backtest الترند + المومنتم · لحد 30 يوم","صفقات الاختبار وحاسبة راس المال للاتنين","متابعة كل البوتات مباشر (Paper)"], count:2, color:"#4CC9F0" },
  { id:"pro", name:"Pro", price:"59$", per:"/شهر", cta:"اشترك Pro", features:["+ شورت العملات الجديدة · Backtest لحد 90 يوم","صفقات الاختبار وحاسبة راس المال للتلاتة","متابعة كل البوتات مباشر (Paper)"], count:3, color:"#7B61FF", popular:true },
  { id:"elite", name:"Elite", price:"99$", per:"/شهر", cta:"اشترك Elite", features:["الـ 4 استراتيجيات + ترند النسبة (High Risk)","Backtest من غير حد للمدة","متابعة كل البوتات مباشر (Paper)"], count:4, color:"#F5B841" },
]
/** The plan that unlocks strategy number i (0-based). */
export const unlockTier = (i: number) => TIERS.find(t => t.count > i) || TIERS[TIERS.length - 1]

// Max backtest range in days, end date inclusive (null = unlimited). The backend enforces the same
// numbers (TIER_BACKTEST_DAYS in backend/app/main.py) — keep them in sync.
export const BACKTEST_DAYS: Record<string, number|null> = { free: 7, starter: 30, pro: 90, elite: null }
export function backtestSpanDays(from: string, to: string){
  return Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1
}
export const TREND_ID = "trend_daily"

/** Plain-language note for the minimum capital. */
export const minCapitalNote = (s: Strategy) =>
  `هامش ${s.minMargin < 10 ? s.minMargin.toFixed(2) : Math.ceil(s.minMargin)}$ للصفقة × لحد ${s.maxOpen} ${s.live === "ratio" ? "رجل مفتوحة" : "صفقة مفتوحة"} + أكبر خسارة متتالية في الاختبار، على رافعة x2`

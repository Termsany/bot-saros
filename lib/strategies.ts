import BOT_STATS from "./bot-stats.json"

/** Measured by research/bots_stats.py on every Binance USDT-M perpetual since 2019 (delisted included), coins chosen
 *  by volume at the time, fees + real funding, $20 x2 per position — never edit these numbers by hand. */
export type BotStats = { trades: number; winRate: number; pf: number; pnl: number; maxDD: number; sharpeIn: number; sharpeOut: number;
  pnlOut: number; years: Record<string, number>; equity: [string, number][] }
/** `live` = the file the bot writes on the VPS (https://bot.da3m.io/<live>.json). `perCoin` = can be backtested on one coin. */
export type Strategy = { id: string; name: string; nameAr: string; desc: string; method: string; tier: "free"|"starter"|"pro"|"elite"; icon: string
  risk: "normal" | "high"; live: string; perCoin: boolean; sides: string } & BotStats
export const STATS_META = BOT_STATS.meta
export const COMBINED = BOT_STATS.combined as unknown as { core: Omit<BotStats, "trades"|"winRate"|"pf">, all: Omit<BotStats, "trades"|"winRate"|"pf"> }
export const BOT_PAGE = "https://bot.da3m.io"

// Order matters: a plan unlocks the first N (see TIERS.count; the backend's STRATEGY_ORDER is the same).
const BASE: Omit<Strategy, keyof BotStats>[] = [
  { id:"trend_daily", name:"Daily Trend", nameAr:"ترند يومي", desc:"لونج على العملات اللي في ترند صاعد",
    method:"كل يوم عند الإغلاق، على أعلى 10 عملات فوليوم: لو السعر أعلى من سعره من 20 و60 و120 يوم في 2 من 3 = يشتري، ولو الترند وقف يبيع. حجم الصفقة يصغر لما السوق يهيج، ووقف حماية قبل التصفية. مبنية على أبحاث الـ Time-Series Momentum.",
    tier:"free", icon:"⟋", risk:"normal", live:"status", perCoin:true, sides:"لونج" },
  { id:"momentum_ls", name:"Momentum L/S", nameAr:"مومنتم لونج/شورت", desc:"لونج الأقوى وشورت الأضعف كل أسبوع",
    method:"كل أسبوع بيرتّب أعلى 50 عملة فوليوم حسب أدائها آخر أسبوعين: لونج على أقوى 5 وشورت على أضعف 5، ويبدّلهم بعد أسبوع (وقف 40%). مبنية على أبحاث الزخم بين العملات (Liu, Tsyvinski & Wu 2022).",
    tier:"starter", icon:"⇅", risk:"normal", live:"momentum", perCoin:false, sides:"لونج + شورت" },
  { id:"listing_short", name:"New Listing Short", nameAr:"شورت العملات الجديدة", desc:"شورت العملة الجديدة بعد ما الهوجة تهدى",
    method:"شورت على العملة الجديدة على Binance بعد 30 يوم من إدراجها، ويقفل بعد 90 يوم أو لو السعر طلع 40% فوق الدخول، بحد أقصى 10 صفقات. مبنية على أبحاث إن العملات الجديدة بتنزل بعد الهوجة (Benedetti & Kostovetsky 2021).",
    tier:"pro", icon:"↘", risk:"normal", live:"listing", perCoin:false, sides:"شورت" },
  { id:"ratio_trend", name:"Ratio Trend", nameAr:"ترند النسبة بين العملات", desc:"لونج/شورت على أزواج أكبر 7 عملات",
    method:"كل الأزواج بين أعلى 7 عملات فوليوم (21 زوج): لو نسبة سعر العملتين فوق متوسط 50 يوم = لونج الأولى وشورت التانية، والعكس. أقصى تراجع كبير، ولما اتضاف للبوتات التلاتة التانية قلّل نتيجتهم في آخر سنتين — عشان كده High Risk.",
    tier:"elite", icon:"⚖", risk:"high", live:"ratio", perCoin:false, sides:"لونج + شورت" },
]
const MEASURED = BOT_STATS.bots as unknown as Record<string, BotStats>
export const STRATEGIES: Strategy[] = BASE.map(s => ({ ...s, ...MEASURED[s.id] }))

/** Text colour for a profit factor / Sharpe: green good, gold roughly flat, red losing. */
export const pfTone = (pf: number) => pf >= 1.05 ? "text-profit" : pf >= 0.95 ? "text-corona" : "text-loss"
export const sharpeTone = (s: number) => s >= 1 ? "text-profit" : s >= 0.5 ? "text-corona" : "text-loss"

export const TIERS = [
  { id:"free", name:"Free", price:"0$", per:"/شهر", cta:"ابدأ مجانا", features:["بوت الترند اليومي","متابعة البوت مباشر","Backtest 7 أيام"], count:1, color:"#8B91A7" },
  { id:"starter", name:"Starter", price:"29$", per:"/شهر", cta:"اشترك", features:["بوتين: ترند + مومنتم","لونج وشورت","Backtest 30 يوم"], count:2, color:"#4CC9F0" },
  { id:"pro", name:"Pro", price:"59$", per:"/شهر", cta:"اشترك Pro", features:["3 بوتات: + شورت العملات الجديدة","Futures LONG/SHORT","Backtest 90 يوم"], count:3, color:"#7B61FF", popular:true },
  { id:"elite", name:"Elite", price:"99$", per:"/شهر", cta:"اشترك Elite", features:["الـ 4 بوتات","+ Ratio Trend (High Risk)","Backtest غير محدود"], count:4, color:"#F5B841" },
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

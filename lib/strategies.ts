import STATS_FILE from "./strategy-stats.json"

/** Measured with the bot's own engine by research/measure_strategies.py — never edit these numbers by hand. */
export type StrategyStats = { trades: number; winRate: number; pf: number; pnl: number; setsWon: number; oosPnl: number; oosSetsWon: number; maxDD: number }
export type Strategy = { id: string; name: string; nameAr: string; desc: string; method: string; tier: "free"|"starter"|"pro"|"elite"; icon: string
  /** set when measured on different data than the 8 standard 1h/4h sets */ basis?: string } & StrategyStats
export const STATS_META = STATS_FILE.meta

// Order matters: a plan unlocks the first N (see TIERS.count). `method` describes what the code really does.
const BASE: Omit<Strategy, keyof StrategyStats>[] = [
  { id:"rsi_macd", name:"RSI+MACD", nameAr:"RSI+MACD", desc:"تشبع + مومنتوم", method:"RSI(14): تحت 30 شراء قوي، تحت 40 شراء خفيف، فوق 60/70 بيع. ويضيف اتجاه MACD Histogram (فوق الصفر = صاعد).", tier:"free", icon:"◉" },
  { id:"classical", name:"Classical", nameAr:"كلاسيكي", desc:"SMA + ميل الترند", method:"السعر فوق SMA20 وSMA20 فوق SMA50 = صاعد، والعكس هابط. ويضيف ميل السعر في آخر 20 شمعة.", tier:"free", icon:"━" },
  { id:"ichimoku", name:"Ichimoku", nameAr:"إيشيموكو", desc:"السحابة + Tenkan/Kijun", method:"السعر فوق السحابة (Senkou A وB) = صاعد، تحتها = هابط. وTenkan فوق Kijun يقوّي الإشارة.", tier:"starter", icon:"☁" },
  { id:"dow", name:"Dow", nameAr:"داو", desc:"قمم وقيعان صاعدة", method:"نظرية داو: يعدّ آخر 5 قمم و5 قيعان. قمم وقيعان أعلى من اللي قبلها = ترند صاعد، أقل = هابط.", tier:"starter", icon:"↗" },
  { id:"gann", name:"Gann", nameAr:"جان", desc:"زاوية الميل", method:"ميل السعر في آخر 10 شموع مقارنة بمدى آخر 50 شمعة. ميل قوي لفوق = صاعد، لتحت = هابط.", tier:"starter", icon:"⬡" },
  { id:"sr", name:"S/R", nameAr:"دعوم", desc:"Pivot", method:"آخر 6 قمم وقيعان (Pivots). قرب الدعم بأقل من 1.5% = شراء، قرب المقاومة = بيع.", tier:"starter", icon:"▭" },
  { id:"elliott", name:"Elliott", nameAr:"موجي", desc:"ZigZag + فيبو", method:"آخر 9 قمم وقيعان + فيبوناتشي: ارتداد بين 50% و61.8% مع شمعة صاعدة = شراء، كسر 61.8% = بيع، اختراق القمة = شراء.", tier:"pro", icon:"〰" },
  { id:"smc", name:"SMC", nameAr:"Smart Money", desc:"BOS + FVG + OB", method:"كسر هيكل (BOS) لقمة أو قاع سابق + فجوة سعرية (FVG) من 3 شموع + Order Block قريب من آخر قاع.", tier:"elite", icon:"◆" },
  { id:"vwap", name:"VWAP", nameAr:"VWAP", desc:"حجم + VWAP", method:"السعر فوق VWAP آخر 20 شمعة = صاعد، تحته = هابط. حجم أكبر من 1.8× المتوسط يقوّي الإشارة.", tier:"elite", icon:"▣" },
  { id:"supertrend", name:"SuperTrend", nameAr:"سوبر ترند", desc:"EMA + ATR", method:"السعر أعلى من EMA(10) + 1.5×ATR = صاعد، أقل من EMA(10) − 1.5×ATR = هابط، وبينهم محايد.", tier:"elite", icon:"▲" },
  { id:"bollinger", name:"Bollinger", nameAr:"بولنجر", desc:"Bands + RSI", method:"اختراق الحد العلوي (20، 2σ) مع RSI فوق 60 = شراء، كسر السفلي مع RSI تحت 40 = بيع. وإلا: RSI تحت 30 شراء، فوق 70 بيع.", tier:"elite", icon:"◎" },
  { id:"harmonic", name:"Harmonic", nameAr:"هارمونيك", desc:"نسب Gartley", method:"آخر 4 قمم وقيعان: لو الارتداد بين 0.618 و0.786 والسعر ارتد 1% من آخر قاع = شراء، أو نزل 1% من آخر قمة = بيع.", tier:"elite", icon:"⬢" },
  { id:"ict", name:"ICT Killzone", nameAr:"ICT", desc:"جلسات لندن ونيويورك", method:"وقت جلسة لندن (7–10 UTC) أو نيويورك (12–15 UTC): اختراق أعلى قمة آخر 20 شمعة = بيع (Sweep)، كسر أدنى قاع = شراء.", tier:"elite", icon:"◐" },
  { id:"heikin", name:"Heikin+ADX", nameAr:"هيكن + ADX", desc:"Heikin Ashi + قوة الترند", method:"شمعتين Heikin Ashi متتاليتين في نفس الاتجاه، وADX فوق 25 يقوّيها وتحت 15 يضعّفها.", tier:"elite", icon:"⬣" },
  { id:"ai", name:"Consensus", nameAr:"الإجماع", desc:"إجماع الـ 14 استراتيجية", method:"متوسط إشارات الـ 14 استراتيجية التانية، ويقوّي الإشارة لو 4 أو أكتر متفقين في نفس الاتجاه.", tier:"elite", icon:"✦" },
  { id:"wave_flats", name:"Wave Flats", nameAr:"موجات Flat", desc:"تصحيح Flat + فيبو", method:"بعد موجة A قوية (ZigZag): ارتداد لمنطقة 0.382–0.236 بشمعة ابتلاعية أو Pin Bar = Regular Flat وهدفه 1.272، أو موجة b تكسر القمة ثم c = Running/Expanded Flat وأهدافه 1.414 (نص الكمية) و1.618. الوقف تحت أدنى شمعتين −0.2% وبيتنقل للدخول لما السعر يكسر قمة التصحيح. بتشتغل لوحدها بوقفها وأهدافها، مش مع باقي الاستراتيجيات.", tier:"elite", icon:"≋" },
  { id:"trend_daily", name:"Daily Trend", nameAr:"ترند يومي", desc:"زخم 20/60/120 يوم + حجم حسب التذبذب", method:"كل يوم عند الإغلاق: لو السعر أعلى من سعره من 20 و60 و120 يوم في 2 من 3 على الأقل = يشتري (لونج بس)، ولو الترند وقف يبيع. حجم الصفقة يصغر لما السوق يهيج (هدف تذبذب 80% في السنة)، ووقف حماية قبل التصفية حسب الرافعة. مبنية على أبحاث الـ Time-Series Momentum. فريم يومي بس، وبتشتغل لوحدها.", tier:"elite", icon:"⟋",
    basis:`فريم يومي · ${STATS_FILE.meta.trendDaily.sets} عملات ${STATS_FILE.meta.trendDaily.from.slice(0,4)}–${STATS_FILE.meta.trendDaily.to.slice(0,4)} · $20 × ${STATS_FILE.meta.trendDaily.leverage} · شامل الـ funding` },
]

const MEASURED = STATS_FILE.strategies as Record<string, StrategyStats>
export const STRATEGIES: Strategy[] = BASE.map(s => ({ ...s, ...MEASURED[s.id] }))

/** Consistency across the 8 data sets, both periods — more meaningful than win rate alone. */
export const consistency = (s: StrategyStats) => s.setsWon + s.oosSetsWon
export const MOST_CONSISTENT = [...STRATEGIES].sort((a, b) => consistency(b) - consistency(a) || b.pnl - a.pnl)[0]
/** Text colour for a profit factor: above 1.05 profitable, 0.95–1.05 roughly break-even, below that losing. */
export const pfTone = (pf: number) => pf >= 1.05 ? "text-profit" : pf >= 0.95 ? "text-corona" : "text-loss"

export const TIERS = [
  { id:"free", name:"Free", price:"0$", per:"/شهر", cta:"ابدأ مجانا", features:["استراتيجيتان","Spot فقط","Backtest 7 أيام"], count:2, color:"#8B91A7" },
  { id:"starter", name:"Starter", price:"29$", per:"/شهر", cta:"اشترك", features:["6 استراتيجيات","Spot","Backtest 30 يوم"], count:6, color:"#4CC9F0" },
  { id:"pro", name:"Pro", price:"59$", per:"/شهر", cta:"اشترك Pro", features:["7 استراتيجيات","Futures LONG/SHORT x5","Backtest 90 يوم"], count:7, color:"#7B61FF", popular:true },
  { id:"elite", name:"Elite", price:"99$", per:"/شهر", cta:"اشترك Elite", features:["17 استراتيجية","ترند يومي + SMC + ICT","Backtest غير محدود"], count:17, color:"#F5B841" },
]
// Max backtest range in days, end date inclusive (null = unlimited). The backend enforces the same
// numbers (TIER_BACKTEST_DAYS in backend/app/main.py) — keep them in sync.
/** Strategies with their own entries and exits (Wave Flats, daily trend) always run alone. */
export const WAVE_ID = "wave_flats", TREND_ID = "trend_daily"
export const SOLO = [WAVE_ID, TREND_ID]
export function toggleStrategy(selected: string[], id: string, single = false){
  if(single || SOLO.includes(id)) return [id]
  const rest = selected.filter(x => !SOLO.includes(x))
  return rest.includes(id) ? rest.filter(x => x !== id) : [...rest, id]
}

export const BACKTEST_DAYS: Record<string, number|null> = { free: 7, starter: 30, pro: 90, elite: null }
export function backtestSpanDays(from: string, to: string){
  return Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1
}

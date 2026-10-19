export type Strategy = { id: string; name: string; nameAr: string; desc: string; method: string; tier: "free"|"starter"|"pro"|"elite"; winRate: number; pf: number; icon: string }
export const STRATEGIES: Strategy[] = [
  { id:"rsi_macd", name:"RSI+MACD", nameAr:"RSI+MACD", desc:"تشبع + مومنتوم", method:"RSI14 <30 تشبع بيعي / >70 تشبع شرائي + MACD Histogram فوق/تحت الصفر. دخول LONG عند RSI منخفض و MACD صاعد، SHORT عند العكس.", tier:"free", winRate:28.6, pf:0.44, icon:"◉" },
  { id:"classical", name:"Classical", nameAr:"كلاسيكي", desc:"SMA + ترند", method:"السعر فوق SMA20>SMA50 = صاعد، تحته = هابط + ميل الترند 20 شمعة + تأكيد حجم.", tier:"free", winRate:35, pf:0.8, icon:"━" },
  { id:"ichimoku", name:"Ichimoku", nameAr:"إيشيموكو", desc:"السحابة + Tenkan", method:"السعر فوق السحابة (Senkou A/B) + Tenkan فوق Kijun = LONG قوي. تحتها = SHORT. Chicou فوق السعر تأكيد.", tier:"starter", winRate:38, pf:1.1, icon:"☁" },
  { id:"dow", name:"Dow", nameAr:"داو", desc:"HH/HL", method:"نظريـة داو: قمم وقيعان صاعدة Higher Highs/Lows = ترند صاعد، هابطة = هابط. عد 5 قمم/قيعان أخيرة.", tier:"starter", winRate:33, pf:0.9, icon:"↗" },
  { id:"gann", name:"Gann", nameAr:"جان", desc:"1/8 + زاوية", method:"تقسيم مدى 50 شمعة إلى 8 مستويات (1/8) + زاوية ميل السعر. قرب مستوى جان = ارتداد متوقع.", tier:"starter", winRate:31, pf:0.85, icon:"⬡" },
  { id:"sr", name:"S/R", nameAr:"دعوم", desc:"Pivot", method:"تحديد Pivot High/Low آخر 6 مستويات. قرب الدعم 1.5% = شراء، قرب المقاومة = بيع.", tier:"starter", winRate:40, pf:1.2, icon:"▭" },
  { id:"elliott", name:"Elliott", nameAr:"موجي", desc:"ZigZag + فيبو", method:"ZigZag 5 نقاط لتحديد الموجات + فيبوناتشي 38.2%/50%/61.8%. ارتداد 50-61.8% = موجة دافعة، كسر 61.8% = تصحيح عميق.", tier:"pro", winRate:42, pf:1.4, icon:"〰" },
  { id:"smc", name:"SMC", nameAr:"Smart Money", desc:"OB + FVG + BOS", method:"Order Block (آخر شمعة انعكاسية) + Fair Value Gap (فجوة 3 شمعات) + Break of Structure (كسر قمة/قاع).", tier:"elite", winRate:48, pf:1.8, icon:"◆" },
  { id:"vwap", name:"VWAP", nameAr:"VWAP", desc:"حجم + VWAP", method:"السعر فوق VWAP20 = صاعد، تحته = هابط + انفجار حجم >1.8x المتوسط كتأكيد.", tier:"elite", winRate:45, pf:1.6, icon:"▣" },
  { id:"supertrend", name:"SuperTrend", nameAr:"سوبر ترند", desc:"ATR + ترند", method:"SuperTrend ATR(10)×3: السعر فوق EMA+1.5×ATR = LONG، تحته = SHORT + ATR يتوسع = زخم.", tier:"elite", winRate:44, pf:1.5, icon:"▲" },
  { id:"bollinger", name:"Bollinger", nameAr:"بولنجر", desc:"Squeeze + StochRSI", method:"Bollinger Bands 20×2: Squeeze (عرض ضيق) = انفجار قريب. اختراق علوي + RSI>60 = LONG.", tier:"elite", winRate:41, pf:1.3, icon:"◎" },
  { id:"harmonic", name:"Harmonic", nameAr:"هارمونيك", desc:"Gartley/Bat", method:"4 Pivot أخيرة: نسبة AB/XA بين 0.618-0.786 = نموذج Gartley. قاع جديد مع ارتداد = صاعد.", tier:"elite", winRate:39, pf:1.2, icon:"⬢" },
  { id:"ict", name:"ICT Killzone", nameAr:"ICT ⭐", desc:"London/NY — بطل BTC 4h 100% و 15m 83% PF 30", method:"Killzone لندن 7-10 UTC / نيويورك 12-15 UTC + Sweep قمة/قاع الجلسة = انعكاس. BTC 4h: +10.48 PF inf (3/3) و BTC 15m: +3.63 PF 30 (5/6) — يحتاج Walk-Forward على كل عملة.", tier:"elite", winRate:71, pf:3.32, icon:"◐" },
  { id:"heikin", name:"Heikin+ADX", nameAr:"هيكن + ADX", desc:"فلترة", method:"Heikin Ashi شمعتان متتاليتان بنفس الاتجاه + ADX>25 قوي يضاعف الإشارة، <15 يضعفها.", tier:"elite", winRate:43, pf:1.4, icon:"⬣" },
  { id:"ai", name:"AI Ensemble", nameAr:"AI", desc:"تكيف تلقائي", method:"متوسط مرجح لكل الاستراتيجيات + تعزيز إذا 4+ استراتيجيات متفقة (×1.3). إجماع قوي = إشارة أقوى.", tier:"elite", winRate:50, pf:1.9, icon:"✦" },
]
export const TIERS = [
  { id:"free", name:"Free", price:"0$", per:"/شهر", cta:"ابدأ مجانا", features:["استراتيجيتان","Spot فقط","Backtest 7 أيام"], count:2, color:"#8A9AB0" },
  { id:"starter", name:"Starter", price:"29$", per:"/شهر", cta:"اشترك", features:["6 استراتيجيات","Spot","Backtest 30 يوم"], count:6, color:"#60A5FA" },
  { id:"pro", name:"Pro", price:"59$", per:"/شهر", cta:"اشترك Pro", features:["7 استراتيجيات","Futures LONG/SHORT x5","Backtest 90 يوم"], count:7, color:"#00D395", popular:true },
  { id:"elite", name:"Elite", price:"99$", per:"/شهر", cta:"اشترك Elite", features:["15 استراتيجية","AI + SMC + ICT","Backtest غير محدود"], count:15, color:"#FFB800" },
]
// Max backtest range in days, end date inclusive (null = unlimited). The backend enforces the same
// numbers (TIER_BACKTEST_DAYS in backend/app/main.py) — keep them in sync.
export const BACKTEST_DAYS: Record<string, number|null> = { free: 7, starter: 30, pro: 90, elite: null }
export function backtestSpanDays(from: string, to: string){
  return Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1
}

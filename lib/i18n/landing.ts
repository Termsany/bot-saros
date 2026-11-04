// The landing page's words, English and Arabic (Figma "RAQM — Global Redesign 2026", page 03 · Landing).
// Numbers are not here: they come from lib/bot-stats.json, lib/demo-baseline.json and the live real-money file.
export type Locale = "en" | "ar"

export const DIR: Record<Locale, "ltr" | "rtl"> = { en: "ltr", ar: "rtl" }
export const OTHER: Record<Locale, { href: string; label: string }> = { en: { href: "/ar", label: "عربي" }, ar: { href: "/", label: "EN" } }

const en = {
  metaTitle: "RAQM — quant trading bots, proven in public",
  metaDesc: "Four crypto trading strategies tested on every Binance perpetual since 2019, with real fees and funding. One trades real money in public.",
  nav: { strategies: "Strategies", proof: "Live proof", pricing: "Pricing", backtest: "Backtest", faq: "FAQ" },
  auth: { signIn: "Sign in", start: "Start free", dashboard: "Dashboard" },
  theme: { toDark: "Switch to dark", toLight: "Switch to light" },
  hero: {
    badge: "LIVE · real money on Binance Futures",
    title: ["Quant trading bots,", "proven in public."],
    sub: "Four strategies that held up on every Binance perpetual since 2019 — delisted coins, real fees and real funding included. One of them trades real money right now, and every trade is public.",
    ctaStart: "Start free — no card", ctaLive: "Watch the live bot",
    trust: ["Stops placed on the exchange", "Read-only public page", "Cancel anytime"],
  },
  live: {
    title: "Momentum L/S · weekly", running: "Running", stopped: "Not reporting", loading: "Loading the live account…", error: "The live account can't be read right now.",
    openPnl: "open P&L · live prices", legs: (n: number) => `${n} legs · x2`, next: "Next rebalance", stops: "Every stop is on Binance", more: (n: number) => `+${n} more on the live page`,
  },
  strip: [
    ["Data since", "2019", "every USDT-M perpetual, delisted too"],
    ["Strategies", "4 + 3", "4 in the plans · 3 on trial"],
    ["Watched", "24/7", "problems reach the team on Telegram"],
    ["Real-money stops", "100%", "placed on the exchange, not in the app"],
  ],
  how: {
    eyebrow: "How it works", title: "Research first. Real money last.", sub: "Every strategy walks the same road before it touches money, and you can follow each step.",
    steps: [
      ["01 · Backtest", "Every Binance perpetual since 2019, delisted coins included, with real fees and real funding. Settings chosen on data before 2024, tested on the rest."],
      ["02 · Demo, in public", "Each bot trades a Binance Demo account around the clock. Every week its trades are measured against the backtest — far from it means switched off, not re-tuned."],
      ["03 · Small real money", "Only then a small real account, every stop placed on the exchange, a kill switch, and a public page anyone can check."],
    ],
  },
  strat: {
    eyebrow: "Strategies", title: "Four strategies made the cut.", sub: "We tested more than fifteen ideas from trading research. These held up on every coin — with their losing stretches shown, not hidden.",
    pf: "Profit factor", win: "Win rate", trades: "Trades", sharpe: "Sharpe 2024+", high: "High risk", watch: "See them running",
    names: { trend_daily: "Daily Trend", momentum_ls: "Momentum L/S", listing_short: "New Listing Short", ratio_trend: "Ratio Trend" } as Record<string, string>,
    desc: { trend_daily: "Long the coins in an uptrend, out when the trend stops.", momentum_ls: "Long the strongest five, short the weakest five — every week.", listing_short: "Short a new listing once the hype fades.", ratio_trend: "Long/short pairs of the top seven coins." } as Record<string, string>,
    note: (from: string, to: string, n: number) => `Backtest on ${n} Binance perpetuals, ${from} → ${to}, after fees and funding. Past results don't promise future ones.`,
  },
  proof: {
    eyebrow: "Live proof", title: "The real account, next to its backtest.", sub: "Updated from the live account. If the real numbers drift from the backtest, you see it here first.",
    measure: "Measure", real: "Real account", backtest: "Backtest",
    rows: { fees: "Fees per fill", closed: "Closed trades", win: "Win rate", pf: "Profit factor", edge: "Edge holds up to" },
    feesReal: "0.050%", wait: (n: number, of: number) => `after ${of} trades (${n}/${of})`, edgeBt: "≈0.7% cost / fill",
    sideBadge: "Honest by design", sideText: "Small samples lie. We show the count next to every number and wait for 30 closed trades before calling anything a result.", sideCta: "Open the live page",
  },
  pricing: {
    eyebrow: "Pricing", title: "Start free. Upgrade when you want more.", sub: "Every plan follows the bots live. Plans unlock longer backtests and more strategies.",
    per: "/ month", popular: "Most popular", redirect: "Opening checkout…", error: "Payment error",
    cta: { free: "Start free", starter: "Choose Starter", pro: "Choose Pro", elite: "Choose Elite" } as Record<string, string>,
    features: {
      free: ["Daily Trend backtest · up to 7 days", "Tested trades & capital calculator", "Follow every bot live (paper)"],
      starter: ["+ Momentum L/S · up to 30 days", "Tested trades & calculator for both", "Follow every bot live (paper)"],
      pro: ["+ New Listing Short · up to 90 days", "Tested trades & calculator for all three", "Follow every bot live (paper)"],
      elite: ["All 4 + Ratio Trend (high risk)", "Unlimited backtest range", "Follow every bot live (paper)"],
    } as Record<string, string[]>,
    note: ["Plans unlock backtests, tested trades and the capital calculator. ", "They don't run bots on your Binance account yet", " — following the bots live is open to everyone. Monthly, cancel anytime, no refunds — "],
    terms: "Terms & risks (Arabic)",
  },
  faq: {
    eyebrow: "Questions", title: "Straight answers.",
    items: [
      ["Do the bots guarantee a profit?", "No. The numbers here are tests on past data and a small live account. Leveraged crypto trading is high risk, and you can lose part or all of what you put in."],
      ["Do I need real money to try it?", "No. Backtests and the paper portfolio use play money, and the free plan needs no card."],
      ["Where do the numbers come from?", "Every USDT-M perpetual on Binance since 2019, delisted coins included, coins picked by their volume at the time, after real fees and funding. Settings were chosen on data before 2024; the 2024+ numbers are the part not used to choose them."],
      ["Will a plan trade on my Binance account?", "Not yet. Plans unlock research tools. The real-money page shows the owner's own account, for transparency."],
      ["Is payment safe? Can I cancel?", "Payments go through Stripe and card details never touch our servers. Cancel anytime from your account."],
    ],
  },
  cta: { title: "Watch it trade before you trust it.", sub: "The live page is public. No sign-up needed.", live: "See the live bot", start: "Start free" },
  footer: { terms: "Terms & risks", live: "Live page", backtest: "Backtest", risk: "Trading leveraged crypto futures is high risk. Backtests and past live results don't guarantee future results. RAQM is a research and tracking tool, not investment advice." },
}

type Dict = typeof en

const ar: Dict = {
  metaTitle: "رقم — بوتات تداول بالأرقام، ونتايجها قدام الكل",
  metaDesc: "أربع استراتيجيات تداول اتجربت على كل عقود Binance من 2019 بالرسوم والـ funding الحقيقي. واحدة منهم شغالة بفلوس حقيقية قدام الكل.",
  nav: { strategies: "الاستراتيجيات", proof: "الإثبات المباشر", pricing: "الباقات", backtest: "Backtest", faq: "أسئلة" },
  auth: { signIn: "دخول", start: "ابدأ مجانًا", dashboard: "لوحة التحكم" },
  theme: { toDark: "الوضع الغامق", toLight: "الوضع الفاتح" },
  hero: {
    badge: "مباشر · فلوس حقيقية على Binance Futures",
    title: ["بوتات تداول بالأرقام،", "ونتايجها قدام الكل."],
    sub: "أربع استراتيجيات صمدت على كل عقود Binance من 2019، بالعملات اللي اتشالت والرسوم والـ funding الحقيقي. واحدة منهم شغالة بفلوس حقيقية دلوقتي، وكل صفقة قدامك.",
    ctaStart: "ابدأ مجانًا — من غير كارت", ctaLive: "شوف البوت المباشر",
    trust: ["الوقف على المنصة نفسها", "صفحة عامة للقراية بس", "تلغي في أي وقت"],
  },
  live: {
    title: "مومنتم لونج/شورت · أسبوعي", running: "شغال", stopped: "مش بيكتب حالته", loading: "بيحمّل الحساب الحقيقي…", error: "الحساب الحقيقي مش متاح دلوقتي.",
    openPnl: "ربح المفتوح · بالسعر اللحظي", legs: (n: number) => `${n} صفقة · x2`, next: "التبديل الجاي", stops: "كل وقف على Binance", more: (n: number) => `+${n} كمان في الصفحة المباشرة`,
  },
  strip: [
    ["داتا من", "2019", "كل عقود USDT-M، والمشطوبة كمان"],
    ["استراتيجيات", "4 + 3", "4 في الباقات · 3 تحت التجربة"],
    ["مراقبة", "24/7", "أي مشكلة بتوصل الفريق على تليجرام"],
    ["وقف الفلوس الحقيقية", "100%", "على المنصة نفسها، مش في التطبيق"],
  ],
  how: {
    eyebrow: "إزاي بيشتغل", title: "البحث الأول، والفلوس الحقيقية آخر حاجة.", sub: "كل استراتيجية بتمشي نفس الطريق قبل ما تلمس فلوس، وتقدر تتابع كل خطوة.",
    steps: [
      ["01 · Backtest", "كل عقود Binance من 2019، بالعملات اللي اتشالت والرسوم والـ funding الحقيقي. الإعدادات اتختارت على اللي قبل 2024، واتختبرت على الباقي."],
      ["02 · Demo قدام الكل", "كل بوت بيتداول على حساب Binance Demo طول اليوم. وكل أسبوع صفقاته بتتقاس قصاد الباكتست — لو بعيدة يتقفل، مش يتعدّل."],
      ["03 · فلوس حقيقية صغيرة", "وبعدها بس حساب حقيقي صغير، كل وقف على المنصة، وزرار إيقاف، وصفحة عامة أي حد يقدر يشوفها."],
    ],
  },
  strat: {
    eyebrow: "الاستراتيجيات", title: "أربع استراتيجيات نجحت في الاختبار.", sub: "جربنا أكتر من 15 فكرة من أبحاث التداول. دول اللي صمدوا على كل العملات — والفترات الخسرانة ظاهرة، مش مستخبية.",
    pf: "Profit factor", win: "نسبة الكسب", trades: "صفقات", sharpe: "Sharpe ‎2024+", high: "خطورة عالية", watch: "شوفها شغالة",
    names: { trend_daily: "ترند يومي", momentum_ls: "مومنتم لونج/شورت", listing_short: "شورت العملات الجديدة", ratio_trend: "ترند النسبة بين العملات" },
    desc: { trend_daily: "لونج على العملات اللي في ترند صاعد، وخروج لما الترند يقف.", momentum_ls: "لونج أقوى 5 وشورت أضعف 5 — كل أسبوع.", listing_short: "شورت العملة الجديدة بعد ما الهوجة تهدى.", ratio_trend: "لونج/شورت على أزواج أكبر 7 عملات." },
    note: (from: string, to: string, n: number) => `Backtest على ${n} عقد على Binance، من ${from} لحد ${to}، بعد الرسوم والـ funding. النتايج اللي فاتت مش ضمان لأي نتيجة جاية.`,
  },
  proof: {
    eyebrow: "الإثبات المباشر", title: "الحساب الحقيقي جنب الباكتست بتاعه.", sub: "بيتحدث من الحساب الحقيقي نفسه. لو الأرقام الحقيقية بعدت عن الباكتست، هتشوفها هنا الأول.",
    measure: "المقياس", real: "الحساب الحقيقي", backtest: "الباكتست",
    rows: { fees: "الرسوم لكل تنفيذ", closed: "صفقات مقفولة", win: "نسبة الكسب", pf: "Profit factor", edge: "الميزة صامدة لحد" },
    feesReal: "0.050%", wait: (n: number, of: number) => `بعد ${of} صفقة (${n}/${of})`, edgeBt: "≈0.7% تكلفة لكل تنفيذ",
    sideBadge: "صادقين بالتصميم", sideText: "العينة الصغيرة بتكدب. بنكتب العدد جنب كل رقم، ومش بنسمي حاجة نتيجة قبل 30 صفقة مقفولة.", sideCta: "افتح الصفحة المباشرة",
  },
  pricing: {
    eyebrow: "الباقات", title: "ابدأ مجانًا، وكبّر لما تحب.", sub: "كل باقة بتتابع البوتات مباشر. الباقات بتفتح Backtest أطول واستراتيجيات أكتر.",
    per: "/ شهريًا", popular: "الأكثر اختيارًا", redirect: "جاري التحويل للدفع…", error: "خطأ في الدفع",
    cta: { free: "ابدأ مجانًا", starter: "اختار Starter", pro: "اختار Pro", elite: "اختار Elite" },
    features: {
      free: ["Backtest الترند اليومي · لحد 7 أيام", "صفقات الاختبار وحاسبة راس المال", "متابعة كل البوتات مباشر (Paper)"],
      starter: ["+ المومنتم · لحد 30 يوم", "صفقات الاختبار والحاسبة للاتنين", "متابعة كل البوتات مباشر (Paper)"],
      pro: ["+ شورت العملات الجديدة · لحد 90 يوم", "صفقات الاختبار والحاسبة للتلاتة", "متابعة كل البوتات مباشر (Paper)"],
      elite: ["الـ 4 + ترند النسبة (High Risk)", "Backtest من غير حد للمدة", "متابعة كل البوتات مباشر (Paper)"],
    },
    note: ["الباقات بتفتح الـ Backtest وصفقات الاختبار وحاسبة راس المال. ", "لسه مابتشغّلش بوتات على حسابك في Binance", " — متابعة البوتات مباشر مفتوحة للكل. الاشتراك شهري، تلغيه في أي وقت، ومفيش استرجاع فلوس — "],
    terms: "الشروط والمخاطر",
  },
  faq: {
    eyebrow: "أسئلة", title: "إجابات مباشرة.",
    items: [
      ["هل البوت بيضمن ربح؟", "لأ. الأرقام هنا اختبارات على بيانات فاتت وحساب حقيقي صغير. تداول العملات بالرافعة عالي المخاطرة، وممكن تخسر جزء من فلوسك أو كلها."],
      ["لازم فلوس حقيقية علشان أجرّب؟", "لأ. الـ Backtest والمحفظة التجريبية بفلوس وهمية، والباقة المجانية مش محتاجة كارت."],
      ["الأرقام جاية منين؟", "من كل عقود USDT-M على Binance من 2019، والعملات اللي اتشالت كمان، والعملات بتتختار بالفوليوم وقتها، بعد الرسوم والـ funding الحقيقي. الإعدادات اتختارت على قبل 2024، وأرقام 2024+ هي الفترة اللي ما اتستخدمتش في اختيارها."],
      ["هل الباقة هتتداول على حسابي في Binance؟", "لسه لأ. الباقات بتفتح أدوات البحث. وصفحة الفلوس الحقيقية بتعرض حساب صاحب الموقع نفسه، للشفافية."],
      ["الدفع آمن؟ وأقدر ألغي؟", "الدفع عن طريق Stripe وبيانات الكارت مش بتعدّي على سيرفراتنا. وتلغي في أي وقت من حسابك."],
    ],
  },
  cta: { title: "اتفرّج عليه بيتداول قبل ما تثق فيه.", sub: "الصفحة المباشرة عامة. من غير تسجيل.", live: "شوف البوت المباشر", start: "ابدأ مجانًا" },
  footer: { terms: "الشروط والمخاطر", live: "الصفحة المباشرة", backtest: "Backtest", risk: "تداول العقود بالرافعة عالي المخاطرة. الباكتست والنتايج الحقيقية اللي فاتت مش ضمان لأي نتيجة جاية. رقم أداة بحث ومتابعة، مش نصيحة استثمارية." },
}

export const LANDING: Record<Locale, Dict> = { en, ar }
export type LandingDict = Dict

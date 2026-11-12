// the page's language: its fixed words in English, the bots' close reasons, the switch (split from index.html on 2026-11-11; classic scripts, loaded in order, one shared scope)
// Live page: bot data (status.json) every 15 s + prices streamed from Bybit's public WebSocket,
// so open-trade prices and profit move second by second without reloading.
const $ = id => document.getElementById(id)
let L = document.documentElement.lang === "en" ? "en" : "ar"
const tx = (ar, en) => L === "en" ? en : ar          // one string, in the page's language
// The fixed words of the page: the markup stays Arabic, and English swaps each text by its Arabic.
const EN = {
  "بيحمّل…": "Loading…", "بوت الترند اليومي — مباشر": "Daily Trend bot — live",
  "بيشتري لما العملة تكون أعلى من سعرها من 20 و60 و120 يوم في 2 من 3، وبيبيع لما الترند يقف. لونج بس، وحجم الصفقة بيصغر لما السوق يهيج. الصفقات دي": "It buys when a coin is above its price of 20, 60 and 120 days ago on 2 of 3, and sells when the trend stops. Long only, and the trade size shrinks when the market gets wild. These trades are",
  "— فلوس وهمية، مفيش أوامر حقيقية.": "— play money, no real orders.",
  "الربح المحقق": "Realized", "ربح الصفقات المفتوحة": "Open P&L", "بالسعر اللحظي": "at the live price", "صفقات مفتوحة": "Open trades", "الإجمالي": "Total",
  "الصفقات المفتوحة": "Open trades", "العملة": "Coin", "الدخول": "Entry", "السعر الحالي": "Price now", "وقف الحماية": "Protective stop", "الهامش": "Margin",
  "الربح $": "P&L $", "على الهامش": "On margin", "من": "Since", "قائمة النهارده": "Today's list",
  "أعلى العملات فوليوم (متوسط 30 يوم) — ترند صاعد = ممكن تدخل": "Top coins by volume (30-day average) — uptrend = may enter",
  "صفقات اتقفلت": "Closed trades", "الخروج": "Exit", "السبب": "Reason", "الوقت": "Time", "لسه مفيش صفقات اتقفلت": "No trades closed yet",
  "شورت العملات الجديدة — تجربة Paper": "New Listing Short — Paper test",
  "بوت منفصل: بيعمل شورت على العملة الجديدة على Binance بعد 30 يوم من إدراجها، ويقفل بعد 90 يوم أو لو السعر طلع 40% فوق الدخول، وبحد أقصى 10 صفقات في نفس الوقت. فكرة من الأبحاث إن العملات الجديدة بتنزل بعد الهوجة — بنجربها Paper قبل أي قرار.": "A separate bot: it shorts a new Binance listing 30 days after launch, and closes after 90 days or if the price rises 40% above entry, at most 10 trades at once. The idea comes from research showing new coins fall after the hype — we test it on paper before any decision.",
  "ربح محقق": "Realized", "بالسعر اللحظي من Binance": "at the live Binance price", "شورت مفتوح": "Open shorts", "هامش $20 × 2 للصفقة": "$20 margin × 2 per trade",
  "الوقف": "Stop", "بيقفل في": "Closes on", "جاية": "Coming", "عملات اتدرجت قريب — الشورت بعد 30 يوم من الإدراج": "Recently listed coins — the short comes 30 days after listing",
  "اتقفلت": "Closed",
  "مومنتم: لونج الأقوى وشورت الأضعف — تجربة Paper": "Momentum: long the strongest, short the weakest — Paper test",
  "بوت تالت منفصل: كل أسبوع بيرتّب أعلى 50 عملة فوليوم على Binance حسب أدائها آخر أسبوعين، وبيعمل لونج على أقوى 5 وشورت على أضعف 5، ويقفلهم ويبدّل بعد أسبوع (وقف 40%). مبني على أبحاث الزخم بين العملات — بنجربه Paper قبل أي قرار.": "A third, separate bot: every week it ranks the top 50 Binance coins by volume on their last two weeks, goes long the strongest 5 and short the weakest 5, and swaps them after a week (40% stop). Built on cross-coin momentum research — we test it on paper before any decision.",
  "مفتوحة": "Open", "التبديل الجاي": "Next rebalance", "الاتجاه": "Side", "أداء أسبوعين": "2-week return",
  "Ratio trend بين أكبر العملات": "Ratio trend between the biggest coins",
  "Ratio trend من غير BTC/ETH": "Ratio trend without BTC/ETH",
  "Ratio trend من غير BTC/ETH + trailing 20%": "Ratio trend without BTC/ETH + 20% trailing",
  "Ratio trend بين أكبر العملات + trailing 20%": "Ratio trend between the biggest coins + 20% trailing",
  "نفس بوت الـ Ratio الأصلي (BTC وETH داخلين، 100$ هامش ×2 لكل رجل)، والفرق في الخروج بس: الزوج بيتقفل لو النسبة رجعت 20% من أحسن نقطة وصلتلها، ويفضل مقفول لحد ما الترند يتقلب. في الاختبار (research §35) كان التحسن هنا مش ثابت — شغالة Paper عشان نقارن الاتنين.": "The original ratio bot (BTC and ETH in, $100 margin x2 per leg), with one difference in the exit: a pair is closed when its ratio falls 20% from the best point it reached, and stays closed until the trend turns. In the test (research §35) the gain here was not steady — it runs on paper to compare the two.",
  "نفس بوت Ratio من غير BTC/ETH بالظبط، والفرق في الخروج بس: الزوج بيتقفل لو النسبة رجعت 20% من أحسن نقطة وصلتلها، ويفضل مقفول لحد ما الترند يتقلب. في الاختبار (research §35) قلّل التراجع شوية وحسّن الـ Sharpe شوية — شغالة Paper عشان نقارن الاتنين.": "Exactly the Ratio bot without BTC/ETH, with one difference in the exit: a pair is closed when its ratio falls 20% from the best point it reached, and stays closed until the trend turns. In the test (research §35) it lowered the drawdown a little and raised the Sharpe a little — it runs on paper to compare the two.",
  "نسخة تجريبية تانية: نفس القاعدة، بس BTC وETH مش داخلين — أعلى 7 عملات فوليوم بعدهم، و40$ هامش ×2 لكل رجل. في الاختبار (research §25) كانت أحسن من النسخة الأصلية، بس أقصى تراجعها حوالي 50 وحدة — شغالة Paper عشان نتابعها بس.": "A second experimental version: the same rule, but without BTC and ETH — the top 7 coins by volume after them, $40 margin x2 per leg. In the test (research §25) it did better than the original, but its worst drawdown was about 50 units — it runs on paper only, to watch it.",
  "بوت رابع تجريبي: كل الأزواج بين أعلى 7 عملات فوليوم على Binance (21 زوج). لو نسبة سعر العملتين فوق متوسط 50 يوم: لونج الأولى وشورت التانية، والعكس.": "A fourth, experimental bot: every pair among the top 7 Binance coins by volume (21 pairs). If the ratio of the two prices is above its 50-day average: long the first and short the second, and the other way round.",
  "مخاطرته عالية:": "High risk:",
  "في الاختبار العادل كان أقصى تراجع 795$ وقلّل نتيجة البوتات التلاتة لما اتضاف ليها — شغال Paper عشان نتابع أداءه بس.": "in the fair test its worst drawdown was $795, and adding it lowered the other three bots' result — it runs on paper only so we can follow it.",
  "ربح الأزواج المفتوحة": "Open pairs' P&L", "أزواج مفتوحة": "Open pairs", "لونج": "Long", "شورت": "Short", "دخول لونج": "Long entry", "دخول شورت": "Short entry",
  "الزوج (لونج / شورت)": "Pair (long / short)", "لسه مفيش أزواج اتقفلت": "No pairs closed yet",
  "بريك أوت التذبذب (Larry Williams) — تجربة Paper": "Volatility breakout (Larry Williams) — Paper test",
  "بوت خامس منفصل: كل يوم على أعلى 10 عملات فوليوم على Binance اللي قفلت فوق متوسط 20 يوم، بيشتري لو السعر طلع فوق افتتاح اليوم بـ 0.7 من مدى امبارح، ويقفل على افتتاح اليوم اللي بعده. من غير وقف خلال اليوم (اختبار الساعة بيّن إنه بيقلل الربح) — بس وقف أمان 40% قبل التصفية.": "A fifth, separate bot: every day, on the top 10 Binance coins by volume that closed above their 20-day average, it buys if the price rises above the day's open by 0.7 of yesterday's range, and closes at the next day's open. No intraday stop (the hourly test showed it lowers profit) — only a 40% safety stop before liquidation.",
  "مستني اختراق النهارده": "Waiting for today's breakout",
  "مومنتم يومي: سلة جديدة كل يوم — تجربة Paper": "Momentum daily: a new basket every day — paper test",
  "نفس ترتيب بوت المومنتم، بس كل يوم الساعة 00:00 UTC (2 الفجر بتوقيت مصر): بيرتّب أعلى 50 عملة فوليوم على Binance حسب أدائها آخر أسبوعين، لونج على أقوى 5 وشورت على أضعف 5 (وقف 40%، 100$ هامش ×2 لكل رجل). العملة اللي لسه في السلة بتفضل مفتوحة، واللي خرجت بتتقفل. في الباك تست (2019 → أكتوبر 2026): +3,035$ قصاد +2,200$ للأسبوعي.": "The momentum bot's ranking, but every day at 00:00 UTC: it ranks the top 50 by volume on Binance by their last 2 weeks' return, long the strongest 5 and short the weakest 5 (40% stop, $100 margin ×2 a leg). A coin still in the basket stays open; one that left is closed. Backtest (2019 → October 2026): +$3,035 against +$2,200 for the weekly bot.",
  "مومنتم يومي · هامش 7 — تجربة Paper": "Momentum daily · buffer 7 — paper test",
  "نفس بوت المومنتم اليومي بالظبط، والفرق إن العملة المفتوحة بتفضل في السلة طول ما هي من أقوى 7 (للونج) أو أضعف 7 (للشورت)، مش 5 بس. في الباك تست (research §37) أكبر هبوط بيقل من 578$ لـ 358$، والربح أقل 11%.": "The daily momentum bot exactly, except that an open coin stays in the basket while it is among the strongest 7 (longs) or the weakest 7 (shorts), not just 5. In the backtest (research §37) the worst drawdown falls from $578 to $358, for 11% less profit.",
  "عكس الأغلبية (نسبة لونج/شورت) — تجربة Paper": "Against the crowd (long/short ratio) — Paper test",
  "بوت منفصل من بحث الـ Open Interest (research §29): كل أربع على أعلى 20 عملة فوليوم على Binance، بيعمل لونج على أقل 3 عملات في نسبة لونج/شورت الحسابات (الأغلبية شورت) وشورت على أعلى 3 (الأغلبية لونج)، ويقفلهم ويبدّل بعد أسبوع (وقف 40%). في الاختبار كانت الفكرة الوحيدة اللي كسبت قبل 2024 وبعدها، ومش مرتبطة بالمومنتم — بس اتلقت بعد ما شفنا النتايج، فشغالة Paper عشان نتابعها بس.": "A separate bot from the open-interest research (research §29): every Wednesday, on the top 20 Binance coins by volume, it goes long the 3 with the lowest accounts' long/short ratio (the crowd is short) and short the 3 with the highest (the crowd is long), and rebalances after a week (40% stop). In the test it was the only idea that made money both before and after 2024, and it doesn't move with momentum — but it was found after looking at the results, so it runs on paper only, to watch it.",
  "نسبة لونج/شورت": "Long/short ratio",
  "المحافظ الثلاثة — تجربة Paper": "The three portfolios — Paper test",
  "من البحث (research §31): مومنتم + عكس الأغلبية، مومنتم + RSI-2، والثلاثة مع بعض. كل استراتيجية بوت Paper لوحده (كأنها حساب فرعي لوحدها، §32)، والمحفظة هي مجموع صفقاتهم، كل عملة بهامش $100 × 2، من الصفقات اللي اتفتحت من 9 نوفمبر. في الاختبار الثلاثة كانوا الأنعم، ومومنتم + عكس الأغلبية الأعلى ربح والأعلى تراجع.": "From the research (research §31): momentum + against the crowd, momentum + RSI-2, and all three. Each strategy is its own paper bot (as if on its own sub-account, §32), and a portfolio is the sum of their trades, every coin at $100 margin × 2, counting the trades opened from 9 November. In the test all three together were the smoothest, and momentum + against the crowd made the most and fell the most.",
  "المحفظة": "Portfolio", "صفقات اتقفلت": "Closed trades", "نسبة الكسب": "Win rate", "ربح المفتوح": "Open P&L", "أقصى تراجع": "Max drawdown", "هامش مفتوح": "Margin open",
  "RSI-2 شراء الهبوط (Larry Connors) — تجربة Paper": "RSI-2 buy the dip (Larry Connors) — Paper test",
  "بوت سادس منفصل: كل يوم على أعلى 10 عملات فوليوم فوق متوسط 200 يوم، بيشتري لما RSI-2 ينزل تحت 5 (هبوط حاد في ترند صاعد)، ويقفل أول ما يقفل يومي فوق متوسط 5 أيام أو بعد 10 أيام. وقف 40%.": "A sixth, separate bot: every day, on the top 10 coins by volume above their 200-day average, it buys when RSI-2 drops below 5 (a sharp dip in an uptrend), and closes at the first daily close above the 5-day average or after 10 days. 40% stop.",
  "أقرب عملات لإشارة": "Closest coins to a signal",
  "RSI-2 + فلتر BTC — تجربة Paper تانية": "RSI-2 + BTC filter — second Paper test",
  "نفس بوت RSI-2 بنفس الحجم، بس ما بيدخلش صفقة جديدة غير لما BTC يقفل فوق متوسط 200 يوم. في الاختبار (research §28) نسبة الكسب طلعت من 66% لـ 70% وأقصى تراجع نزل من 48 لـ 28 مارجن، بنفس العائد مقابل المخاطرة بعد 2024 وصفقات أقل — شغال Paper جنب الأصلي عشان نقارنهم.": "The same RSI-2 bot at the same size, but it opens a new trade only while BTC closes above its 200-day average. In the test (research §28) the win rate rose from 66% to 70% and the worst drawdown fell from 48 to 28 margins, with the same return for the risk after 2024 and fewer trades — it runs on paper next to the original so we can compare them.",
  "فلتر BTC · أقرب عملات": "BTC filter · closest coins",
  "اختراق الترند (Minervini / Darvas) — تجربة Paper": "Trend breakout (Minervini / Darvas) — Paper test",
  "بوت سابع منفصل: على أعلى 100 عملة فوليوم في ترند صاعد واضح (السعر فوق متوسط 50 فوق 150 فوق 200 يوم)، بيشتري لما القفل اليومي يكسر أعلى سعر في آخر 20 يوم، ويقفل أول قفل يومي تحت متوسط 20 يوم. وقف 40%. تجربة: في الاختبار زوّد الربح بس مش العائد مقابل المخاطرة، وبيكسب في سنين الصعود القوية بس.": "A seventh, separate bot: on the top 100 coins by volume in a clear uptrend (price above the 50-, over the 150-, over the 200-day average), it buys when the daily close breaks the highest price of the last 20 days, and closes at the first daily close below the 20-day average. 40% stop. A test: in the backtest it raised profit but not the return for the risk, and it only wins in strong bull years.",
  "أقرب عملات للاختراق": "Closest coins to a breakout",
  "نتايج Paper حيّة من البوت، مش نصيحة استثمارية ومش ضمان لأي ربح. اختبار الاستراتيجية التاريخي في": "Live paper results from the bot, not investment advice and no guarantee of any profit. The strategies' historical test is in",
  ". الأسعار لحظية من Bybit (الترند) وBinance (الشورت والمومنتم والـ ratio)، وبيانات البوتات بتتحدث كل 15 ثانية.": ". Prices are live from Bybit (the trend) and Binance (the short, momentum and ratio), and the bots' data refreshes every 15 seconds.",
}
// the bots write their close reasons in Arabic (bot.py)
const REASONS_EN = {"تبديل أسبوعي": "Weekly rebalance", "تبديل يومي": "Daily rebalance", "الترند وقف": "Trend stopped", "الترند اتقلب": "Trend flipped", "اشارة عكسية": "Opposite signal",
  "اشارة عكسية قوية": "Strong opposite signal", "قفل يدوي من Binance": "Closed by hand on Binance", "اتقفلت يدوي من Binance": "Closed by hand on Binance",
  "قفل يدوي من الموقع": "Closed by hand from the site", "الوقف اترفض — قفل فوري": "Stop rejected — closed at once", "خروج افتتاح اليوم": "Exit at the day's open",
  "وقف خسارة": "Stop loss", SL: "Stop loss", TP: "Target",
  "قفل يدوي (أدمن)": "Closed by hand (admin)", "قفل فوق متوسط 5 يوم": "Closed above the 5-day average"}
// "وقف 0.0346" = the stop hit at that price
const rsn = r => { if(L !== "en") return r; if(REASONS_EN[r]) return REASONS_EN[r]; const m = /^وقف (.+)$/.exec(r || ""); return m ? `Stop at ${m[1]}` : r }
const norm = t => t.replace(/\s+/g, " ").trim()
const FIXED = []        // [text node, its Arabic] — every fixed text on the page
{ const w = document.createTreeWalker(document.querySelector(".wrap"), NodeFilter.SHOW_TEXT)
  for(let n; (n = w.nextNode());) if(/[\u0600-\u06ff]/.test(n.nodeValue)) FIXED.push([n, n.nodeValue]) }
function applyWords(){
  for(const [n, ar] of FIXED){ const k = norm(ar); n.nodeValue = L === "en" && EN[k] ? ar.match(/^\s*/)[0] + EN[k] + ar.match(/\s*$/)[0] : ar }
  document.title = tx("بوت رقم — مباشر", "RAQM — live paper bots")
  document.querySelector('meta[name="description"]').content = tx("صفقات بوت رقم مباشرة: ترند يومي على أعلى العملات فوليوم — Paper", "RAQM's paper bots live: daily trend on the top coins by volume, and more — paper money")
  $("langBtn").textContent = tx("English", "العربية")
  $("langBtn").lang = L === "ar" ? "en" : "ar"
  $("themeBtn").setAttribute("aria-label", document.documentElement.dataset.theme === "dark" ? tx("الوضع الفاتح", "Switch to light") : tx("الوضع الغامق", "Switch to dark"))
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))
const usd = (v, sign = true) => v == null ? "—" : `${sign && v > 0 ? "+" : ""}${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
const px = v => v == null ? "—" : Number(v).toLocaleString("en-US", {maximumSignificantDigits: 6})
const tone = v => v > 0 ? "profit" : v < 0 ? "loss" : ""
const ago = iso => {
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000))
  if(L === "en") return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`
  return s < 60 ? `من ${s} ثانية` : s < 3600 ? `من ${Math.round(s / 60)} دقيقة` : s < 86400 ? `من ${Math.round(s / 3600)} ساعة` : `من ${Math.round(s / 86400)} يوم`
}
const day = iso => iso ? new Date(iso).toLocaleDateString("en-GB", {day: "2-digit", month: "short", timeZone: "UTC"}) : "—"
const wsSym = sym => sym.replace("/", "").replace(":USDT", "")   // "BTC/USDT" -> "BTCUSDT"


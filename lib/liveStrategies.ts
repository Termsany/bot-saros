// The strategies a user can run with real money (backend/app/user_bots.py LIVE_STRATEGIES; owner, 2026-11-07).
export const LIVE_STRATEGIES = ["momentum_ls", "rsi2_pullback"] as const
export const LIVE_SHORT: Record<string, string> = { momentum_ls: "momentum", rsi2_pullback: "RSI-2" }
export const LIVE_NAMES: Record<"ar" | "en", Record<string, [string, string]>> = {
  ar: { momentum_ls: ["Momentum", "سلة 5 لونج + 5 شورت · سلة جديدة كل يوم 00:00 UTC، والعملة اللي لسه فيها بتفضل مفتوحة"],
        rsi2_pullback: ["RSI-2 + فلتر BTC", "شراء الهبوط الحاد في ترند صاعد · لحد 10 صفقات · مفيش دخول و BTC تحت متوسط 200 يوم"] },
  en: { momentum_ls: ["Momentum", "5 long + 5 short basket · a new basket every day at 00:00 UTC; a coin still in it stays open"],
        rsi2_pullback: ["RSI-2 + BTC filter", "Buys sharp dips in an uptrend · up to 10 trades · no entries while BTC is below its 200-day average"] },
}
/** "momentum", "RSI-2" or "momentum + RSI-2" */
export const liveShort = (s: string[]) => s.map(x => LIVE_SHORT[x] || x).join(" + ")

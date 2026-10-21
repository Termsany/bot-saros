// Browser daily trend (lib/trend-daily.ts) vs strategies_trend.py, trade by trade.
// Run `python research/trend_parity_export.py` first, then `node research/trend_parity.ts`. Exits 1 on any difference.
import { readFileSync, readdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { runTrendDaily } from "../lib/trend-daily.ts"

const cache = fileURLToPath(new URL("./.cache/", import.meta.url))
const files = readdirSync(cache).filter(f => f.startsWith("trendparity_")).sort()
if(!files.length){ console.error("no trendparity_*.json — run python research/trend_parity_export.py"); process.exit(1) }
let total = 0, bad = 0
for(const f of files){
  const { candles, funding, runs } = JSON.parse(readFileSync(cache + f, "utf8"))
  for(const [key, trades] of Object.entries<any[]>(runs)){
    const js = runTrendDaily(candles, key.endsWith("f") ? funding : undefined, 20, parseInt(key))
    total += trades.length
    if(js.length !== trades.length){ bad++; console.log(`${f} ${key}: python ${trades.length} trades, browser ${js.length}`); continue }
    trades.forEach((p, i) => {
      const t = js[i]
      const same = p.entry_ts === t.entry_ts && p.exit_ts === t.exit_ts && p.reason === t.reason
        && Math.abs(p.entry - t.entry) < 1e-9 && Math.abs(p.exit - t.exit) < 1e-9 && Math.abs(p.pnl - t.pnl) < 1e-9
      if(!same){ bad++; console.log(`${f} ${key} trade ${i}: python ${JSON.stringify(p)} browser ${JSON.stringify(t)}`) }
    })
  }
}
console.log(`trend daily: ${total} trades, ${bad} differences`)
process.exit(bad ? 1 : 0)

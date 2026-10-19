// Browser Wave Flats (lib/wave-flats.ts) vs strategies_wave.py, trade by trade.
// Run `python research/wave_parity_export.py` first, then `node research/wave_parity.ts`. Exits 1 on any difference.
import { readFileSync, readdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { runWaveFlats } from "../lib/wave-flats.ts"

const cache = fileURLToPath(new URL("./.cache/", import.meta.url))
const files = readdirSync(cache).filter(f => f.startsWith("wave_") && f.endsWith(".json")).sort()
if(!files.length){ console.error("no wave_*.json — run python research/wave_parity_export.py"); process.exit(1) }
let total = 0, bad = 0
for(const f of files){
  const { tf, candles, trades } = JSON.parse(readFileSync(cache + f, "utf8"))
  const js = runWaveFlats(candles, tf)
  total += trades.length
  if(js.length !== trades.length){ bad++; console.log(`${f}: python ${trades.length} trades, browser ${js.length}`); continue }
  trades.forEach((p: any, i: number) => {
    const t = js[i]
    const same = p.entry_ts === t.entry_ts && p.exit_ts === t.exit_ts && p.side === t.side && p.kind === t.kind && p.reason === t.reason
      && Math.abs(p.entry - t.entry) < 1e-9 && Math.abs(p.exit - t.exit) < 1e-9 && Math.abs(p.pnl - t.pnl) < 1e-9
    if(!same){ bad++; console.log(`${f} trade ${i}: python ${JSON.stringify(p)} browser ${JSON.stringify(t)}`) }
  })
}
console.log(`wave flats: ${total} trades in ${files.length} sets, ${bad} differences`)
process.exit(bad ? 1 : 0)

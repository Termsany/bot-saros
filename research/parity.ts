// Browser engine (lib/strategy-engine.ts) vs the Python bot: every signal on every candle, then trades and PnL.
// Run `python research/parity_export.py` first, then `node research/parity.ts`. Exits 1 on any difference.
import { readFileSync, readdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { runEngine, scoresAt, STRATEGY_IDS, type Strategy } from "../lib/strategy-engine.ts"

const cache = fileURLToPath(new URL("./.cache/", import.meta.url))
const files = readdirSync(cache).filter(f => f.startsWith("parity_")).sort()
if(!files.length){ console.error("no parity_*.json — run python research/parity_export.py"); process.exit(1) }
let failures = 0

const diff: Record<string, { n: number, bars: number, example?: string }> = {}
for(const f of files){
  const { candles, scores } = JSON.parse(readFileSync(cache + f, "utf8"))
  for(let i = 60; i < candles.length; i++){
    const js = scoresAt(candles, i)
    for(const k of STRATEGY_IDS){
      const py = scores[i][k] ?? NaN, t = js[k] ?? NaN, d = (Number.isNaN(py) && Number.isNaN(t)) ? 0 : Math.abs(py - t)
      const r = (diff[k] ??= { n: 0, bars: 0 }); r.bars++
      if(!(d < 1e-9)){ r.n++; r.example ??= `${f} candle ${i}: python ${py} browser ${t}` }
    }
  }
}
for(const [k, r] of Object.entries(diff)){
  console.log(`signals ${k.padEnd(11)} ${r.n ? `${r.n}/${r.bars} differ — ${r.example}` : `${r.bars} candles ✓`}`)
  failures += r.n
}

const ref = JSON.parse(readFileSync(cache + "engine_ref.json", "utf8"))
let ok = 0
for(const [key, r] of Object.entries<{ n: number, pnl: number }>(ref)){
  const [tag, combo] = key.split("|")
  const { candles } = JSON.parse(readFileSync(cache + `parity_${tag}.json`, "utf8"))
  const t = runEngine(candles, combo.split("+") as Strategy[], 20, 5)
  const pnl = t.reduce((s, x) => s + x.pnl, 0)
  if(t.length === r.n && Math.abs(pnl - r.pnl) < 1e-6) ok++
  else { failures++; console.log(`trades  ${key}: python ${r.n} trades ${r.pnl.toFixed(6)} | browser ${t.length} trades ${pnl.toFixed(6)}`) }
}
console.log(`trades  ${ok}/${Object.keys(ref).length} runs match`)
process.exit(failures ? 1 : 0)

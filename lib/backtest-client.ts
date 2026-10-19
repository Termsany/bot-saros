// Pure browser backtest engine — mirrors backtest.py
// Fetches Bybit -> OKX -> Binance, scores 15 strategies, simulates LONG/SHORT

type Candle = { ts: number; open: number; high: number; low: number; close: number; vol: number }
type Trade = { entry_ts: number; exit_ts: number; side: "long"|"short"; entry: number; exit: number; qty: number; pnl: number; reason: string }

function toBybitInterval(tf: string){ const m: Record<string,string> = { "1m":"1","5m":"5","15m":"15","1h":"60","4h":"240","1d":"D" }; return m[tf]||"60" }

export async function fetchCandles(symbol: string, timeframe: string, limit=300, from?: string, to?: string): Promise<Candle[]>{
  const sym = symbol.replace("/","")
  const bybitInterval = toBybitInterval(timeframe)

  // If from/to given, compute limit from date range (cap 300)
  let effLimit = limit
  if(from || to){
    const fromMs = from ? new Date(from).getTime() : 0
    const toMs = to ? new Date(to).getTime() + 24*3600*1000 : Date.now()
    const tfMs: Record<string,number> = { "15m":15*60000, "1h":3600000, "4h":14400000, "1d":86400000 }
    const ms = tfMs[timeframe] || 3600000
    effLimit = Math.min(300, Math.max(50, Math.ceil((toMs - fromMs)/ms)))
  }

  // Try Bybit
  try{
    const r = await fetch(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${sym}&interval=${bybitInterval}&limit=${effLimit}`)
    if(r.ok){
      const j = await r.json()
      const list = j?.result?.list
      if(Array.isArray(list) && list.length){
        const sorted = [...list].reverse()
        return sorted.map((k:any)=> ({ ts: Number(k[0]), open:+k[1], high:+k[2], low:+k[3], close:+k[4], vol:+k[5] }))
      }
    }
  }catch{}
  // OKX
  try{
    const okxTf = timeframe==="1d"?"1D":timeframe
    const r = await fetch(`https://www.okx.com/api/v5/market/candles?instId=${sym.replace("USDT","-USDT")}&bar=${okxTf}&limit=${effLimit}`)
    if(r.ok){
      const j = await r.json()
      const data = j?.data
      if(Array.isArray(data) && data.length){
        const sorted = [...data].reverse()
        return sorted.map((k:any)=> ({ ts: Number(k[0]), open:+k[1], high:+k[2], low:+k[3], close:+k[4], vol:+k[5] }))
      }
    }
  }catch{}
  // Binance
  try{
    const r = await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${timeframe}&limit=${effLimit}`)
    if(r.ok){
      const raw = await r.json()
      if(Array.isArray(raw) && raw.length){
        return raw.map((k:any)=> ({ ts: Number(k[0]), open:+k[1], high:+k[2], low:+k[3], close:+k[4], vol:+k[5] }))
      }
    }
  }catch{}
  return []
}

// ── Indicators (simplified, browser-friendly) ──
function sma(arr: number[], period: number, idx: number){
  if(idx < period-1) return NaN
  let s=0; for(let i=idx-period+1;i<=idx;i++) s+=arr[i]
  return s/period
}
function ema(arr: number[], period: number): number[]{
  const out: number[] = []; let k=2/(period+1)
  for(let i=0;i<arr.length;i++){
    if(i===0) out.push(arr[0])
    else out.push(arr[i]*k + out[i-1]*(1-k))
  }
  return out
}
function rsi(close: number[], period=14): number[]{
  const out: number[] = []
  let gains=0, losses=0
  for(let i=0;i<close.length;i++){
    if(i===0){ out.push(50); continue }
    const d = close[i]-close[i-1]
    const gain = d>0?d:0, loss = d<0?-d:0
    if(i < period){ gains+=gain; losses+=loss; out.push(50); continue }
    if(i===period){ gains/=period; losses/=period } else { gains=(gains*(period-1)+gain)/period; losses=(losses*(period-1)+loss)/period }
    const rs = losses===0 ? 100 : gains/losses
    out.push(100 - 100/(1+rs))
  }
  return out
}

// Strategy scorers — each returns -1 to +1
function scoreRSI(close: number[], idx: number): number{
  const r = rsi(close)[idx]
  if(r<30) return 0.8
  if(r>70) return -0.8
  if(r<40) return 0.3
  if(r>60) return -0.3
  return 0
}
function scoreClassical(close: number[], idx: number): number{
  if(idx<50) return 0
  const s20 = sma(close,20,idx), s50=sma(close,50,idx), price=close[idx]
  let sc=0
  if(price>s20 && s20>s50) sc+=0.6
  else if(price<s20 && s20<s50) sc-=0.6
  return Math.max(-1,Math.min(1,sc))
}
function scoreIchimoku(high: number[], low: number[], close: number[], idx: number): number{
  if(idx<52) return 0
  // Simplified: Tenkan(9) vs Kijun(26) + price vs cloud
  const tenkan = (Math.max(...high.slice(idx-8,idx+1)) + Math.min(...low.slice(idx-8,idx+1)))/2
  const kijun = (Math.max(...high.slice(idx-25,idx+1)) + Math.min(...low.slice(idx-25,idx+1)))/2
  let sc=0
  if(close[idx] > tenkan && tenkan > kijun) sc+=0.7
  else if(close[idx] < tenkan && tenkan < kijun) sc-=0.7
  return sc
}
function scoreMACD(close: number[], idx: number): number{
  if(idx<26) return 0
  const e12=ema(close,12), e26=ema(close,26)
  const macd = e12[idx]-e26[idx]
  const prev = e12[idx-1]-e26[idx-1]
  if(macd>0 && prev<=0) return 0.5
  if(macd<0 && prev>=0) return -0.5
  return macd>0 ? 0.2 : -0.2
}
function scoreBollinger(close: number[], idx: number): number{
  if(idx<20) return 0
  const m = sma(close,20,idx)
  let sum=0; for(let i=idx-19;i<=idx;i++) sum+=(close[i]-m)**2
  const std = Math.sqrt(sum/20)
  const upper=m+2*std, lower=m-2*std
  if(close[idx] > upper) return -0.6
  if(close[idx] < lower) return 0.6
  return 0
}

const SCORERS: Record<string, (c:number[],h:number[],l:number[],v:number[], idx:number)=>number> = {
  rsi_macd: (c,h,l,v,i)=> (scoreRSI(c,i)+scoreMACD(c,i))/2,
  classical: (c,h,l,v,i)=> scoreClassical(c,i),
  ichimoku: (c,h,l,v,i)=> scoreIchimoku(h,l,c,i),
  bollinger: (c,h,l,v,i)=> scoreBollinger(c,i),
  // Others neutral for now — ICT is our hero, map others to RSI proxy
  ict: (c,h,l,v,i)=> scoreRSI(c,i)*0.7 + scoreClassical(c,i)*0.3,
  smc: (c,h,l,v,i)=> scoreClassical(c,i)*0.8,
  vwap: (c,h,l,v,i)=> scoreClassical(c,i)*0.6,
  supertrend: (c,h,l,v,i)=> scoreIchimoku(h,l,c,i)*0.8,
  harmonic: (c,h,l,v,i)=> scoreRSI(c,i)*0.5,
  dow: (c,h,l,v,i)=> scoreClassical(c,i)*0.5,
  gann: (c,h,l,v,i)=> 0,
  elliott: (c,h,l,v,i)=> scoreClassical(c,i)*0.4,
  sr: (c,h,l,v,i)=> scoreBollinger(c,i)*0.7,
  heikin: (c,h,l,v,i)=> scoreClassical(c,i)*0.5,
  ai: (c,h,l,v,i)=> scoreRSI(c,i)*0.3 + scoreClassical(c,i)*0.3,
}

const WEIGHTS: Record<string,number> = {
  rsi_macd:0.12, classical:0.05, ichimoku:0.10, bollinger:0.07, ict:0.15, smc:0.10, vwap:0.07,
  supertrend:0.07, harmonic:0.05, dow:0.05, gann:0.05, elliott:0.08, sr:0.05, heikin:0.05, ai:0.04
}

export async function runBacktestClient(opts: {
  symbol: string; timeframe: string; limit?: number; from?: string; to?: string;
  strategies: string[]; amount: number; leverage: number;
}){
  const candles = await fetchCandles(opts.symbol, opts.timeframe, opts.limit||300, opts.from, opts.to)
  if(!candles.length) return { ok:false, error: "No candles — Bybit/OKX/Binance all failed" }
  if(candles.length < 60) return { ok:false, error: `Not enough candles: ${candles.length} (need 60)` }

  const close = candles.map(c=>c.close)
  const high = candles.map(c=>c.high)
  const low = candles.map(c=>c.low)
  const vol = candles.map(c=>c.vol)

  const enabled = opts.strategies
  const wsum = enabled.reduce((s,k)=> s + (WEIGHTS[k]||0), 0) || 1

  const trades: Trade[] = []
  let position: { side:"long"|"short"; entry:number; qty:number; sl:number; tp:number; ts: number; breakeven: boolean } | null = null
  const fee = 0.0004
  let wins=0, losses=0
  const equity: number[] = [0]

  for(let i=60; i<candles.length; i++){
    const price = close[i]
    const ts = candles[i].ts
    // total score
    let total=0
    for(const k of enabled){
      const fn = SCORERS[k]
      if(fn) total += (fn(close,high,low,vol,i) * (WEIGHTS[k]||0)) / wsum
    }

    // SL/TP check
    if(position){
      const sl=position.sl, tp=position.tp
      let hit=false, exitPrice=price, reason=""
      if(position.side==="long"){
        if(low[i] <= sl){ hit=true; exitPrice=sl; reason="SL" }
        else if(high[i] >= tp){ hit=true; exitPrice=tp; reason="TP" }
        else if(total < -0.35){ hit=true; reason="reverse" }
      } else {
        if(high[i] >= sl){ hit=true; exitPrice=sl; reason="SL" }
        else if(low[i] <= tp){ hit=true; exitPrice=tp; reason="TP" }
        else if(total > 0.35){ hit=true; reason="reverse" }
      }
      if(hit){
        const qty = position.qty
        let pnl = position.side==="long" ? (exitPrice - position.entry)*qty : (position.entry - exitPrice)*qty
        pnl -= (position.entry*qty + exitPrice*qty)*fee
        trades.push({ entry_ts: position.ts, exit_ts: ts, side: position.side, entry: position.entry, exit: exitPrice, qty, pnl, reason })
        if(pnl>0) wins++; else losses++
        equity.push((equity[equity.length-1]||0) + pnl)
        position = null
        continue
      }
      // ♻️ Breakeven 50% — applied after this bar's SL/TP check, so the new SL counts from the next bar
      if(!position.breakeven){
        const trig = position.entry + (position.tp - position.entry)*0.5
        const hitBe = position.side==="long" ? price >= trig : price <= trig
        if(hitBe){
          const off = 0.001
          const beSl = position.side==="long" ? position.entry*(1+off) : position.entry*(1-off)
          if(position.side==="long" && beSl > position.sl) position.sl = beSl
          if(position.side==="short" && beSl < position.sl) position.sl = beSl
          position.breakeven = true
        }
      }
    }

    if(!position){
      let side: "long"|"short"|null = null
      if(total > 0.15) side="long"
      else if(total < -0.15) side="short"
      if(side){
        const notional = opts.amount * opts.leverage
        const qty = notional / price
        const sl = side==="long" ? price*0.97 : price*1.03
        const tp = side==="long" ? price*1.06 : price*0.94
        position = { side, entry: price, qty, sl, tp, ts, breakeven: false }
      }
    }
    equity.push(equity[equity.length-1]||0)
  }

  if(position){
    const price = close[close.length-1]
    let pnl = position.side==="long" ? (price - position.entry)*position.qty : (position.entry - price)*position.qty
    pnl -= (position.entry*position.qty + price*position.qty)*fee
    trades.push({ entry_ts: position.ts, exit_ts: candles[candles.length-1].ts, side: position.side, entry: position.entry, exit: price, qty: position.qty, pnl, reason: "close" })
    if(pnl>0) wins++; else losses++
  }

  const totalPnl = trades.reduce((s,t)=>s+t.pnl, 0)
  const winRate = trades.length ? wins/trades.length*100 : 0
  const avgWin = trades.filter(t=>t.pnl>0).reduce((s,t)=>s+t.pnl,0) / Math.max(1, wins) || 0
  const avgLoss = trades.filter(t=>t.pnl<0).reduce((s,t)=>s+t.pnl,0) / Math.max(1, losses) || 0
  const sumWin = trades.filter(t=>t.pnl>0).reduce((s,t)=>s+t.pnl,0)
  const sumLoss = Math.abs(trades.filter(t=>t.pnl<0).reduce((s,t)=>s+t.pnl,0))
  const pf = sumLoss ? sumWin/sumLoss : sumWin ? 99 : 0
  let peak=0, maxDD=0
  for(const v of equity){ if(v>peak) peak=v; maxDD=Math.max(maxDD, peak-v) }

  // Build chart data for report: price line + equity
  return {
    ok: true,
    data: {
      symbol: opts.symbol, timeframe: opts.timeframe,
      stats: { total: trades.length, wins, losses, win_rate: winRate, pnl: totalPnl, avg_win: avgWin, avg_loss: avgLoss, profit_factor: pf, max_dd: maxDD },
      trades: trades.map(t=> ({ ...t, entry_ts: new Date(t.entry_ts).toISOString(), exit_ts: new Date(t.exit_ts).toISOString() })),
      candles: candles.length,
    }
  }
}

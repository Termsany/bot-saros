// the daily trend bot (status.json) and Bybit's live price stream (split from index.html on 2026-11-11; classic scripts, loaded in order, one shared scope)
let D = null                 // last status.json
const live = {}              // BTCUSDT -> last price from the stream
const prev = {}              // last rendered price, for the flash
let ws = null, wsOk = false, subs = new Set(), dirty = false

const priceOf = (sym, fallback) => live[wsSym(sym)] ?? fallback

function render(){
  if(!D) return
  const d = D
  const stale = (Date.now() - Date.parse(d.updated)) / 60000 > Math.max(15, (d.poll_seconds || 60) / 60 * 3)
  $("live").classList.toggle("stale", stale)
  $("updated").textContent = stale ? tx(`آخر تحديث للبوت ${ago(d.updated)} — البوت ممكن يكون واقف`, `The bot last updated ${ago(d.updated)} — it may be stopped`)
    : tx(`${wsOk ? "أسعار لحظية" : "مباشر"} · آخر دورة للبوت ${ago(d.updated)}`, `${wsOk ? "Live prices" : "Live"} · bot's last cycle ${ago(d.updated)}`)

  const pos = d.positions.map(p => {
    const price = priceOf(p.symbol, p.price)
    const pnl = (price - p.entry) * p.qty * (p.side === "short" ? -1 : 1)
    return { ...p, price, pnl, pnl_pct: p.margin ? pnl / p.margin * 100 : null }
  })
  const s = d.stats, unreal = pos.reduce((a, p) => a + p.pnl, 0), total = s.realized + unreal
  $("realized").innerHTML = `<span class="${tone(s.realized)}">${usd(s.realized)}</span>`
  $("wl").textContent = tx(`${s.closed} صفقة اتقفلت · ${s.wins} كسبانة / ${s.losses} خسرانة`, `${s.closed} closed · ${s.wins} won / ${s.losses} lost`)
  $("unrealized").innerHTML = `<span class="${tone(unreal)}">${usd(unreal)}</span>`
  $("open").textContent = s.open
  const known = pos.filter(p => p.margin != null)
  $("marginUsed").textContent = pos.length && !known.length ? tx("الهامش مش معروف للصفقات دي", "margin not known for these trades")
    : `${tx("هامش مستخدم", "margin in use")} $${known.reduce((a, p) => a + p.margin, 0).toFixed(0)}`
  $("total").innerHTML = `<span class="${tone(total)}">${usd(total)}</span>`
  $("since").textContent = d.started ? tx(`البوت شغال ${ago(d.started)}`, `started ${ago(d.started)}`) : ""

  $("openCount").textContent = pos.length ? tx(`${pos.length} صفقة`, `${pos.length} trades`) : ""
  $("positions").innerHTML = pos.length ? pos.map(p => {
      const k = wsSym(p.symbol), flash = prev[k] == null || prev[k] === p.price ? "" : p.price > prev[k] ? "up" : "down"
      prev[k] = p.price
      return `<tr>
      <td class="coin">${esc(p.symbol.replace("/USDT", ""))}</td>
      <td class="num mono">${px(p.entry)}</td>
      <td class="num mono ${flash}">${px(p.price)}</td>
      <td class="num mono" style="color:var(--faint)">${px(p.sl)}</td>
      <td class="num mono">${p.margin == null ? "—" : "$" + Number(p.margin).toFixed(2)}</td>
      <td class="num mono ${tone(p.pnl)}">${usd(p.pnl)}</td>
      <td class="num mono ${tone(p.pnl_pct)}">${p.pnl_pct == null ? "—" : (p.pnl_pct > 0 ? "+" : "") + p.pnl_pct.toFixed(1) + "%"}</td>
      <td class="mono" style="color:var(--muted)">${day(p.opened)}</td></tr>`}).join("")
    : `<tr><td colspan="8" class="empty">${tx("مفيش صفقات مفتوحة — البوت مستني ترند صاعد", "No open trades — the bot is waiting for an uptrend")}</td></tr>`

  $("signals").innerHTML = (d.signals || []).filter(x => x.in_list).map(x => `<div class="sig">
      <span><b>${esc(x.symbol.replace("/USDT", ""))}</b> <span class="mono" style="color:var(--faint);font-size:11px">${px(priceOf(x.symbol, x.price))}</span></span>
      <span class="s ${x.on ? "on" : "off"}">${x.on ? tx("ترند صاعد", "Uptrend") : tx("مستني", "Waiting")}</span></div>`).join("")
    || `<div class="empty">${tx("بيحمّل…", "Loading…")}</div>`

  $("histCount").textContent = d.history.length ? `${tx("آخر", "last")} ${d.history.length}` : ""
  if(d.history.length) $("history").innerHTML = d.history.slice(0, 100).map(h => `<tr>
      <td class="coin">${esc(h.symbol.replace("/USDT", ""))}</td>
      <td class="num mono">${px(h.entry)}</td>
      <td class="num mono">${px(h.exit)}</td>
      <td class="num mono ${tone(h.pnl)}">${usd(h.pnl)}</td>
      <td style="color:var(--muted)">${esc(rsn(h.reason))}</td>
      <td class="mono" style="color:var(--muted)">${day(h.time)}</td></tr>`).join("")
}

function renderSettings(d){
  $("settings").innerHTML = [
    `<span class="chip paper">${d.mode === "paper" ? tx("Paper — فلوس وهمية", "Paper — play money") : "LIVE"}</span>`,
    `<span class="chip">${tx("رافعة", "Leverage")} <b class="mono">x${esc(d.leverage)}</b></span>`,
    tx(`<span class="chip">هامش <b class="mono">$${esc(d.margin)}</b> للصفقة</span>`, `<span class="chip">Margin <b class="mono">$${esc(d.margin)}</b> per trade</span>`),
    d.universe_size ? tx(`<span class="chip">أعلى <b class="mono">${esc(d.universe_size)}</b> عملة فوليوم</span>`, `<span class="chip">Top <b class="mono">${esc(d.universe_size)}</b> coins by volume</span>`) : "",
    `<span class="chip">${tx("البوت بيفحص كل", "The bot checks every")} <b class="mono">${d.poll_seconds >= 60 ? Math.round(d.poll_seconds / 60) + tx(" دقيقة", " min") : d.poll_seconds + tx(" ثانية", " s")}</b></span>`,
  ].join("")
}

async function load(){
  try{
    const r = await fetch(`status.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0
    D = await r.json(); renderSettings(D); render(); subscribe()
  }catch{ if(!D){ $("updated").textContent = tx("مفيش بيانات لسه", "No data yet"); $("live").classList.add("stale") } }
}

// ── Bybit public ticker stream (linear USDT perpetuals) ──
function wanted(){
  if(!D) return new Set()
  return new Set([...D.positions.map(p => p.symbol), ...(D.signals || []).filter(x => x.in_list).map(x => x.symbol)].map(wsSym))
}
function subscribe(){
  if(!ws || ws.readyState !== 1) return
  const add = [...wanted()].filter(x => !subs.has(x))
  for(let i = 0; i < add.length; i += 10){   // Bybit: up to 10 topics per request
    ws.send(JSON.stringify({ op: "subscribe", args: add.slice(i, i + 10).map(x => `tickers.${x}`) }))
  }
  add.forEach(x => subs.add(x))
}
function connect(){
  ws = new WebSocket("wss://stream.bybit.com/v5/public/linear")
  let ping
  ws.onopen = () => { wsOk = true; subs = new Set(); subscribe(); ping = setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ op: "ping" })), 20000) }
  ws.onmessage = e => {
    const m = JSON.parse(e.data)
    if(m.topic && m.data && m.data.lastPrice){ live[m.data.symbol] = +m.data.lastPrice; dirty = true }
  }
  ws.onclose = () => { wsOk = false; clearInterval(ping); setTimeout(connect, 3000) }   // reconnect
  ws.onerror = () => ws.close()
}

applyWords()
load(); connect()
setInterval(load, 15000)                                            // bot data
setInterval(() => { if(dirty){ dirty = false; render() } }, 1000)   // prices: at most one redraw a second
setInterval(() => { if(!dirty) render() }, 10000)                   // keep "x seconds ago" fresh

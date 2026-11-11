// the other paper bots' sections: listing short, momentum, against the crowd, the portfolios, ratio, breakout, RSI-2, trend breakout (split from index.html on 2026-11-11; classic scripts, loaded in order, one shared scope)
// ── new-listing short (separate paper bot): listing.json every 15 s + Binance futures prices ──
let LS = null, bws = null, bsubs = new Set(), bdirty = false
const blive = {}
function renderListing(){
  const sec = $("listingSec")
  if(!LS){ sec.style.display = "none"; return }
  sec.style.display = ""
  const d = LS
  $("lsUpdated").textContent = `${tx("آخر دورة", "last cycle")} ${ago(d.updated)}`
  const pos = d.positions.map(p => {
    const price = blive[p.id] ?? p.price, pnl = (p.entry - price) * p.qty
    return { ...p, price, pnl, pnl_pct: p.margin ? pnl / p.margin * 100 : 0 }
  })
  const s = d.stats, unreal = pos.reduce((a, p) => a + p.pnl, 0), total = s.realized + unreal
  $("lsRealized").innerHTML = `<span class="${tone(s.realized)}">${usd(s.realized)}</span>`
  $("lsWl").textContent = tx(`${s.closed} اتقفلت · ${s.wins} كسبانة / ${s.losses} خسرانة`, `${s.closed} closed · ${s.wins} won / ${s.losses} lost`)
  $("lsUnreal").innerHTML = `<span class="${tone(unreal)}">${usd(unreal)}</span>`
  $("lsOpen").textContent = `${pos.length} / ${d.rules.max_open}`
  $("lsMargin").textContent = `${tx("هامش مستخدم", "margin in use")} $${pos.reduce((a, p) => a + p.margin, 0).toFixed(0)}`
  $("lsTotal").innerHTML = `<span class="${tone(total)}">${usd(total)}</span>`
  $("lsPositions").innerHTML = pos.length ? pos.map(p => `<tr>
      <td class="coin">${esc(p.symbol.replace("/USDT", ""))} <span style="color:var(--loss);font-size:11px">SHORT</span></td>
      <td class="num mono">${px(p.entry)}</td>
      <td class="num mono">${px(p.price)}</td>
      <td class="num mono" style="color:var(--faint)">${px(p.sl)}</td>
      <td class="num mono ${tone(p.pnl)}">${usd(p.pnl)}</td>
      <td class="num mono ${tone(p.pnl_pct)}">${p.pnl_pct > 0 ? "+" : ""}${p.pnl_pct.toFixed(1)}%</td>
      <td class="mono" style="color:var(--muted)">${day(p.exit_at)}</td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">${tx("مفيش شورت مفتوح — مستني عملة تكمّل 30 يوم من إدراجها", "No open short — waiting for a coin to reach 30 days since listing")}</td></tr>`
  $("lsUpcoming").innerHTML = d.upcoming.length ? d.upcoming.map(u => `<span class="chip"><b>${esc(u.symbol.replace("/USDT", ""))}</b> · ${tx("بعد", "in")} <b class="mono">${Math.max(0, Math.ceil(u.days_left))}</b> ${tx("يوم", "days")}</span>`).join("")
    : `<span class="chip">${tx("مفيش عملات جديدة اتدرجت آخر 30 يوم", "No new coins listed in the last 30 days")}</span>`
  $("lsHistCount").textContent = d.history.length ? `${tx("آخر", "last")} ${d.history.length}` : ""
  if(d.history.length) $("lsHistory").innerHTML = d.history.slice(0, 100).map(h => `<tr>
      <td class="coin">${esc(h.symbol.replace("/USDT", ""))}</td>
      <td class="num mono">${px(h.entry)}</td>
      <td class="num mono">${px(h.exit)}</td>
      <td class="num mono ${tone(h.pnl)}">${usd(h.pnl)}</td>
      <td style="color:var(--muted)">${esc(rsn(h.reason))}</td>
      <td class="mono" style="color:var(--muted)">${day(h.time)}</td></tr>`).join("")
}
async function loadListing(){
  try{ const r = await fetch(`listing.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; LS = await r.json(); renderListing(); bsubscribe() }
  catch{ if(!LS) renderListing() }
}
function bsubscribe(){
  if(!bws || bws.readyState !== 1) return
  const ids = [...(LS ? LS.positions : []), ...(typeof MS !== "undefined" && MS ? MS.positions : []), ...(typeof MD !== "undefined" && MD ? MD.positions : []), ...(typeof MB !== "undefined" && MB ? MB.positions : []), ...(typeof RF !== "undefined" && RF ? RF.positions : []),
               ...(typeof RS !== "undefined" && RS ? RS.pairs.flatMap(p => [p.long, p.short]) : []),
               ...(typeof RN !== "undefined" && RN ? RN.pairs.flatMap(p => [p.long, p.short]) : []),
               ...(typeof RT !== "undefined" && RT ? RT.pairs.flatMap(p => [p.long, p.short]) : []),
               ...(typeof RW !== "undefined" && RW ? RW.pairs.flatMap(p => [p.long, p.short]) : []),
               ...(typeof BO !== "undefined" && BO ? BO.positions : []), ...(typeof R2 !== "undefined" && R2 ? R2.positions : []),
               ...(typeof RB !== "undefined" && RB ? RB.positions : []),
               ...(typeof TBk !== "undefined" && TBk ? TBk.positions : [])].map(p => p.id)
  const add = ids.filter(x => !bsubs.has(x))
  if(add.length) bws.send(JSON.stringify({ method: "SUBSCRIBE", params: add.map(x => `${x.toLowerCase()}@miniTicker`), id: Date.now() }))
  add.forEach(x => bsubs.add(x))
}
function bconnect(){
  bws = new WebSocket("wss://fstream.binance.com/market/ws")   // Binance moved market streams to /market (the old /ws path accepts subscriptions but sends nothing)
  bws.onopen = () => { bsubs = new Set(); bsubscribe() }
  bws.onmessage = e => { const m = JSON.parse(e.data); if(m.e === "24hrMiniTicker"){ blive[m.s] = +m.c; bdirty = true } }
  bws.onclose = () => setTimeout(bconnect, 3000)
  bws.onerror = () => bws.close()
}
loadListing(); bconnect()
setInterval(loadListing, 15000)
setInterval(() => { if(bdirty){ bdirty = false; renderListing() } }, 1000)
// ── weekly momentum long/short (third paper bot): momentum.json every 15 s, prices on the same Binance stream ──
let MS = null
const sideTag = s => s === "long" ? `<span style="color:var(--profit);font-weight:700">LONG</span>` : `<span style="color:var(--loss);font-weight:700">SHORT</span>`
function renderMomBot(d, p, secId, wait){
  const sec = $(secId)
  if(!d){ sec.style.display = "none"; return }
  sec.style.display = ""
  $(p + "Updated").textContent = `${tx("آخر دورة", "last cycle")} ${ago(d.updated)}`
  const pos = d.positions.map(p => {
    const price = blive[p.id] ?? p.price, sg = p.side === "long" ? 1 : -1, pnl = sg * (price - p.entry) * p.qty
    return { ...p, price, pnl, pnl_pct: p.margin ? pnl / p.margin * 100 : 0 }
  })
  const s = d.stats, unreal = pos.reduce((a, p) => a + p.pnl, 0), total = s.realized + unreal
  $(p + "Realized").innerHTML = `<span class="${tone(s.realized)}">${usd(s.realized)}</span>`
  $(p + "Wl").textContent = tx(`${s.closed} اتقفلت · ${s.wins} كسبانة / ${s.losses} خسرانة`, `${s.closed} closed · ${s.wins} won / ${s.losses} lost`)
  $(p + "Unreal").innerHTML = `<span class="${tone(unreal)}">${usd(unreal)}</span>`
  $(p + "Open").textContent = tx(`${pos.filter(p => p.side === "long").length} لونج · ${pos.filter(p => p.side === "short").length} شورت`, `${pos.filter(p => p.side === "long").length} long · ${pos.filter(p => p.side === "short").length} short`)
  $(p + "Margin").textContent = `${tx("هامش مستخدم", "margin in use")} $${pos.reduce((a, p) => a + p.margin, 0).toFixed(0)}`
  $(p + "Next").textContent = d.next_rebalance ? new Date(d.next_rebalance).toLocaleDateString(L === "en" ? "en-GB" : "ar-EG", {weekday: "long", day: "numeric", month: "short", timeZone: "UTC"}) : "—"
  $(p + "Total").innerHTML = `${tx("الإجمالي", "Total")} <b class="mono ${tone(total)}">${usd(total)}</b>`
  $(p + "Positions").innerHTML = pos.length ? pos.map(p => `<tr>
      <td class="coin">${esc(p.symbol.replace("/USDT", ""))}</td>
      <td>${sideTag(p.side)}</td>
      <td class="num mono ${tone(p.ret)}">${p.ret > 0 ? "+" : ""}${Number(p.ret).toFixed(0)}%</td>
      <td class="num mono">${px(p.entry)}</td>
      <td class="num mono">${px(p.price)}</td>
      <td class="num mono" style="color:var(--faint)">${px(p.sl)}</td>
      <td class="num mono ${tone(p.pnl)}">${usd(p.pnl)}</td>
      <td class="num mono ${tone(p.pnl_pct)}">${p.pnl_pct > 0 ? "+" : ""}${p.pnl_pct.toFixed(1)}%</td></tr>`).join("")
    : `<tr><td colspan="8" class="empty">${wait()}</td></tr>`
  $(p + "HistCount").textContent = d.history.length ? `${tx("آخر", "last")} ${d.history.length}` : ""
  if(d.history.length) $(p + "History").innerHTML = d.history.slice(0, 100).map(h => `<tr>
      <td class="coin">${esc(h.symbol.replace("/USDT", ""))}</td>
      <td>${sideTag(h.side)}</td>
      <td class="num mono">${px(h.entry)}</td>
      <td class="num mono">${px(h.exit)}</td>
      <td class="num mono ${tone(h.pnl)}">${usd(h.pnl)}</td>
      <td style="color:var(--muted)">${esc(rsn(h.reason))}</td>
      <td class="mono" style="color:var(--muted)">${day(h.time)}</td></tr>`).join("")
}
function renderMomentum(){ renderMomBot(MS, "ms", "momSec", () => tx("مفيش صفقات مفتوحة — مستني التبديل الأسبوعي", "No open trades — waiting for the weekly rebalance")) }
async function loadMomentum(){
  try{ const r = await fetch(`momentum.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; MS = await r.json(); renderMomentum(); bsubscribe() }
  catch{ if(!MS) renderMomentum() }
}
loadMomentum()
setInterval(loadMomentum, 15000)
setInterval(() => { if(MS) renderMomentum() }, 1000)
// ── momentum daily (owner, 2026-11-11): momentum_daily.json every 15 s, a new basket every day ──
let MD = null
function renderMomDaily(){ renderMomBot(MD, "md", "mdSec", () => tx("مفيش صفقات مفتوحة — مستني سلة بكرة", "No open trades — waiting for tomorrow's basket")) }
async function loadMomDaily(){
  try{ const r = await fetch(`momentum_daily.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; MD = await r.json(); renderMomDaily(); bsubscribe() }
  catch{ if(!MD) renderMomDaily() }
}
loadMomDaily()
setInterval(loadMomDaily, 15000)
setInterval(() => { if(MD) renderMomDaily() }, 1000)
// ── momentum daily, buffer 7 (research §37): momentum_daily_b7.json every 15 s ──
let MB = null
function renderMomB7(){ renderMomBot(MB, "mb", "mbSec", () => tx("مفيش صفقات مفتوحة — مستني سلة بكرة", "No open trades — waiting for tomorrow's basket")) }
async function loadMomB7(){
  try{ const r = await fetch(`momentum_daily_b7.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; MB = await r.json(); renderMomB7(); bsubscribe() }
  catch{ if(!MB) renderMomB7() }
}
loadMomB7()
setInterval(loadMomB7, 15000)
setInterval(() => { if(MB) renderMomB7() }, 1000)
// ── against the crowd (research §29): retail_fade.json every 15 s, legs priced on the same Binance stream ──
let RF = null
function renderRetail(){
  const sec = $("rfSec")
  if(!RF){ sec.style.display = "none"; return }
  sec.style.display = ""
  const d = RF
  $("rfUpdated").textContent = `${tx("آخر دورة", "last cycle")} ${ago(d.updated)}`
  const pos = d.positions.map(p => {
    const price = blive[p.id] ?? p.price, sg = p.side === "long" ? 1 : -1, pnl = sg * (price - p.entry) * p.qty
    return { ...p, price, pnl, pnl_pct: p.margin ? pnl / p.margin * 100 : 0 }
  })
  const s = d.stats, unreal = pos.reduce((a, p) => a + p.pnl, 0), total = s.realized + unreal
  $("rfRealized").innerHTML = `<span class="${tone(s.realized)}">${usd(s.realized)}</span>`
  $("rfWl").textContent = tx(`${s.closed} اتقفلت · ${s.wins} كسبانة / ${s.losses} خسرانة`, `${s.closed} closed · ${s.wins} won / ${s.losses} lost`)
  $("rfUnreal").innerHTML = `<span class="${tone(unreal)}">${usd(unreal)}</span>`
  $("rfOpen").textContent = tx(`${pos.filter(p => p.side === "long").length} لونج · ${pos.filter(p => p.side === "short").length} شورت`, `${pos.filter(p => p.side === "long").length} long · ${pos.filter(p => p.side === "short").length} short`)
  $("rfMargin").textContent = `${tx("هامش مستخدم", "margin in use")} $${pos.reduce((a, p) => a + p.margin, 0).toFixed(0)}`
  $("rfNext").textContent = d.next_rebalance ? new Date(d.next_rebalance).toLocaleDateString(L === "en" ? "en-GB" : "ar-EG", {weekday: "long", day: "numeric", month: "short", timeZone: "UTC"}) : "—"
  $("rfTotal").innerHTML = `${tx("الإجمالي", "Total")} <b class="mono ${tone(total)}">${usd(total)}</b>`
  $("rfPositions").innerHTML = pos.length ? pos.map(p => `<tr>
      <td class="coin">${esc(p.symbol.replace("/USDT", ""))}</td>
      <td>${sideTag(p.side)}</td>
      <td class="num mono">${p.ratio != null ? Number(p.ratio).toFixed(2) : "—"}</td>
      <td class="num mono">${px(p.entry)}</td>
      <td class="num mono">${px(p.price)}</td>
      <td class="num mono" style="color:var(--faint)">${px(p.sl)}</td>
      <td class="num mono ${tone(p.pnl)}">${usd(p.pnl)}</td>
      <td class="num mono ${tone(p.pnl_pct)}">${p.pnl_pct > 0 ? "+" : ""}${p.pnl_pct.toFixed(1)}%</td></tr>`).join("")
    : `<tr><td colspan="8" class="empty">${tx("مفيش صفقات مفتوحة — مستني التبديل الأسبوعي", "No open trades — waiting for the weekly rebalance")}</td></tr>`
  $("rfHistCount").textContent = d.history.length ? `${tx("آخر", "last")} ${d.history.length}` : ""
  if(d.history.length) $("rfHistory").innerHTML = d.history.slice(0, 100).map(h => `<tr>
      <td class="coin">${esc(h.symbol.replace("/USDT", ""))}</td>
      <td>${sideTag(h.side)}</td>
      <td class="num mono">${px(h.entry)}</td>
      <td class="num mono">${px(h.exit)}</td>
      <td class="num mono ${tone(h.pnl)}">${usd(h.pnl)}</td>
      <td style="color:var(--muted)">${esc(rsn(h.reason))}</td>
      <td class="mono" style="color:var(--muted)">${day(h.time)}</td></tr>`).join("")
}
async function loadRetail(){
  try{ const r = await fetch(`retail_fade.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; RF = await r.json(); renderRetail(); bsubscribe() }
  catch{ if(!RF) renderRetail() }
}
loadRetail()
setInterval(loadRetail, 15000)
setInterval(() => { if(RF) renderRetail() }, 1000)
// ── the three portfolios (research §31, owner 2026-11-09): the sum of the momentum, crowd and RSI-2 + BTC paper bots,
// every trade at $100 of margin, the trades opened from PF_START — the same rule as scripts/demo_weekly.py's section.
// A fixed date, not the bots' "started": that moves at every restart and would empty the portfolios each time. ──
const PF_MARGIN = 100, PF_START = Date.parse("2026-11-09T00:00:00Z")
const opened = x => Date.parse(x.opened || x.time)
const PORTFOLIOS = [                       // [name, its bots] — called at each render, so the name follows the language
  () => [tx("مومنتم + عكس الأغلبية", "Momentum + against the crowd"), [MS, RF]],
  () => [tx("مومنتم + RSI-2", "Momentum + RSI-2"), [MS, RB]],
  () => [tx("الثلاثة", "All three"), [MS, RF, RB]],
]
function pfStats(bots){
  const k = d => d.margin > 0 ? PF_MARGIN / d.margin : 0
  const closed = bots.flatMap(d => (d.history || []).filter(h => opened(h) >= PF_START).map(h => ({ t: Date.parse(h.time), pnl: h.pnl * k(d) })))
                     .sort((a, b) => a.t - b.t)
  let eq = 0, peak = 0, dd = 0
  for(const c of closed){ eq += c.pnl; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq) }
  const open = bots.flatMap(d => (d.positions || []).filter(p => opened(p) >= PF_START).map(p => {
    const price = blive[p.id] ?? p.price, sg = p.side === "short" ? -1 : 1
    return sg * (price - p.entry) * p.qty * (p.margin > 0 ? PF_MARGIN / p.margin : k(d))
  }))
  return { n: closed.length, wins: closed.filter(c => c.pnl > 0).length, realized: eq, dd,
           unreal: open.reduce((a, v) => a + v, 0), legs: open.length }
}
function renderPortfolios(){
  const sec = $("pfSec")
  if(!MS && !RF && !RB){ sec.style.display = "none"; return }
  sec.style.display = ""
  const names = [[MS, tx("مومنتم", "momentum")], [RF, tx("عكس الأغلبية", "against the crowd")], [RB, "RSI-2 + BTC"]]
  $("pfRows").innerHTML = PORTFOLIOS.map(pf => {
    const [label, bots] = pf()
    if(bots.some(d => !d)){
      const miss = names.filter(([d]) => bots.includes(d) && !d).map(([, n]) => n).join(tx(" و", ", "))
      return `<tr><td class="coin">${esc(label)}</td><td colspan="7" class="empty">${tx("مستني ملف", "waiting for the file of")} ${esc(miss)}</td></tr>`
    }
    const s = pfStats(bots)
    return `<tr><td class="coin">${esc(label)}</td>
      <td class="num mono">${s.n}</td>
      <td class="num mono">${s.n ? Math.round(s.wins / s.n * 100) + "%" : "—"}</td>
      <td class="num mono ${tone(s.realized)}">${usd(s.realized)}</td>
      <td class="num mono ${tone(s.unreal)}">${usd(s.unreal)}</td>
      <td class="num mono ${tone(s.realized + s.unreal)}"><b>${usd(s.realized + s.unreal)}</b></td>
      <td class="num mono loss">${s.dd ? usd(-s.dd) : "—"}</td>
      <td class="num mono">$${(s.legs * PF_MARGIN).toLocaleString("en-US")}</td></tr>`
  }).join("")
  $("pfSince").textContent = `${tx("الصفقات اللي اتفتحت من", "trades opened since")} ${day(new Date(PF_START).toISOString())}`
}
setInterval(renderPortfolios, 1000)
// ── HIGH RISK ratio trend (fourth paper bot): ratio.json every 15 s, legs priced on the same Binance stream ──
let RS = null, RN = null, RT = null, RW = null
function renderRatioInto(k, secId, d){
  const sec = $(secId)
  if(!d){ sec.style.display = "none"; return }
  sec.style.display = ""
  $(k + "Updated").textContent = `${tx("آخر دورة", "last cycle")} ${ago(d.updated)}`
  $(k + "Members").innerHTML = d.members.map(m => `<span class="chip"><b>${esc(m)}</b></span>`).join("")
  const legPnl = l => (l.side === "long" ? 1 : -1) * ((blive[l.id] ?? l.price) - l.entry) * l.qty
  const pairs = d.pairs.map(p => ({ ...p, pnl: legPnl(p.long) + legPnl(p.short) }))
  const s = d.stats, unreal = pairs.reduce((a, p) => a + p.pnl, 0), total = s.realized + unreal
  $(k + "Realized").innerHTML = `<span class="${tone(s.realized)}">${usd(s.realized)}</span>`
  $(k + "Wl").textContent = tx(`${s.closed} اتقفلت · ${s.wins} كسبانة / ${s.losses} خسرانة`, `${s.closed} closed · ${s.wins} won / ${s.losses} lost`)
  $(k + "Unreal").innerHTML = `<span class="${tone(unreal)}">${usd(unreal)}</span>`
  $(k + "Open").textContent = pairs.length
  $(k + "Margin").textContent = `${tx("هامش مستخدم", "margin in use")} $${pairs.reduce((a, p) => a + p.margin, 0).toFixed(0)}`
  $(k + "Total").innerHTML = `<span class="${tone(total)}">${usd(total)}</span>`
  $(k + "Next").textContent = d.next_members ? tx(`تحديث القائمة ${day(d.next_members)}`, `list refresh ${day(d.next_members)}`) : ""
  $(k + "Pairs").innerHTML = pairs.length ? pairs.map(p => `<tr>
      <td class="coin" style="color:var(--profit)">${esc(p.long.symbol.replace("/USDT", ""))}</td>
      <td class="coin" style="color:var(--loss)">${esc(p.short.symbol.replace("/USDT", ""))}</td>
      <td class="num mono">${px(p.long.entry)}</td>
      <td class="num mono">${px(p.short.entry)}</td>
      <td class="num mono ${tone(p.pnl)}">${usd(p.pnl)}</td>
      <td class="mono" style="color:var(--muted)">${day(p.opened)}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">${tx("مفيش أزواج مفتوحة", "No open pairs")}</td></tr>`
  $(k + "HistCount").textContent = d.history.length ? `${tx("آخر", "last")} ${d.history.length}` : ""
  if(d.history.length) $(k + "History").innerHTML = d.history.slice(0, 100).map(h => `<tr>
      <td class="coin">${esc(h.pair)}</td>
      <td class="num mono ${tone(h.pnl)}">${usd(h.pnl)}</td>
      <td style="color:var(--muted)">${esc(rsn(h.reason))}</td>
      <td class="mono" style="color:var(--muted)">${day(h.time)}</td></tr>`).join("")
}
function renderRatio(){ renderRatioInto("rs", "ratioSec", RS) }
function renderRatioNb(){ renderRatioInto("rn", "ratioNbSec", RN) }
function renderRatioTr(){ renderRatioInto("rt", "ratioTrSec", RT) }
function renderRatioTw(){ renderRatioInto("rw", "ratioTwSec", RW) }
async function loadRatio(){
  try{ const r = await fetch(`ratio.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; RS = await r.json(); renderRatio(); bsubscribe() }
  catch{ if(!RS) renderRatio() }
  // the second ratio bot (no BTC/ETH, research §25): hidden until its file exists
  try{ const r = await fetch(`ratio_nobtc.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; RN = await r.json(); renderRatioNb(); bsubscribe() }
  catch{ if(!RN) renderRatioNb() }
  // the same with a 20% trail (research §35): hidden until its file exists
  try{ const r = await fetch(`ratio_trail.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; RT = await r.json(); renderRatioTr(); bsubscribe() }
  catch{ if(!RT) renderRatioTr() }
  // the first ratio bot with a 20% trail (research §35): hidden until its file exists
  try{ const r = await fetch(`ratio_trail_btc.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; RW = await r.json(); renderRatioTw(); bsubscribe() }
  catch{ if(!RW) renderRatioTw() }
}
loadRatio()
setInterval(loadRatio, 15000)
setInterval(() => { if(RS) renderRatio(); if(RN) renderRatioNb(); if(RT) renderRatioTr(); if(RW) renderRatioTw() }, 1000)
// ── volatility breakout + RSI-2 (fifth and sixth paper bots): breakout.json / rsi2.json every 15 s, Binance prices ──
let BO = null, R2 = null, TBk = null, RB = null
function renderSimple(key, d, watchHtml){
  const sec = $(key + "Sec")
  if(!d){ sec.style.display = "none"; return }
  sec.style.display = ""
  $(key + "Updated").textContent = `${tx("آخر دورة", "last cycle")} ${ago(d.updated)}`
  const pos = d.positions.map(p => { const price = blive[p.id] ?? p.price, pnl = (price - p.entry) * p.qty
    return { ...p, price, pnl, pnl_pct: p.margin ? pnl / p.margin * 100 : 0 } })
  const s = d.stats, unreal = pos.reduce((a, p) => a + p.pnl, 0), total = s.realized + unreal
  $(key + "Realized").innerHTML = `<span class="${tone(s.realized)}">${usd(s.realized)}</span>`
  $(key + "Wl").textContent = tx(`${s.closed} اتقفلت · ${s.wins} كسبانة / ${s.losses} خسرانة`, `${s.closed} closed · ${s.wins} won / ${s.losses} lost`)
  $(key + "Unreal").innerHTML = `<span class="${tone(unreal)}">${usd(unreal)}</span>`
  $(key + "Open").textContent = tx(`${pos.length} لونج`, `${pos.length} long`)
  $(key + "Margin").textContent = `${tx("هامش مستخدم", "margin in use")} $${pos.reduce((a, p) => a + p.margin, 0).toFixed(0)}`
  $(key + "Watch").innerHTML = watchHtml
  $(key + "Total").innerHTML = `${tx("الإجمالي", "Total")} <b class="mono ${tone(total)}">${usd(total)}</b>`
  $(key + "Positions").innerHTML = pos.length ? pos.map(p => `<tr>
      <td class="coin">${esc(p.symbol.replace("/USDT", ""))}</td>
      <td class="num mono">${px(p.entry)}</td><td class="num mono">${px(p.price)}</td>
      <td class="num mono" style="color:var(--faint)">${px(p.sl)}</td>
      <td style="color:var(--muted)">${key === "bo" ? tx("افتتاح بكرة 00:00 UTC", "tomorrow's open 00:00 UTC") : key === "tb" ? tx("قفل يومي تحت متوسط 20 يوم", "a daily close below the 20-day average") : tx("قفل فوق متوسط 5 أيام · لحد ", "a close above the 5-day average · by ") + day(p.exit_at)}</td>
      <td class="num mono ${tone(p.pnl)}">${usd(p.pnl)}</td>
      <td class="num mono ${tone(p.pnl_pct)}">${p.pnl_pct > 0 ? "+" : ""}${p.pnl_pct.toFixed(1)}%</td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">${tx("مفيش صفقات مفتوحة — مستني إشارة", "No open trades — waiting for a signal")}</td></tr>`
  $(key + "HistCount").textContent = d.history.length ? `${tx("آخر", "last")} ${d.history.length}` : ""
  if(d.history.length) $(key + "History").innerHTML = d.history.slice(0, 100).map(h => `<tr>
      <td class="coin">${esc(h.symbol.replace("/USDT", ""))}</td>
      <td class="num mono">${px(h.entry)}</td><td class="num mono">${px(h.exit)}</td>
      <td class="num mono ${tone(h.pnl)}">${usd(h.pnl)}</td>
      <td style="color:var(--muted)">${esc(rsn(h.reason))}</td>
      <td class="mono" style="color:var(--muted)">${day(h.time)}</td></tr>`).join("")
}
function renderBreakout(){
  const plan = (BO && BO.plan || []).filter(p => p.above_ma && p.trigger && !p.entered)
  renderSimple("bo", BO, plan.length ? plan.slice(0, 5).map(p => `${esc(p.symbol.replace("/USDT", ""))} <span class="mono">${px(p.trigger)}</span>`).join("<br>")
                                     : `<span style="color:var(--faint)">${tx("ولا عملة فوق متوسط 20 النهارده", "No coin above its 20-day average today")}</span>`)
}
function renderRsi2(){
  const w = (R2 && R2.watch || []).filter(x => x.above_200).sort((a, b) => a.rsi2 - b.rsi2)
  renderSimple("r2", R2, w.length ? w.slice(0, 4).map(x => `${esc(x.symbol.replace("/USDT", ""))} <span class="mono">RSI ${Number(x.rsi2).toFixed(0)}</span>`).join("<br>")
                                  : `<span style="color:var(--faint)">${tx("مفيش عملة في ترند صاعد", "No coin in an uptrend")}</span>`)
}
function renderRsi2Btc(){
  const f = RB && RB.btc_filter, w = (RB && RB.watch || []).filter(x => x.above_200).sort((a, b) => a.rsi2 - b.rsi2)
  const btc = !f ? "" : f.error ? `<span style="color:var(--faint)">${tx("BTC: مفيش داتا — مفيش دخول", "BTC: no data — no entries")}</span><br>`
    : f.above ? `<span class="profit">${tx("BTC فوق متوسط 200 — الدخول مفتوح", "BTC above its 200-day average — entries on")}</span><br>`
    : `<span class="loss">${tx("BTC تحت متوسط 200 — مفيش دخول", "BTC below its 200-day average — no entries")}</span><br>`
  renderSimple("rb", RB, btc + (w.length ? w.slice(0, 3).map(x => `${esc(x.symbol.replace("/USDT", ""))} <span class="mono">RSI ${Number(x.rsi2).toFixed(0)}</span>`).join("<br>")
                                         : `<span style="color:var(--faint)">${tx("مفيش عملة في ترند صاعد", "No coin in an uptrend")}</span>`))
}
async function loadSimple(){
  for(const [file, set, render] of [["breakout", v => BO = v, renderBreakout], ["rsi2", v => R2 = v, renderRsi2], ["rsi2_btc", v => RB = v, renderRsi2Btc], ["tbreak", v => TBk = v, renderTbreak]]){
    try{ const r = await fetch(`${file}.json?t=${Date.now()}`, {cache: "no-store"}); if(!r.ok) throw 0; set(await r.json()); render() } catch{ render() }
  }
  bsubscribe()
}
function renderTbreak(){
  const w = (TBk && TBk.watch || [])
  renderSimple("tb", TBk, w.length ? w.slice(0, 4).map(x => `${esc(x.symbol.replace("/USDT", ""))} <span class="mono">${x.gap_pct > 0 ? "+" : ""}${Number(x.gap_pct).toFixed(1)}%</span>`).join("<br>")
                                   : `<span style="color:var(--faint)">${tx("مفيش عملة في ترند صاعد", "No coin in an uptrend")}</span>`)
}
loadSimple()
setInterval(loadSimple, 15000)

function renderAll(){
  applyWords()
  if(D){ renderSettings(D); render() }
  renderListing(); renderMomentum(); renderRetail(); renderPortfolios(); renderRatio(); renderBreakout(); renderRsi2(); renderRsi2Btc(); renderTbreak()
}
$("langBtn").onclick = () => {
  L = L === "ar" ? "en" : "ar"
  const h = document.documentElement; h.lang = L; h.dir = L === "ar" ? "rtl" : "ltr"
  try { localStorage.setItem("raqm-lang", L) } catch(e){}
  const u = new URL(location.href); if(u.searchParams.has("lang")){ u.searchParams.set("lang", L); history.replaceState(null, "", u) }
  renderAll()
}
$("themeBtn").onclick = () => {
  const h = document.documentElement, next = h.dataset.theme === "dark" ? "light" : "dark"
  h.dataset.theme = next
  try { localStorage.setItem("raqm-theme", next) } catch(e){}
  applyWords()
}
setInterval(() => { if(BO) renderBreakout(); if(R2) renderRsi2(); if(RB) renderRsi2Btc(); if(TBk) renderTbreak() }, 1000)

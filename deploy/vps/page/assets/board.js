// the leaderboard: one row per bot, its side panel, compare, the portfolios tab and the URL's view (split from index.html on 2026-11-11; classic scripts, loaded in order, one shared scope)

// ── the leaderboard page (owner, 2026-11-10; Figma "RAQM — Global Redesign 2026", page 09 · Paper bots) ──
// One row per bot instead of twelve stacked sections. A row opens that bot's own section in a side panel (#drawer),
// "Compare" puts two bots side by side, and "Portfolios" holds the three portfolios. The state is in the URL hash
// (#bot=<key>, #view=cmp&a=<key>&b=<key>, #view=pf) so a link opens the same view.
const FAM = { trend: ["ترند", "Trend"], momentum: ["مومنتم", "Momentum"], ratio: ["Ratio", "Ratio"], meanrev: ["ارتداد", "Mean reversion"],
              breakout: ["بريك أوت", "Breakout"], short: ["شورت", "Short"] }
const TRAIL = { ar: "الفرق الوحيد: الزوج بيتقفل لو النسبة رجعت 20% من أحسن يوم، ويستنى لحد ما الترند يتقلب (research §35).",
                en: "The one difference: a pair closes when its ratio falls 20% from its best day, and waits until the trend turns (research §35)." }
const BOTS = [
  { k: "status", d: () => D, sec: "trendSec", ar: "الترند اليومي", en: "Daily trend", fam: "trend", kind: "bybit" },
  { k: "listing", d: () => LS, sec: "listingSec", ar: "شورت العملات الجديدة", en: "New listing short", fam: "short", kind: "short" },
  { k: "momentum", d: () => MS, sec: "momSec", ar: "مومنتم", en: "Momentum", fam: "momentum" },
  { k: "retail_fade", d: () => RF, sec: "rfSec", ar: "عكس الأغلبية", en: "Against the crowd", fam: "momentum" },
  { k: "ratio", d: () => RS, sec: "ratioSec", ar: "Ratio", en: "Ratio trend", fam: "ratio", risk: true, ab: "A", twin: "ratio_trail_btc" },
  { k: "ratio_trail_btc", d: () => RW, sec: "ratioTwSec", ar: "Ratio · trailing 20%", en: "Ratio · trail 20%", fam: "ratio", risk: true, ab: "B", twin: "ratio",
    since: "2026-11-10T11:30:00Z", diff: TRAIL },
  { k: "ratio_nobtc", d: () => RN, sec: "ratioNbSec", ar: "Ratio من غير BTC/ETH", en: "Ratio · no BTC/ETH", fam: "ratio", risk: true, ab: "A", twin: "ratio_trail" },
  { k: "ratio_trail", d: () => RT, sec: "ratioTrSec", ar: "Ratio من غير BTC/ETH · trailing 20%", en: "Ratio · no BTC/ETH · trail 20%", fam: "ratio", risk: true, ab: "B",
    twin: "ratio_nobtc", since: "2026-11-10T11:17:00Z", diff: TRAIL },
  { k: "breakout", d: () => BO, sec: "boSec", ar: "بريك أوت التذبذب", en: "Volatility breakout", fam: "breakout" },
  { k: "rsi2", d: () => R2, sec: "r2Sec", ar: "RSI-2", en: "RSI-2", fam: "meanrev", ab: "A", twin: "rsi2_btc" },
  { k: "rsi2_btc", d: () => RB, sec: "rbSec", ar: "RSI-2 + فلتر BTC", en: "RSI-2 + BTC filter", fam: "meanrev", ab: "B", twin: "rsi2",
    diff: { ar: "الفرق الوحيد: مفيش دخول جديد غير لما BTC يقفل فوق متوسط 200 يوم (research §28).", en: "The one difference: no new entry unless BTC closes above its 200-day average (research §28)." } },
  { k: "tbreak", d: () => TBk, sec: "tbSec", ar: "اختراق الترند", en: "Trend breakout", fam: "trend" },
]
const bot = k => BOTS.find(b => b.k === k)
const put = (id, html) => { const e = $(id); if(e.innerHTML !== html) e.innerHTML = html }   // redraw only what changed: keeps focus and hover
const bname = b => tx(b.ar, b.en)
const STALE_S = 900                                   // scripts/watchdog.py PAPER_STALE_S: a bot quiet that long is stopped or stuck
const lp = l => (l.side === "long" ? 1 : -1) * ((blive[l.id] ?? l.price) - l.entry) * l.qty
const pairPnl = p => lp(p.long) + lp(p.short)
const pairName = p => `${p.long.symbol.replace("/USDT", "").replace(":USDT", "")} / ${p.short.symbol.replace("/USDT", "").replace(":USDT", "")}`
function openPnl(b, d){
  if(d.pairs) return d.pairs.reduce((a, p) => a + pairPnl(p), 0)
  return (d.positions || []).reduce((a, p) => {
    const price = b.kind === "bybit" ? priceOf(p.symbol, p.price) : (blive[p.id] ?? p.price)
    return a + (b.kind === "short" || p.side === "short" ? -1 : 1) * (price - p.entry) * p.qty }, 0)
}
function summary(b){
  const d = b.d(); if(!d) return null
  const s = d.stats || {}, open = openPnl(b, d), realized = +s.realized || 0, closed = s.closed || 0
  const age = (Date.now() - Date.parse(d.updated)) / 1000
  const hist = (d.history || []).filter(h => h.pnl != null && h.time)
  const coins = [...(d.positions || []).map(p => p.symbol), ...(d.pairs || []).flatMap(p => [p.long.symbol, p.short.symbol])].join(" ")
  return { b, d, realized, open, total: realized + open, closed, win: closed ? Math.round((s.wins || 0) / closed * 100) : null,
           nOpen: d.pairs ? d.pairs.length : (d.positions || []).length, age, stale: !(age < STALE_S), hist, coins }
}
function spark(sm){
  // realized P&L of the last 14 days, a point a day, ending with today's total (realized + open)
  const now = Date.now(), DAY = 86400000, start = now - 14 * DAY
  let base = sm.hist.filter(h => Date.parse(h.time) < start).reduce((a, h) => a + h.pnl, 0)
  const pts = []
  for(let i = 0; i <= 14; i++){
    const end = start + i * DAY
    pts.push(base + sm.hist.filter(h => { const t = Date.parse(h.time); return t >= start && t < end }).reduce((a, h) => a + h.pnl, 0))
  }
  pts.push(pts[pts.length - 1] + sm.open)
  const w = 96, h = 26, mn = Math.min(...pts), mx = Math.max(...pts)
  const d = pts.map((p, i) => `${i ? "L" : "M"}${(i / (pts.length - 1) * w).toFixed(1)} ${(h - 3 - (p - mn) / ((mx - mn) || 1) * (h - 6)).toFixed(1)}`).join(" ")
  const col = pts[pts.length - 1] >= pts[0] ? "var(--profit)" : "var(--loss)"
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`
}
const agoShort = s => s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`
let VIEW = "lb", FAMSEL = "all", SORT = "total", OPEN = null, PICK = new Set(), CA = "ratio_nobtc", CB = "ratio_trail"
const SORTS = { total: ["الإجمالي", "Total P&L"], realized: ["الربح المحقق", "Realized"], open: ["ربح المفتوح", "Open P&L"], win: ["نسبة الكسب", "Win rate"],
                closed: ["صفقات اتقفلت", "Trades closed"], name: ["الاسم", "Name"] }
function tagsHtml(b){
  return `${b.ab ? `<span class="tag ${b.ab === "B" ? "b" : ""}">${b.ab}</span>` : ""}${b.risk ? `<span class="tag risk">${tx("مخاطرة عالية", "High risk")}</span>` : ""}`
}
function renderUI(){
  const all = BOTS.map(summary), have = all.filter(Boolean)
  $("pTitle").textContent = tx("بوتات الـ Paper", "Paper bots")
  $("pSub").textContent = tx("كل استراتيجية بنجربها، بفلوس وهمية على أسعار حقيقية. دوس على بوت تشوف صفقاته، أو قارن اتنين جنب بعض.",
                             "Every strategy we test, trading play money on live prices. Pick a bot to see its trades, or compare two side by side.")
  for(const btn of $("viewSeg").children){
    btn.textContent = { lb: tx("الترتيب", "Leaderboard"), cmp: tx("مقارنة", "Compare"), pf: tx("المحافظ", "Portfolios") }[btn.dataset.view]
    btn.setAttribute("aria-selected", String(btn.dataset.view === VIEW))
  }
  $("vLb").hidden = VIEW !== "lb"; $("vCmp").hidden = VIEW !== "cmp"; $("vPf").hidden = VIEW !== "pf"
  // summary
  const tot = have.reduce((a, s) => a + s.total, 0), nOpen = have.reduce((a, s) => a + s.nOpen, 0), lead = [...have].sort((a, b) => b.total - a.total)[0]
  const stale = have.filter(s => s.stale)
  put("sumCards", [
    [tx("إجمالي ربح الـ Paper", "Total paper P&L"), `<span class="${tone(tot)}">${usd(tot)}</span>`, tx(`${have.length} بوت، من ساعة ما كل واحد بدأ`, `${have.length} bots, since each started`)],
    [tx("صفقات مفتوحة", "Open trades"), nOpen, tx(`في ${have.filter(s => s.nOpen).length} بوت`, `across ${have.filter(s => s.nOpen).length} bots`)],
    [tx("الأول دلوقتي", "Leading now"), lead ? `<span class="txt">${esc(bname(lead.b))}</span>` : "—", lead ? `<span dir="ltr" class="mono ${tone(lead.total)}">${usd(lead.total)}</span>` : ""],
    [tx("محتاج تشوفه", "Needs a look"), `<span class="${stale.length ? "loss" : ""}">${stale.length}</span>`,
     stale.length ? stale.map(s => bname(s.b)).join(tx("، ", ", ")) + tx(" — مش بيحدّث", " — not updating") : tx("كل البوتات بتحدّث", "every bot is updating")],
  ].map(([l, v, n]) => `<div class="card kpi"><div class="label">${l}</div><div class="value mono ${typeof v === "string" && v.includes("txt") ? "txt" : ""}">${v}</div><div class="note">${n.startsWith("<span") ? n : esc(n)}</div></div>`).join(""))
  if(VIEW === "lb") renderBoard(have)
  if(VIEW === "cmp") renderCompare()
  if(OPEN) renderDrawerHead()
}
function renderBoard(have){
  const counts = { all: have.length }; for(const s of have) counts[s.b.fam] = (counts[s.b.fam] || 0) + 1
  put("fchips", ["all", ...Object.keys(FAM)].filter(f => counts[f]).map(f =>
    `<button type="button" class="fchip" data-fam="${f}" aria-pressed="${FAMSEL === f}">${f === "all" ? tx("الكل", "All") : tx(...FAM[f])} <span class="mono">${counts[f]}</span></button>`).join(""))
  const q = $("q"); q.placeholder = tx("دوّر على بوت أو عملة", "Search a bot or coin")
  const sel = $("sortSel"); if(sel.options.length !== Object.keys(SORTS).length || sel.dataset.l !== L){
    sel.innerHTML = Object.entries(SORTS).map(([k, v]) => `<option value="${k}">${tx("ترتيب: ", "Sort: ")}${tx(...v)}</option>`).join(""); sel.dataset.l = L }
  sel.value = SORT
  $("cmpGo").textContent = tx(`قارن (${PICK.size})`, `Compare (${PICK.size})`); $("cmpGo").classList.toggle("on", PICK.size === 2)
  $("lbHead").innerHTML = [[tx("البوت", "Bot"), ""], [tx("شغال", "Live"), "hm"], [tx("محقق", "Realized"), "num hm"], [tx("مفتوح", "Open"), "num hm"],
    [tx("الإجمالي", "Total"), "num"], [tx("كسب", "Win"), "num hm"], [tx("صفقات", "Trades"), "num hm"], [tx("14 يوم", "14 days"), ""], [tx("قارن", "Cmp"), "hm"]]
    .map(([t, c]) => `<th class="${c}">${t}</th>`).join("")
  const needle = q.value.trim().toLowerCase()
  const rows = have.filter(s => (FAMSEL === "all" || s.b.fam === FAMSEL)
      && (!needle || [s.b.ar, s.b.en, s.coins].join(" ").toLowerCase().includes(needle)))
  const key = { total: s => -s.total, realized: s => -s.realized, open: s => -s.open, win: s => -(s.win ?? -1), closed: s => -s.closed, name: s => bname(s.b) }[SORT]
  rows.sort((a, b) => { const x = key(a), y = key(b); return typeof x === "string" ? x.localeCompare(y) : x - y })
  put("lbRows", rows.length ? rows.map(s => `<tr tabindex="0" data-k="${s.b.k}" data-testid="row-${s.b.k}" class="${s.b.ab ? "ab" : ""} ${OPEN === s.b.k ? "sel" : ""}">
      <td class="bn"><div class="nm">${esc(bname(s.b))} ${tagsHtml(s.b)}</div><span class="fam ${s.b.fam}">${tx(...FAM[s.b.fam])}</span></td>
      <td class="hm mono" style="color:${s.stale ? "var(--loss)" : "var(--faint)"};font-size:12px"><span class="ld ${s.stale ? "stale" : ""}"></span>${agoShort(s.age)}</td>
      <td class="num mono hm ${tone(s.realized)}">${usd(s.realized)}</td>
      <td class="num mono hm ${tone(s.open)}">${usd(s.open)}</td>
      <td class="num mono ${tone(s.total)}"><b>${usd(s.total)}</b></td>
      <td class="num mono hm" style="color:var(--muted)">${s.win == null ? "—" : s.win + "%"}</td>
      <td class="num mono hm" style="color:var(--muted)">${s.closed}</td>
      <td>${spark(s)}</td>
      <td class="hm"><input type="checkbox" class="chk" data-pick="${s.b.k}" ${PICK.has(s.b.k) ? "checked" : ""} aria-label="${tx("اختار للمقارنة", "pick to compare")}"></td></tr>`).join("")
    : `<tr><td colspan="9" class="empty">${tx("مفيش بوت بالبحث ده", "No bot matches")}</td></tr>`)
  $("lbNote").textContent = tx("A / B = نفس البوت بفرق واحد، جنب بعض. دوس على سطر تشوف صفقاته، أو علّم على اتنين وقارنهم.",
                               "A / B = the same bot with one change, side by side. Click a row for its trades, or tick two rows to compare.")
}
// ── the side panel: the bot's own section, moved in while it's open ──
function renderDrawerHead(){
  const b = bot(OPEN); if(!b) return
  $("dTitle").textContent = bname(b)
  $("dTags").innerHTML = `<span class="fam ${b.fam}" style="margin:0">${tx(...FAM[b.fam])}</span> ${tagsHtml(b)}${b.since ? ` <span class="tag">${tx("من", "since")} ${day(b.since)}</span>` : ""}`
  $("dDiff").textContent = b.diff ? tx(b.diff.ar, b.diff.en) : b.twin ? tx(`له توأم بفرق واحد: ${bname(bot(b.twin))}.`, `It has a twin with one change: ${bname(bot(b.twin))}.`) : ""
  $("dDiff").hidden = !$("dDiff").textContent
  $("dActs").innerHTML = b.twin ? `<button class="btn gold" type="button" data-testid="drawer-compare" data-cmp="${b.ab === "B" ? b.twin : b.k},${b.ab === "B" ? b.k : b.twin}">${tx("قارنه بتوأمه", "Compare with its twin")} (${b.ab === "B" ? "A" : "B"})</button>` : ""
  $("dClose").setAttribute("aria-label", tx("قفل", "Close"))
}
function openBot(k, push = true){
  const b = bot(k); if(!b) return
  if(OPEN && OPEN !== k) closeBot(false)
  OPEN = k; $("dBody").appendChild($(b.sec)); $("drawer").hidden = false; document.body.style.overflow = "hidden"
  renderDrawerHead(); renderUI()
  if(push) setHash(`bot=${k}`)
  $("dClose").focus()
}
function closeBot(push = true){
  if(!OPEN) return
  $("bots").appendChild($(bot(OPEN).sec)); OPEN = null; $("drawer").hidden = true; document.body.style.overflow = ""
  if(push) setHash(VIEW === "lb" ? "" : VIEW === "pf" ? "view=pf" : `view=cmp&a=${CA}&b=${CB}`)
  renderUI()
}
// ── compare: two bots on the same prices; twins from the moment both ran (their "since") ──
function windowOf(a, b){ const t = [a.since, b.since].filter(Boolean).map(Date.parse); return a.twin === b.k && t.length ? Math.max(...t) : null }
function cmpStats(sm, since){
  const hist = sm.hist.filter(h => since == null || Date.parse(h.time) >= since).sort((x, y) => Date.parse(x.time) - Date.parse(y.time))
  let eq = 0, peak = 0, dd = 0; const curve = [[since ?? (hist[0] ? Date.parse(hist[0].time) : Date.now()), 0]]
  for(const h of hist){ eq += h.pnl; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); curve.push([Date.parse(h.time), eq]) }
  curve.push([Date.now(), eq + sm.open])
  return { realized: eq, open: sm.open, total: eq + sm.open, closed: hist.length, wins: hist.filter(h => h.pnl > 0).length, dd, nOpen: sm.nOpen, curve,
           trail: hist.filter(h => /^trailing/.test(h.reason || "")).length, hist }
}
function renderCompare(){
  const opts = BOTS.filter(b => b.d()).map(b => `<option value="${b.k}">${esc(bname(b))}</option>`).join("")
  for(const [id, v] of [["cmpA", CA], ["cmpB", CB]]){ const s = $(id); if(s.dataset.o !== opts){ s.innerHTML = opts; s.dataset.o = opts } s.value = v }
  const A = bot(CA), B = bot(CB), sa = A && summary(A), sb = B && summary(B)
  $("cmpAn").textContent = A && A.diff && A.ab === "B" ? tx(A.diff.ar, A.diff.en) : ""
  $("cmpBn").textContent = B && B.diff && B.ab === "B" ? tx(B.diff.ar, B.diff.en) : ""
  $("qpicks").innerHTML = `${tx("اختيارات سريعة:", "Quick picks:")} ` + BOTS.filter(b => b.ab === "B" && bot(b.twin).d() && b.d()).map(b =>
    `<button type="button" class="fchip" data-cmp="${b.twin},${b.k}" aria-pressed="${CA === b.twin && CB === b.k}">${esc(bname(bot(b.twin)))} ⇄ ${esc(bname(b))}</button>`).join("")
  if(!sa || !sb){ $("cmpRows").innerHTML = `<tr><td class="empty" colspan="4">${tx("اختار بوتين ليهم بيانات", "Pick two bots that have data")}</td></tr>`; $("cmpChart").innerHTML = ""; $("cmpDiff").innerHTML = ""; return }
  const since = windowOf(A, B), ca = cmpStats(sa, since), cb = cmpStats(sb, since)
  $("cmpHead").innerHTML = `<th>${since ? tx("من", "Since") + " " + new Date(since).toISOString().slice(0, 16).replace("T", " ") + " UTC" : tx("من أول البوت", "Since each started")}</th>
    <th class="num">A · ${esc(bname(A))}</th><th class="num" style="color:var(--corona)">B · ${esc(bname(B))}</th><th class="num">B − A</th>`
  const money = (x, y) => `<td class="num mono ${tone(x)}">${usd(x)}</td><td class="num mono ${tone(y)}">${usd(y)}</td><td class="num mono ${tone(y - x)}">${usd(y - x)}</td>`
  const plain = (x, y, d = true) => `<td class="num mono">${x}</td><td class="num mono">${y}</td><td class="num mono" style="color:var(--faint)">${d && typeof x === "number" && typeof y === "number" ? (y - x > 0 ? "+" : "") + (y - x) : "—"}</td>`
  const pct = c => c.closed ? Math.round(c.wins / c.closed * 100) : null
  $("cmpRows").innerHTML = [
    [tx("الإجمالي", "Total P&L"), money(ca.total, cb.total)],
    [tx("ربح محقق", "Realized"), money(ca.realized, cb.realized)],
    [tx("ربح المفتوح", "Open P&L"), money(ca.open, cb.open)],
    [tx("مفتوح دلوقتي", "Open now"), plain(ca.nOpen, cb.nOpen)],
    [tx("اتقفلت", "Closed"), plain(ca.closed, cb.closed)],
    [tx("نسبة الكسب", "Win rate"), plain(pct(ca) == null ? "—" : pct(ca) + "%", pct(cb) == null ? "—" : pct(cb) + "%", false)],
    [tx("اتقفلت بالـ trailing", "Closed by the trail"), plain(ca.trail, cb.trail)],
    [tx("أقصى تراجع (المحقق)", "Worst fall (realized)"), `<td class="num mono loss">${ca.dd ? usd(-ca.dd) : "—"}</td><td class="num mono loss">${cb.dd ? usd(-cb.dd) : "—"}</td><td class="num mono ${tone(ca.dd - cb.dd)}">${ca.dd || cb.dd ? usd(ca.dd - cb.dd) : "—"}</td>`],
  ].map(([l, c]) => `<tr><td style="color:var(--muted)">${l}</td>${c}</tr>`).join("")
  // chart: realized step by step, ending at today's total
  $("cmpChartT").textContent = tx("الربح مع الوقت", "P&L over time")
  $("cmpChartN").innerHTML = `<span style="color:var(--muted)">━ A</span> &nbsp; <span class="gold">━ B</span>`
  const pts = [...ca.curve, ...cb.curve], t0 = Math.min(...pts.map(p => p[0])), t1 = Math.max(...pts.map(p => p[0]), t0 + 1)
  const v0 = Math.min(0, ...pts.map(p => p[1])), v1 = Math.max(0, ...pts.map(p => p[1]), v0 + 1), W = 1000, H = 220
  const X = t => (t - t0) / (t1 - t0) * W, Y = v => H - 12 - (v - v0) / (v1 - v0) * (H - 24)
  const line = c => c.map(([t, v], i) => `${i ? `L${X(t).toFixed(1)} ${Y(c[i - 1][1]).toFixed(1)} ` : "M"}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ")
  $("cmpChart").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${tx("الربح مع الوقت", "P&L over time")}">
    <path d="M0 ${Y(0).toFixed(1)} H${W}" stroke="var(--line)" stroke-dasharray="4 6"/>
    <path d="${line(ca.curve)}" fill="none" stroke="var(--muted)" stroke-width="2"/>
    <path d="${line(cb.curve)}" fill="none" stroke="var(--corona)" stroke-width="2.4"/></svg>`
  // where they differ: each pair one of them closed by its trail, and what the other did with it
  $("cmpDiffT").textContent = tx("فين اختلفوا", "Where they differ")
  const other = (mine, them) => mine.hist.filter(h => /^trailing/.test(h.reason || "")).map(h => {
    const live = (them.d.pairs || []).find(p => pairName(p) === h.pair)
    const later = them.hist.find(x => x.pair === h.pair && Date.parse(x.time) >= Date.parse(h.time))
    const theirs = live ? pairPnl(live) : later ? later.pnl : null
    return { h, theirs, how: live ? tx("لسه مفتوح", "still open") : later ? tx("قفل", "closed") : tx("مش ماسكه", "not held") } })
  const diffs = [...other(cb, sa).map(x => ({ ...x, who: "B" })), ...other(ca, sb).map(x => ({ ...x, who: "A" }))]
  $("cmpDiff").innerHTML = diffs.length ? `<div class="table"><table style="min-width:560px"><thead><tr><th>${tx("الزوج", "Pair")}</th><th class="num">${tx("أحسن ربح", "Best")}</th><th class="num">${tx("قفل بالـ trailing", "Trail close")}</th><th>${tx("التاني", "The other")}</th><th class="num">${tx("الفرق", "Difference")}</th></tr></thead><tbody>` +
    diffs.map(x => `<tr><td class="coin">${esc(x.h.pair)} <span class="tag ${x.who === "B" ? "b" : ""}">${x.who}</span></td>
      <td class="num mono">${x.h.peak != null ? usd(x.h.peak) : "—"}</td><td class="num mono ${tone(x.h.pnl)}">${usd(x.h.pnl)}</td>
      <td style="color:var(--muted)">${x.how}${x.theirs != null ? ` <span class="mono ${tone(x.theirs)}">${usd(x.theirs)}</span>` : ""}</td>
      <td class="num mono ${tone(x.theirs == null ? 0 : x.h.pnl - x.theirs)}">${x.theirs == null ? "—" : usd(x.h.pnl - x.theirs)}</td></tr>`).join("") + `</tbody></table></div>`
    : `<p class="sub" style="font-size:13px">${A.diff || B.diff ? tx("لسه مفيش: كل زوج يتقفل بدري بالـ trailing هيظهر هنا، ومعاه اللي التاني عمله بنفس الزوج — الربح اللي اتحفظ، أو الترند اللي فات.",
        "Nothing yet: each pair closed early by the trail shows here, with what the other bot did with the same pair — the give-back saved, or the trend it missed.") : tx("البوتين دول مش توأم: قارن الأرقام اللي فوق.", "These two aren't twins: compare the numbers above.")}</p>`
}
// ── views and the URL ──
function setHash(h){ const u = new URL(location.href); u.hash = h; history.replaceState(null, "", u) }
function setView(v, push = true){ VIEW = v; if(push) setHash(v === "lb" ? "" : v === "pf" ? "view=pf" : `view=cmp&a=${CA}&b=${CB}`); renderUI() }
function fromHash(){
  const p = new URLSearchParams(location.hash.slice(1))
  if(p.get("view") === "cmp"){ if(bot(p.get("a"))) CA = p.get("a"); if(bot(p.get("b"))) CB = p.get("b"); VIEW = "cmp" }
  else if(p.get("view") === "pf") VIEW = "pf"
  else VIEW = "lb"
  if(p.get("bot") && bot(p.get("bot"))) openBot(p.get("bot"), false); else if(OPEN) closeBot(false)
  renderUI()
}
$("vPf").appendChild($("pfSec"))
$("viewSeg").onclick = e => { const v = e.target.closest("button")?.dataset.view; if(v) setView(v) }
$("fchips").onclick = e => { const f = e.target.closest("button")?.dataset.fam; if(f){ FAMSEL = f; renderUI() } }
$("q").oninput = () => renderUI()
$("sortSel").onchange = e => { SORT = e.target.value; renderUI() }
$("lbRows").onclick = e => {
  const c = e.target.closest("[data-pick]")
  if(c){ c.checked ? PICK.add(c.dataset.pick) : PICK.delete(c.dataset.pick); while(PICK.size > 2) PICK.delete(PICK.values().next().value); renderUI(); return }
  const r = e.target.closest("tr[data-k]"); if(r) openBot(r.dataset.k)
}
$("lbRows").onkeydown = e => { const r = e.target.closest("tr[data-k]"); if(r && (e.key === "Enter" || e.key === " ")){ e.preventDefault(); openBot(r.dataset.k) } }
$("cmpGo").onclick = () => { if(PICK.size === 2){ [CA, CB] = [...PICK]; PICK.clear(); setView("cmp") } }
const goCmp = e => { const v = e.target.closest("[data-cmp]")?.dataset.cmp; if(v){ [CA, CB] = v.split(","); closeBot(false); setView("cmp") } }
$("qpicks").onclick = goCmp; $("dActs").onclick = goCmp
$("cmpA").onchange = e => { CA = e.target.value; setView("cmp") }
$("cmpB").onchange = e => { CB = e.target.value; setView("cmp") }
$("dClose").onclick = () => closeBot(); $("dBack").onclick = () => closeBot()
document.addEventListener("keydown", e => { if(e.key === "Escape" && OPEN) closeBot() })
window.addEventListener("hashchange", fromHash)
fromHash()
setInterval(renderUI, 1000)
{ const prevAll = renderAll; renderAll = () => { prevAll(); renderUI() } }

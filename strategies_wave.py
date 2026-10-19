"""
Wave Flats — entry at the end of the correction after wave A (Regular / Running / Expanded Flat).
Port of the Pine Script strategy "Wave Flats - Regular / Running / Expanded" (default inputs).
Must stay identical to lib/wave-flats.ts — research/parity.ts compares them trade by trade.

Fibonacci levels run from the start of wave A (0) to its end (1).
1) Regular Flat: price comes back to the 0.382–0.236 zone + reversal candle -> target 1.272
2) Wave a touches the zone, wave b breaks point 1, then wave c:
   - Running Flat : c stays above a's extreme -> reversal candle that touched a Fibonacci level
   - Expanded Flat: c breaks a's extreme      -> reversal candle
   targets 1.414 (close 50%) and 1.618
Stop: the 2-candle extreme of the reversal candle -/+ 0.2%. Moved to entry once price breaks the correction high (low).
No higher-timeframe filter: the Pine version's "trade with the higher timeframe only" option is off (owner's choice;
on 16 data sets it also did better without it — research/README.md).

Execution follows TradingView's broker emulator: the entry fills at the next candle's open, stops/targets fill
inside the candle along open->high->low->close (or open->low->high->close when the open is nearer the low).
"""
TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800}

ZONE_FROM, ZONE_TO, TARGET = 0.382, 0.236, 1.272
FIBS = (0.236, 0.382, 0.5, 0.618, 0.786)
MAX_B, TP1, TP2, TP1_PCT = 1.272, 1.414, 1.618, 50.0
STOP_BUF, PIN_RATIO, MAX_BARS = 0.2, 2.0, 300


def preset_dev(sec):  return 1.5 if sec <= 900 else 3.0 if sec <= 3600 else 5.0 if sec <= 14400 else 8.0 if sec <= 86400 else 15.0
def preset_move(sec): return 4.0 if sec <= 900 else 8.0 if sec <= 3600 else 15.0 if sec <= 14400 else 25.0 if sec <= 86400 else 40.0
def above(a, b, d):   return d * (a - b) > 0


class _Setup:
    def __init__(self, d): self.dir, self.active = d, False
    def lvl(self, x): return self.p0 + x * (self.p1 - self.p0)
    def start(self, p0, p1, bar):
        self.active, self.phase, self.touched = True, 1, False
        self.p0, self.p1, self.a_ext, self.b_ext, self.c_ext, self.start_b = p0, p1, None, None, None, bar


def run_wave_flats(o, h, l, c, ts, timeframe, amount=20, leverage=5, fee=0.0004, start_ts=0, last_signal=None):
    """Backtest on candle arrays (oldest first); entries only on candles at or after start_ts.
    Returns trades: {entry_ts, exit_ts, side, entry, exit, qty, pnl, reason, kind}.
    last_signal (dict): filled with the order (dir, kind, stop, targets, ts) when the last candle triggers an entry —
    the live bot passes closed candles and enters at market."""
    n = len(c); sec = TF_SEC[timeframe]
    dev, mv = preset_dev(sec), preset_move(sec)
    zz_dir, ext_p, ext_b = 1, None, None
    piv_h = piv_hb = piv_l = piv_lb = None
    short_s, long_s = _Setup(-1), _Setup(1)
    trades = []
    pending = None          # entry order placed at a candle close, fills at the next open
    pos = None              # open position
    tr = {}

    def close_leg(qty, price):
        p = pos
        pnl = (price - p["entry"]) * qty * p["dir"] - (p["entry"] * qty + price * qty) * fee
        p["pnl"] += pnl; p["left"] -= qty; p["exit_val"] += price * qty
        return pnl

    for i in range(n):
        # ── fills inside candle i (orders placed at candle i-1's close) ──
        if pending is not None:
            qty = amount * leverage / o[i]
            pos = {"dir": pending["dir"], "entry": o[i], "qty": qty, "left": qty, "pnl": 0.0, "exit_val": 0.0,
                   "entry_ts": ts[i], "kind": pending["kind"], "legs": []}
            pending = None
        if pos is not None:
            d = pos["dir"]
            path = [o[i], h[i], l[i], c[i]] if (h[i] - o[i]) < (o[i] - l[i]) else [o[i], l[i], h[i], c[i]]
            for a, b in zip(path, path[1:]):
                if pos is None: break
                lo_, hi_ = min(a, b), max(a, b)
                # levels crossed along a -> b, in the order price reaches them
                orders = [("SL", tr["stop"])]
                if tr["two"]:
                    if not tr["tp1_hit"]: orders.append(("TP1", tr["tgt1"]))
                    orders.append(("TP2", tr["tgt2"]))
                else:
                    orders.append(("TP", tr["tgt1"]))
                hits = []
                for name, px in orders:
                    is_stop = name == "SL"
                    # a stop is on the losing side, targets on the winning side
                    if is_stop:
                        trig = (d == 1 and b < a and lo_ <= px <= hi_) or (d == -1 and b > a and lo_ <= px <= hi_)
                        gap = (d == 1 and a <= px) or (d == -1 and a >= px)
                    else:
                        trig = (d == 1 and b > a and lo_ <= px <= hi_) or (d == -1 and b < a and lo_ <= px <= hi_)
                        gap = (d == 1 and a >= px) or (d == -1 and a <= px)
                    if gap: hits.append((0, name, a))
                    elif trig: hits.append((abs(px - a), name, px))
                for _, name, px in sorted(hits, key=lambda x: x[0]):
                    if pos is None: break
                    if name == "TP1":
                        q = pos["qty"] * TP1_PCT / 100
                        close_leg(q, px); pos["legs"].append("TP1"); tr["tp1_hit"] = True
                    else:
                        close_leg(pos["left"], px); pos["legs"].append(name)
                        trades.append(_finish(pos, ts[i]))
                        pos = None
        # ── script at candle i's close ──
        new_low = new_high = False
        if ext_p is None:
            ext_p, ext_b = h[i], i
        elif zz_dir == 1:
            if h[i] >= ext_p: ext_p, ext_b = h[i], i
            elif l[i] <= ext_p * (1 - dev / 100):
                new_high, new_high_p, new_high_b = True, ext_p, ext_b
                piv_h, piv_hb, zz_dir, ext_p, ext_b = ext_p, ext_b, -1, l[i], i
        else:
            if l[i] <= ext_p: ext_p, ext_b = l[i], i
            elif h[i] >= ext_p * (1 + dev / 100):
                new_low, new_low_p, new_low_b = True, ext_p, ext_b
                piv_l, piv_lb, zz_dir, ext_p, ext_b = ext_p, ext_b, 1, h[i], i

        if new_low and not short_s.active and piv_h is not None and piv_hb < new_low_b and (piv_h - new_low_p) / piv_h * 100 >= mv:
            short_s.start(piv_h, new_low_p, i)
        if new_high and not long_s.active and piv_l is not None and piv_lb < new_high_b and (new_high_p - piv_l) / piv_l * 100 >= mv:
            long_s.start(piv_l, new_high_p, i)

        in_pos = pos is not None
        entered_short = _process(short_s, i, o, h, l, c, in_pos, False, ts, start_ts, tr)
        entered_long = _process(long_s, i, o, h, l, c, in_pos, entered_short, ts, start_ts, tr)
        if (entered_short or entered_long) and i + 1 < n:
            pending = {"dir": tr["dir"], "kind": tr["kind"]}
        elif (entered_short or entered_long) and last_signal is not None:
            last_signal.update(tr, ts=ts[i])

        # trade management at the close (takes effect from the next candle)
        if pos is not None and not tr["be_done"]:
            d = pos["dir"]
            if above(h[i] if d == 1 else l[i], tr["be"], d):
                tr["stop"], tr["be_done"] = pos["entry"], True

    if pos is not None:
        close_leg(pos["left"], c[-1]); pos["legs"].append("close")
        trades.append(_finish(pos, ts[-1]))
    return trades


def _finish(p, exit_ts):
    reason = "+".join(p["legs"])
    return {"entry_ts": p["entry_ts"], "exit_ts": exit_ts, "side": "long" if p["dir"] == 1 else "short",
            "entry": p["entry"], "exit": p["exit_val"] / p["qty"], "qty": p["qty"], "pnl": p["pnl"],
            "reason": reason, "kind": p["kind"]}


def _process(s, i, o, h, l, c, in_pos, blocked, ts, start_ts, tr):
    if not (s.active and i > s.start_b): return False
    d = s.dir
    hi_x, lo_x = (h[i], l[i]) if d == 1 else (l[i], h[i])
    ext2 = min(l[i], l[i - 1]) if d == 1 else max(h[i], h[i - 1])
    body = abs(c[i] - o[i]); rng = h[i] - l[i]; min_body = max(body, rng * 0.05)
    up_w = h[i] - max(o[i], c[i]); lo_w = min(o[i], c[i]) - l[i]
    if d == 1:
        engulf = c[i] > o[i] and c[i-1] < o[i-1] and c[i] >= o[i-1] and o[i] <= c[i-1]
        pin = rng > 0 and lo_w >= PIN_RATIO * min_body and lo_w >= rng * 0.5 and up_w <= lo_w * 0.5
    else:
        engulf = c[i] < o[i] and c[i-1] > o[i-1] and c[i] <= o[i-1] and o[i] >= c[i-1]
        pin = rng > 0 and up_w >= PIN_RATIO * min_body and up_w >= rng * 0.5 and lo_w <= up_w * 0.5
    rev = engulf or pin
    z_far, z_near = s.lvl(ZONE_FROM), s.lvl(ZONE_TO)
    can_enter = rev and not in_pos and not blocked and ts[i] >= start_ts
    kill, kind = False, ""
    if not above(lo_x, s.p0, d):
        kill = True
    elif s.phase == 1:
        if not s.touched and above(hi_x, s.p1, d):
            s.p1 = hi_x
        else:
            if not above(lo_x, z_far, d): s.touched = True
            if s.touched and (s.a_ext is None or not above(lo_x, s.a_ext, d)): s.a_ext = lo_x
            if s.touched and above(hi_x, s.p1, d):
                s.phase, s.start_b, s.b_ext = 2, i, hi_x
            elif s.touched and can_enter and not above(ext2, z_far, d) and above(c[i], z_near, d):
                kind = "Regular Flat"
    else:
        if not above(s.lvl(MAX_B), hi_x, d):
            kill = True
        else:
            if above(hi_x, s.b_ext, d): s.b_ext = hi_x
            if s.c_ext is None or not above(lo_x, s.c_ext, d): s.c_ext = lo_x
            if can_enter:
                if not above(s.c_ext, s.a_ext, d):
                    kind = "Expanded Flat"
                elif any((not above(ext2, s.lvl(f), d)) and above(c[i], s.lvl(f), d) for f in FIBS):
                    kind = "Running Flat"
    entered = False
    if kind:
        flat = s.phase == 2
        tr.clear()
        tr.update({"dir": d, "kind": kind, "stop": ext2 * (1 - d * STOP_BUF / 100), "two": flat, "tp1_hit": False,
                   "tgt1": s.lvl(TP1) if flat else s.lvl(TARGET), "tgt2": s.lvl(TP2) if flat else None,
                   "be": s.b_ext if flat else s.p1, "be_done": False})
        s.active = False; entered = True
    if s.active and i - s.start_b > MAX_BARS: kill = True
    if kill and s.active: s.active = False
    return entered

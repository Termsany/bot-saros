"""
Phase 1 — end-to-end validation of the live execution adapters on Binance Futures **Demo Trading** (play money).

Runs each adapter the strategies use for real orders against the real exchange, small size, and checks what the
exchange says at every step (not what the bot thinks):

  single-leg adapter (_single_leg_live_entry / _single_leg_live_exit): vol_breakout, rsi2_pullback, trend_breakout
  basket engine, one leg (_phase2_live_basket): listing_short (short)
  basket engine, two legs: momentum_ls, ratio_trend — plus a second leg that the exchange rejects on purpose
  an out-of-band close in the exchange (as if closed by hand in the app), detected by reconcile_live

Per scenario: entry -> position and protective stop on the exchange -> restart (state reloaded from disk, reconcile
twice) with no duplicate and no false recovery -> exit -> exchange flat, own stop gone, risk released, trade recorded.
Always finishes by closing anything left on the symbols it touched and cancelling its own orders.

Then the bot's own cycle ("loop:" scenarios): run_once_breakout / run_once_rsi2 / run_once_tbreak on the exchange
strategy_exchange() hands them, with candles shaped to fire the entry, then the exit, on DOGE — the orders, sizing,
stop and reconciliation are the real cycle's. And every strategy's real command line (bot.py --live --once) with a
tripped kill switch: the whole cycle runs on the Demo account (keys, reconcile, equity, signals) and must not trade.
The adapter scenarios alone missed that the cycle handed six strategies a keyless client.

Refuses to run unless BINANCE_ENV=demo and the private endpoint is demo-fapi.binance.com.

  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.live; set +a; cd /opt/raqm-live && \\
      BINANCE_ENV=demo venv/bin/python scripts/demo_e2e.py --out state/demo_e2e.json'
"""
import argparse, json, os, subprocess, sys, tempfile, time, traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod
from backend.app import risk_manager as riskmgr

MARGIN, LEV = 15.0, 2                     # $15 margin x2 = $30 per leg: above Binance's $5 minimum, tiny for Demo
SINGLE = "DOGE/USDT:USDT"
PAIR = ("XRP/USDT:USDT", "ADA/USDT:USDT")
OOB = "LINK/USDT:USDT"
TOUCHED = {SINGLE, OOB, *PAIR}


class Fail(Exception):
    pass


def check(steps, name, ok, detail=""):
    steps.append({"step": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"   {'✅' if ok else '❌'} {name}{(' — ' + str(detail)[:160]) if detail else ''}", flush=True)
    if not ok: raise Fail(name)


def fresh_books(tmp, tag):
    """Each scenario gets its own state and a permissive risk ledger (this tests execution, not risk sizing)."""
    botmod.STATE_PATH = tmp / f"state_{tag}.json"; botmod.LOG_PATH = tmp / f"state_{tag}.log"
    botmod.RISK_PATH = tmp / f"risk_{tag}.json"
    riskmgr.save_risk_state(botmod.RISK_PATH, riskmgr._default_state({
        "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
        "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
    botmod._ENTRY_BLOCK["reason"] = ""
    return botmod.load_state()


def price(ex, sym): return float(ex.fetch_ticker(sym)["last"])
def qty(ex, sym, side): return botmod._exchange_position_qty(ex, sym, side=side)


def own_trigger_orders(ex, sym, pos_id):
    ids = {botmod_oco_id(pos_id, "sl"), botmod_oco_id(pos_id, "tp")}
    found = []
    for params in ({}, {"trigger": True}, {"stop": True}):
        try: rows = ex.fetch_open_orders(sym, None, None, params) if params else ex.fetch_open_orders(sym)
        except Exception: continue
        found += [o for o in rows or [] if (o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderId")) in ids]
    return {o.get("id"): o for o in found}


def any_own_orders(ex, sym):
    """Every open order of ours (raqm- client id) on the symbol, plain or conditional."""
    out = {}
    for params in ({}, {"trigger": True}, {"stop": True}):
        try: rows = ex.fetch_open_orders(sym, None, None, params) if params else ex.fetch_open_orders(sym)
        except Exception: continue
        out.update({o.get("id"): o for o in rows or [] if str(o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderId") or "").startswith("raqm-")})
    return out


def botmod_oco_id(pos_id, leg):
    from backend.app.oco import _oco_id
    return _oco_id(pos_id, leg)


def restart_and_reconcile(ex, steps, expect):
    """Reload the state file as a fresh process would, reconcile twice; positions must survive, no recovery."""
    state = botmod.load_state()
    botmod.reconcile_live(state, ex); botmod.reconcile_live(state, ex)
    for sym in expect:
        check(steps, f"restart keeps {sym.split('/')[0]}", sym in state["positions"], sorted(state["positions"]))
    check(steps, "restart: no false recovery", not state.get("recovery_required"), state.get("recovery_required"))
    check(steps, "restart: entries not blocked", not botmod._ENTRY_BLOCK["reason"], botmod._ENTRY_BLOCK["reason"])
    return state


def risk_open(strategy, sym):
    return (strategy + ":" + sym) in (riskmgr.load_risk_state(botmod.RISK_PATH).get("open_risk") or {})


# ── scenarios ──
def single_leg(ex, steps, strategy, exit_via_close=False):
    state = botmod.load_state(); px = price(ex, SINGLE)
    pos = botmod._single_leg_live_entry(ex, state, SINGLE, "long", MARGIN, px, px * 0.6, None, strategy)
    check(steps, "entry returned a position", pos is not None, state.get("recovery_required") or botmod._ENTRY_BLOCK["reason"])
    q = qty(ex, SINGLE, "long")
    check(steps, "position on the exchange", q and abs(q - float(pos["qty"])) < 1e-9 * max(1, q) + 1e-6, f"exchange {q} vs bot {pos['qty']}")
    stops = own_trigger_orders(ex, SINGLE, pos["oco_ids"]["pos_id"])
    check(steps, "protective stop on the exchange", len(stops) >= 1, list(stops))
    check(steps, "risk reserved", risk_open(strategy, SINGLE))
    state = restart_and_reconcile(ex, steps, [SINGLE])
    if exit_via_close:
        res = botmod.close_live_position(ex, SINGLE, state["positions"][SINGLE], price(ex, SINGLE))
        check(steps, "close_live_position closed it", not res.get("error") and not res.get("recovery_required"), res.get("error"))
        state["positions"].pop(SINGLE, None); botmod._release_position_risk(SINGLE, pos); botmod.save_state(state)
    else:
        ok = botmod._single_leg_live_exit(ex, state, SINGLE, price(ex, SINGLE), "demo e2e exit")
        check(steps, "exit adapter reported success", ok is not False, state.get("recovery_required"))
    check(steps, "exchange flat after exit", qty(ex, SINGLE, "long") == 0.0)
    check(steps, "own stop cancelled", not own_trigger_orders(ex, SINGLE, pos["oco_ids"]["pos_id"]))
    check(steps, "risk released", not risk_open(strategy, SINGLE))


def basket(ex, steps, strategy, legs_spec, tag):
    state = botmod.load_state(); legs = []
    for i, (sym, side) in enumerate(legs_spec):
        px = price(ex, sym); sl = px * (0.6 if side == "long" else 1.4)
        legs.append(botmod._phase2_leg(sym, side, MARGIN, px, sl, None, strategy, order=i))
    res = botmod._phase2_live_basket(ex, state, strategy, f"demo-e2e-entry:{tag}:{int(time.time())}", legs)
    check(steps, "basket entry filled", res and res.get("status") == "filled", res)
    state = botmod.load_state()
    for sym, side in legs_spec:
        q = qty(ex, sym, side)
        check(steps, f"{sym.split('/')[0]} {side} on the exchange", q and q > 0, q)
        pid = state["positions"][sym]["oco_ids"]["pos_id"]
        check(steps, f"{sym.split('/')[0]} stop on the exchange", len(own_trigger_orders(ex, sym, pid)) >= 1)
    state = restart_and_reconcile(ex, steps, [s for s, _ in legs_spec])
    exits = [{"symbol": s, "side": "close_" + sd, "action": "exit", "position": state["positions"][s], "price": price(ex, s), "order": i,
              "risk_usdt": 0, "notional_usdt": 0, "correlation_group": botmod._correlation_group(s)} for i, (s, sd) in enumerate(legs_spec)]
    pids = {s: state["positions"][s]["oco_ids"]["pos_id"] for s, _ in legs_spec}
    res = botmod._phase2_live_basket(ex, state, strategy, f"demo-e2e-exit:{tag}:{int(time.time())}", exits, reserve=False)
    check(steps, "basket exit filled", res and res.get("status") == "filled", res)
    for sym, side in legs_spec:
        check(steps, f"{sym.split('/')[0]} flat after exit", qty(ex, sym, side) == 0.0)
        check(steps, f"{sym.split('/')[0]} stop cancelled", not own_trigger_orders(ex, sym, pids[sym]))
        check(steps, f"{sym.split('/')[0]} risk released", not risk_open(strategy, sym))


def basket_leg_rejected(ex, steps, strategy):
    """Second leg too small for the exchange's minimum: rejected -> the first leg must be unwound, nothing left."""
    state = botmod.load_state(); a, b = PAIR
    pa, pb = price(ex, a), price(ex, b)
    legs = [botmod._phase2_leg(a, "long", MARGIN, pa, pa * 0.6, None, strategy, order=0),
            botmod._phase2_leg(b, "short", 1.0, pb, pb * 1.4, None, strategy, order=1)]    # $2 notional: below $5
    try: res = botmod._phase2_live_basket(ex, state, strategy, f"demo-e2e-reject:{int(time.time())}", legs)
    except Exception as e: res = {"status": "raised", "error": str(e)}
    check(steps, "basket not reported filled", not (res and res.get("status") == "filled"), res)
    time.sleep(2)
    check(steps, f"{a.split('/')[0]} unwound (flat)", qty(ex, a, "long") == 0.0, qty(ex, a, "long"))
    check(steps, f"{a.split('/')[0]} stop removed after the unwind", not any_own_orders(ex, a),
          "a leftover reduceOnly stop would later close a new position on this coin at a stale price")
    check(steps, f"{b.split('/')[0]} never opened", qty(ex, b, "short") == 0.0)
    state = botmod.load_state()
    check(steps, "no position left in the bot", not {a, b} & set(state["positions"]), sorted(state["positions"]))
    check(steps, "no stuck risk", not risk_open(strategy, a) and not risk_open(strategy, b))


def out_of_band_close(ex, steps):
    state = botmod.load_state(); px = price(ex, OOB)
    pos = botmod._single_leg_live_entry(ex, state, OOB, "long", MARGIN, px, px * 0.6, None, "vol_breakout")
    check(steps, "entry", pos is not None)
    pid = pos["oco_ids"]["pos_id"]
    ex.create_order(OOB, "market", "sell", float(pos["qty"]), None, {"reduceOnly": True})   # "closed by hand in the app"
    time.sleep(2)
    state = botmod.load_state()
    botmod.reconcile_live(state, ex); botmod.reconcile_live(state, ex)
    check(steps, "bot dropped the position", OOB not in state["positions"], sorted(state["positions"]))
    last = (state.get("history") or [{}])[-1]
    check(steps, "close recorded with an exchange price", last.get("symbol") == OOB and float(last.get("exit") or 0) > 0, last)
    check(steps, "own stop cancelled", not own_trigger_orders(ex, OOB, pid))
    check(steps, "no false recovery", OOB not in (state.get("recovery_required") or {}))


DAY_MS = 86_400_000


def candles(strategy, phase, px, n):
    """Daily candles ending with today's open candle, shaped so the strategy's rule fires (prices around px)."""
    want = int(n or 220); n = max(want, 230); today = int(botmod._utc_day(datetime.now(timezone.utc)).timestamp() * 1000)
    closes = [px * (0.6 + 0.35 * i / (n - 2)) for i in range(n - 1)]                 # a steady uptrend
    if strategy == "rsi2_pullback" and phase == "entry": closes[-2:] = [px * 0.93, px * 0.90]   # two down days in it
    if strategy == "rsi2_pullback" and phase == "exit": closes[-1] = px * 1.02                  # close above the 5-day mean
    if strategy == "trend_breakout" and phase == "exit": closes[-1] = px * 0.5                  # close below the 20-day mean
    rows = [[today - (n - 1 - i) * DAY_MS, c, c * 1.002, c * 0.998, c, 1e6] for i, c in enumerate(closes)]
    if strategy == "trend_breakout" and phase == "entry":                                       # today's close breaks the 20-day high
        rows = [[t, c, c, c * 0.998, c, v] for t, _, _, _, c, v in rows]
    return (rows + [[today, px * 0.95, px * 0.95, px * 0.95, px * 0.95, 1e5]])[-want:]


def cycle(ex_unused, steps, strategy):
    """The bot's own cycle on the Demo account: entry from a signal, then the exit from the next day's signal."""
    botmod.CONFIG["enabled_strategies"] = [strategy]
    run, day_key = {"vol_breakout": (botmod.run_once_breakout, "vb_day"), "rsi2_pullback": (botmod.run_once_rsi2, "rsi2_day"),
                    "trend_breakout": (botmod.run_once_tbreak, "tb_day")}[strategy]
    lx = botmod.strategy_exchange()
    check(steps, "the cycle runs on the keyed Demo account", lx.apiKey and "demo-fapi" in str(lx.urls["api"].get("fapiPrivate", "")))
    px = price(lx, SINGLE); real_ohlcv, real_universe = lx.fetch_ohlcv, botmod.volume_universe
    try:
        botmod.volume_universe = lambda ex, n: [SINGLE]
        lx.fetch_ohlcv = lambda sym, tf="1d", since=None, limit=None, params=None: candles(strategy, "entry", px, limit)
        run(lx)
        state = botmod.load_state()
        check(steps, "the cycle opened the trade", SINGLE in state["positions"], state.get("recovery_required") or botmod._ENTRY_BLOCK["reason"])
        pos = state["positions"][SINGLE]; q = qty(lx, SINGLE, "long")
        check(steps, "position on the exchange", q and abs(q - float(pos["qty"])) < 1e-6 * max(1, q), f"exchange {q} vs bot {pos['qty']}")
        notional = q * px
        check(steps, "size = margin x leverage, applied once", abs(notional - MARGIN * LEV) / (MARGIN * LEV) < 0.15, f"${notional:.2f} vs ${MARGIN * LEV}")
        check(steps, "protective stop on the exchange", own_trigger_orders(lx, SINGLE, pos["oco_ids"]["pos_id"]))
        check(steps, "risk reserved", risk_open(strategy, SINGLE))
        run(lx)                                                    # same day again: no second order
        check(steps, "no duplicate on the next cycle", abs((qty(lx, SINGLE, "long") or 0) - q) < 1e-9, qty(lx, SINGLE, "long"))
        state = botmod.load_state(); state[day_key] = "2000-01-01"; botmod.save_state(state)        # next day
        botmod.volume_universe = lambda ex, n: [SINGLE] if strategy != "vol_breakout" else []
        lx.fetch_ohlcv = lambda sym, tf="1d", since=None, limit=None, params=None: candles(strategy, "exit", px, limit)
        run(lx)
        state = botmod.load_state()
        check(steps, "the cycle closed the trade", SINGLE not in state["positions"], state.get("recovery_required") or botmod._ENTRY_BLOCK["reason"])
        check(steps, "exchange flat", qty(lx, SINGLE, "long") == 0.0)
        check(steps, "own stop cancelled", not own_trigger_orders(lx, SINGLE, pos["oco_ids"]["pos_id"]))
        check(steps, "risk released", not risk_open(strategy, SINGLE))
        last = (state.get("history") or [{}])[-1]
        check(steps, "trade recorded with an exchange price", last.get("symbol") == SINGLE and float(last.get("exit") or 0) > 0, last)
        check(steps, "no recovery left", not state.get("recovery_required"), state.get("recovery_required"))
    finally:
        lx.fetch_ohlcv, botmod.volume_universe = real_ohlcv, real_universe


def command_line(ex, steps, strategy):
    """bot.py --live --once exactly as a service would start it, on Demo, with the kill switch tripped: the whole
    cycle must run on the keyed account and place nothing."""
    tmp = Path(tempfile.mkdtemp(prefix=f"cli_{strategy}_"))
    riskmgr.save_risk_state(tmp / "risk_state.json", riskmgr._default_state())
    riskmgr.trip_kill_switch(tmp / "risk_state.json", "demo e2e: command-line smoke must not trade", by="demo_e2e")
    before = {p["symbol"]: p.get("contracts") for p in ex.fetch_positions() if float(p.get("contracts") or 0)}
    env = {**os.environ, "BINANCE_ENV": "demo", "RAQM_RISK_DIR": str(tmp), "PYTHONIOENCODING": "utf-8", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
    r = subprocess.run([sys.executable, str(ROOT / "bot.py"), "--live", "--expect-env", "demo", "--strategy", strategy, "--once",
                        "--leverage", str(LEV), "--amount", str(int(MARGIN)), "--state", str(tmp / "state.json")],
                       capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=900, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    check(steps, "cycle finished", r.returncode == 0, out[-300:])
    check(steps, "no missing-credentials error", "apiKey" not in out, [l for l in out.splitlines() if "apiKey" in l][:2])
    check(steps, "no traceback", "Traceback" not in out, out[out.find("Traceback"):][:300])
    after = {p["symbol"]: p.get("contracts") for p in ex.fetch_positions() if float(p.get("contracts") or 0)}
    check(steps, "nothing traded with the kill switch on", after == before, {"before": before, "after": after})


SCENARIOS = [
    ("vol_breakout", lambda ex, s: single_leg(ex, s, "vol_breakout")),
    ("rsi2_pullback", lambda ex, s: single_leg(ex, s, "rsi2_pullback")),
    ("trend_breakout", lambda ex, s: single_leg(ex, s, "trend_breakout")),
    ("listing_short", lambda ex, s: basket(ex, s, "listing_short", [(SINGLE, "short")], "listing")),
    ("momentum_ls", lambda ex, s: basket(ex, s, "momentum_ls", [(PAIR[0], "long"), (PAIR[1], "short")], "momentum")),
    ("ratio_trend", lambda ex, s: basket(ex, s, "ratio_trend", [(PAIR[0], "long"), (PAIR[1], "short")], "ratio")),
    ("ratio_trend: rejected leg unwound", lambda ex, s: basket_leg_rejected(ex, s, "ratio_trend")),
    ("out-of-band close detected", out_of_band_close),
    ("loop: vol_breakout", lambda ex, s: cycle(ex, s, "vol_breakout")),
    ("loop: rsi2_pullback", lambda ex, s: cycle(ex, s, "rsi2_pullback")),
    ("loop: trend_breakout", lambda ex, s: cycle(ex, s, "trend_breakout")),
    *[(f"cli: {st}", lambda ex, s, st=st: command_line(ex, s, st))
      for st in ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")],
]


def cleanup(ex):
    """Close whatever is still open on the symbols this run touched and cancel our own orders there."""
    left = []
    for sym in sorted(TOUCHED):
        for side in ("long", "short"):
            q = qty(ex, sym, side)
            if q:
                try:
                    ex.create_order(sym, "market", "sell" if side == "long" else "buy", q, None, {"reduceOnly": True})
                    left.append(f"closed {side} {sym} {q}")
                except Exception as e: left.append(f"COULD NOT CLOSE {side} {sym} {q}: {e}")
        for params in ({}, {"trigger": True}):
            try: rows = ex.fetch_open_orders(sym, None, None, params) if params else ex.fetch_open_orders(sym)
            except Exception: continue
            for o in rows or []:
                cid = o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderId") or ""
                if cid.startswith("raqm-"):
                    try: ex.cancel_order(o["id"], sym, params) if params else ex.cancel_order(o["id"], sym); left.append(f"cancelled {cid}")
                    except Exception as e: left.append(f"COULD NOT CANCEL {cid}: {e}")
    return left


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=None); ap.add_argument("--only", default="")
    a = ap.parse_args()
    if botmod.binance_env() != "demo":
        sys.exit("refusing: BINANCE_ENV must be demo (Binance Futures Demo Trading)")
    botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": LEV, "trade_amount_usdt": MARGIN, "notify": False,
                          "use_percent_risk": False, "public_dir": None})
    ex, err = botmod.get_exchange(auth=True)
    if err: sys.exit(f"no keys: {err}")
    host = str(ex.urls["api"].get("fapiPrivate", ""))
    if "demo-fapi.binance.com" not in host:
        sys.exit(f"refusing: private endpoint is {host}, not Binance Demo")
    ex.load_markets()
    bal = ex.fetch_balance(); print(f"Binance Demo — USDT free {(bal.get('USDT') or {}).get('free')} — {host}", flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="demo_e2e_"))
    botmod.ENTRY_RECHECK_S = 2.0
    report = {"started": datetime.now(timezone.utc).isoformat(), "endpoint": host, "scenarios": []}
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    try:
        for name, fn in SCENARIOS:
            if only and name.split(":")[0] not in only and name not in only: continue
            print(f"\n▶ {name}", flush=True); steps = []
            # own books per scenario: "ratio_trend" and "ratio_trend: rejected leg unwound" must not share a state file
            fresh_books(tmp, f"{len(report['scenarios'])}_" + "".join(c if c.isalnum() else "_" for c in name))
            try: fn(ex, steps); ok, err_txt = True, ""
            except Fail as f: ok, err_txt = False, f"failed at: {f}"
            except Exception as e: ok, err_txt = False, f"{type(e).__name__}: {e}"; traceback.print_exc()
            report["scenarios"].append({"name": name, "ok": ok, "error": err_txt, "steps": steps})
            for line in cleanup(ex): print(f"   🧹 {line}", flush=True)
    finally:
        report["cleanup"] = cleanup(ex)
        report["finished"] = datetime.now(timezone.utc).isoformat()
        print("\n=== result ===")
        for s in report["scenarios"]: print(f"{'✅' if s['ok'] else '❌'} {s['name']}{('  — ' + s['error']) if s['error'] else ''}")
        print("cleanup:", report["cleanup"] or "nothing left open")
        if a.out: Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0 if all(s["ok"] for s in report["scenarios"]) else 1)


if __name__ == "__main__":
    main()

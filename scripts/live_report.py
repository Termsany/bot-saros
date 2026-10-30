"""Daily report on the real-orders bots (one per strategy on one account). Read only: it never sends an order.

Per strategy: open positions, trades closed in the last 24 hours and their PnL, totals, and anything waiting for a
person (review marks, expected stops, due exits, basket back-off). Account-wide: balance, the exchange's positions
against the bots' books and the shared risk ledger, and the kill switch. Prints one JSON document.

  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.live; set +a; cd /opt/raqm-live && \\
      BINANCE_ENV=demo venv/bin/python -E -s scripts/live_report.py --env demo'
"""
import argparse, json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod
from backend.app import risk_manager as riskmgr

STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")
base = lambda sym: str(sym).split(":")[0]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--env", choices=["demo", "live"], required=True)
    ap.add_argument("--hours", type=float, default=24.0)
    a = ap.parse_args()
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    ledger_path = Path(os.getenv("RAQM_RISK_DIR") or ("/opt/raqm-risk-demo" if a.env == "demo" else "/opt/raqm-risk")) / "risk_state.json"
    out = {"generated": datetime.now(timezone.utc).isoformat(), "env": a.env, "hours": a.hours, "strategies": {}, "account": {}}

    held = {}                                   # base symbol -> strategy, from the bots' own books
    for s in STRATEGIES:
        f = ROOT / "state" / f"{a.env}-{s}.json"
        if not f.exists():
            out["strategies"][s] = {"state": "no state file (bot never ran)"}; continue
        st = json.loads(f.read_text(encoding="utf-8"))
        recent = [h for h in st.get("history", []) if h.get("time") and datetime.fromisoformat(h["time"]) >= since]
        known = [h for h in recent if h.get("pnl") is not None]
        for sym in st.get("positions", {}): held[base(sym)] = s
        out["strategies"][s] = {
            "open": [{"symbol": base(k), "side": p.get("side"), "entry": p.get("entry"), "qty": p.get("qty"), "sl": p.get("sl"),
                      "opened": p.get("time"), "unprotected": bool(p.get("unprotected") or p.get("sl_unverified"))}
                     for k, p in st.get("positions", {}).items()],
            "closed_recently": len(recent), "pnl_recently": round(sum(float(h["pnl"]) for h in known), 4),
            "closed_with_unknown_pnl": len(recent) - len(known),
            "totals": st.get("stats"),
            "needs_a_person": st.get("recovery_required") or {},
            "expected_stops": list((st.get("protect") or {}).keys()),
            "due_exits": st.get("exit_due") or {},
            "basket_backoff": st.get("basket_backoff") or {},
            "state_updated": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
        }

    try:
        ledger = riskmgr.load_risk_state(ledger_path)
        rows = ledger.get("open_risk") or {}
        out["account"]["kill_switch"] = ledger.get("kill_switch")
        out["account"]["limits"] = ledger.get("limits")
        out["account"]["daily"] = ledger.get("daily")
        ledger_held = {base(r["symbol"]): r["strategy"] for r in rows.values()}
        out["account"]["ledger_rows_by_status"] = {k: sum(1 for r in rows.values() if r.get("status") == k) for k in ("reserved", "open", "recovery")}
    except Exception as e:
        ledger_held = None; out["account"]["ledger_error"] = str(e)

    ex, err = botmod.get_exchange(auth=True)
    if err:
        out["account"]["exchange_error"] = err
    else:
        try:
            bal = ex.fetch_balance(); usdt = bal.get("USDT") or {}
            out["account"]["balance_usdt"] = {"total": usdt.get("total"), "free": usdt.get("free"), "used": usdt.get("used")}
            positions = [p for p in ex.fetch_positions() if float(p.get("contracts") or 0)]
            on_exchange = {base(p["symbol"]): p for p in positions}
            out["account"]["exchange_positions"] = len(on_exchange)
            out["account"]["unrealized_pnl"] = round(sum(float(p.get("unrealizedPnl") or 0) for p in positions), 4)
            out["account"]["by_strategy_unrealized"] = {}
            for sym, p in on_exchange.items():
                s = held.get(sym, "?")
                out["account"]["by_strategy_unrealized"][s] = round(out["account"]["by_strategy_unrealized"].get(s, 0) + float(p.get("unrealizedPnl") or 0), 4)
            out["account"]["on_exchange_not_in_any_book"] = sorted(set(on_exchange) - set(held))
            out["account"]["in_a_book_not_on_exchange"] = sorted(set(held) - set(on_exchange))
            if ledger_held is not None:
                out["account"]["book_vs_ledger_mismatch"] = sorted(sym for sym in set(held) | set(ledger_held)
                                                                   if held.get(sym) != ledger_held.get(sym))
        except Exception as e:
            out["account"]["exchange_error"] = f"{type(e).__name__}: {e}"
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()

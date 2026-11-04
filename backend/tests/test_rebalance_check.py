"""scripts/rebalance_check.py: the real basket against the exchange, read only — a missing stop, a quantity or side
that isn't the exchange's, a position the bot doesn't hold, an order left on a closed coin, a rebalance that didn't run
or a closed leg without an exit price are each a ❌; and it never places, changes or cancels anything."""
import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "backend"))
import rebalance_check as rc
from app import oco

NOW = datetime(2026, 11, 9, 0, 20, tzinfo=timezone.utc)
TODAY = "2026-11-09T00:00:00+00:00"
COINS = [f"C{i}/USDT:USDT" for i in range(10)]


class FakeEx:
    """Positions and open stop orders only; any write call fails the test."""
    def __init__(self, positions, orders):
        self.positions, self.orders, self.writes = positions, orders, []
    def fetch_positions(self): return list(self.positions)
    def fetch_order(self, oid, symbol):
        for o in self.orders:
            if o["id"] == oid and o["symbol"] == symbol: return o
        raise Exception("order not found")
    def fetch_open_orders(self, symbol=None, since=None, limit=None, params=None):
        return [o for o in self.orders if o["symbol"] == symbol]
    def __getattr__(self, name):
        if name.startswith(("create", "cancel", "edit", "set")):
            self.writes.append(name); raise AssertionError(f"write call {name}")
        raise AttributeError(name)


def basket():
    state, positions, orders = {"positions": {}, "history": [], "mom_last": TODAY, "recovery_required": {}}, [], []
    for i, sym in enumerate(COINS):
        side = "long" if i < 5 else "short"; pid = f"raqm-{i:012d}"; sl = f"sl{i}"
        state["positions"][sym] = {"side": side, "qty": 10.0 + i, "oco_ids": {"pos_id": pid, "sl": sl, "tp": None}}
        positions.append({"symbol": sym, "side": side, "contracts": 10.0 + i})
        orders.append({"id": sl, "symbol": sym, "status": "open", "clientOrderId": oco._oco_id(pid, "sl")})
    state["history"] = [{"symbol": f"OLD{i}/USDT:USDT", "side": "long", "entry": 1.0, "exit": 1.1, "qty": 5, "pnl": 0.4, "time": TODAY[:11] + "00:01:00+00:00"} for i in range(10)]
    status = {"env": "live", "updated": (NOW - timedelta(seconds=40)).isoformat(), "entry_block": "", "review": {}}
    return state, status, positions, orders


def run(state, status, positions, orders, day=True, wd=None):
    ex = FakeEx(positions, orders)
    res = rc.check(state, status, ex, NOW, rebalance_day=day, watchdog=wd if wd is not None else {})
    assert not ex.writes
    return [t for ok, t in res if ok is False], res


class RebalanceCheckTests(unittest.TestCase):
    def test_a_clean_rebalance_passes(self):
        bad, res = run(*basket())
        self.assertEqual(bad, [])
        self.assertIn("كله سليم", rc.report(res, True)[0])
        self.assertTrue(any(ok is None and "+4.00" in t for ok, t in res))     # last week's net, information only

    def test_a_missing_stop_is_flagged(self):
        s, st, p, o = basket(); o.pop(3)
        bad, _ = run(s, st, p, o)
        self.assertEqual(len(bad), 1); self.assertIn("C3", bad[0]); self.assertIn("مش لاقيينه", bad[0])

    def test_a_quantity_or_side_not_the_exchanges(self):
        s, st, p, o = basket(); p[0]["contracts"] = 9.0; p[7]["side"] = "long"
        bad, _ = run(s, st, p, o)
        self.assertEqual(sorted(b.split()[0] for b in bad), ["C0", "C7"])

    def test_a_position_the_bot_does_not_hold(self):
        s, st, p, o = basket(); p.append({"symbol": "X/USDT:USDT", "side": "long", "contracts": 1})
        bad, _ = run(s, st, p, o)
        self.assertTrue(any("X" in b and "مش في البوت" in b for b in bad))

    def test_an_order_left_on_a_closed_coin(self):
        s, st, p, o = basket(); o.append({"id": "old", "symbol": "OLD2/USDT:USDT", "status": "open"})
        bad, _ = run(s, st, p, o)
        self.assertTrue(any("OLD2" in b for b in bad))

    def test_a_rebalance_that_did_not_run_today(self):
        s, st, p, o = basket(); s["mom_last"] = "2026-11-03T00:00:00+00:00"; s["history"] = []
        bad, _ = run(s, st, p, o)
        self.assertTrue(any("التبديل اتعمل" in b for b in bad)); self.assertTrue(any("اتقفل 0" in b for b in bad))

    def test_a_closed_leg_without_an_exit_price(self):
        s, st, p, o = basket(); s["history"][4]["exit"] = None
        bad, _ = run(s, st, p, o)
        self.assertTrue(any("اتقفل 10 صفقة، 9" in b for b in bad))

    def test_recovery_a_stale_status_and_a_watchdog_alert(self):
        s, st, p, o = basket(); s["recovery_required"] = {"C1/USDT:USDT": {}}; st["updated"] = (NOW - timedelta(minutes=9)).isoformat()
        bad, _ = run(s, st, p, o, wd={"down:x": {"sent": True, "text": "البوت واقف"}})
        self.assertEqual(len(bad), 3)

    def test_outside_a_rebalance_day_only_the_basket_is_checked(self):
        s, st, p, o = basket(); s["mom_last"] = "2026-11-03T00:00:00+00:00"; s["history"] = []
        bad, res = run(s, st, p, o, day=False)
        self.assertEqual(bad, []); self.assertFalse(any("التبديل" in t for _, t in res))

    def test_setup_installs_the_script_and_the_monday_timer(self):
        s = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/rebalance_check.py", s); self.assertIn("raqm-rebalance-check.timer", s)
        t = (ROOT / "deploy" / "vps" / "raqm-rebalance-check.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=Mon *-*-* 00:20:00 UTC", t)
        u = (ROOT / "deploy" / "vps" / "raqm-rebalance-check.service").read_text(encoding="utf-8")
        self.assertIn("User=raqmlive", u); self.assertIn("--rebalance-day --telegram", u); self.assertIn("ProtectSystem=strict", u)
        # then the costs (development-plan 2.5), from where setup-live.sh installs them, never failing the check
        self.assertIn("ExecStart=-/usr/bin/env RAQM_LIVE_ROOT=/opt/raqm-live", u); self.assertIn("rebalance_costs.py --telegram", u)
        self.assertLess(u.index("rebalance_check.py"), u.index("rebalance_costs.py"))
        self.assertIn('"$T/scripts/rebalance_costs.py" /usr/local/lib/raqm/rebalance_costs.py', s)


if __name__ == "__main__":
    unittest.main()

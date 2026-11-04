"""What a real rebalance cost (scripts/rebalance_costs.py, development-plan 2.5): read from Binance, never an order."""
import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rebalance_costs as rc

DAY = datetime(2026, 11, 9, tzinfo=timezone.utc)
D0 = int(DAY.timestamp() * 1000)


class FakeEx:
    """Binance as ccxt shows it: two coins rebalanced at 00:01, one fee paid in BNB; it fails on any order call."""
    markets = {"AAA/USDT:USDT": {"id": "AAAUSDT", "swap": True, "linear": True},
               "BBB/USDT:USDT": {"id": "BBBUSDT", "swap": True, "linear": True}}
    def load_markets(self): return self.markets
    def fapiPrivateGetIncome(self, p):
        rows = {"COMMISSION": [{"symbol": "AAAUSDT", "time": D0 + 60_000}, {"symbol": "BBBUSDT", "time": D0 + 60_000},
                               {"symbol": "OLDUSDT", "time": D0 + 60_000}],          # a delisted coin: not in markets, skipped
                "FUNDING_FEE": [{"income": "-0.30", "time": D0 - 3_600_000}, {"income": "0.10", "time": D0 - 7_200_000}]}
        return [r for r in rows[p["incomeType"]] if p["startTime"] <= r["time"] < p["endTime"]]
    def fetch_my_trades(self, sym, since=None, limit=None):
        t = D0 + 65_000
        if sym == "AAA/USDT:USDT":
            return [{"side": "buy", "price": 10.1, "amount": 5, "timestamp": t, "fee": {"cost": 0.02525, "currency": "USDT"}},
                    {"side": "buy", "price": 9.0, "amount": 1, "timestamp": D0 - 1, "fee": {"cost": 1, "currency": "USDT"}}]   # before: out
        return [{"side": "sell", "price": 4.9, "amount": 10, "timestamp": t, "fee": {"cost": 0.00004, "currency": "BNB"}}]
    def fetch_ticker(self, sym): return {"last": 600.0}                      # BNB
    def fetch_ohlcv(self, sym, tf, since=None, limit=None):
        close = {"AAA/USDT:USDT": 10.0, "BBB/USDT:USDT": 5.0}[sym]
        if tf == "1d": return [[D0 - 86_400_000, 0, 0, 0, close, 0], [D0, 0, 0, 0, 0, 0]]
        return [[since, close * 1.005 if sym.startswith("AAA") else close * 0.99, 0, 0, 0, 0]]
    def __getattr__(self, name):
        raise AssertionError(f"rebalance_costs called {name}: it must only read")


class RebalanceCostsTests(unittest.TestCase):
    def test_reads_fills_fees_funding_and_both_reference_prices(self):
        fills, funding, close_ref, minute_ref = rc.collect(FakeEx(), DAY, 6)
        self.assertEqual(sorted(f["symbol"] for f in fills), ["AAA/USDT:USDT", "BBB/USDT:USDT"])   # the earlier fill is out
        self.assertAlmostEqual(next(f for f in fills if f["side"] == "sell")["fee_usdt"], 0.024)  # BNB fee in USDT
        self.assertEqual(sorted(funding), [-0.30, 0.10])
        self.assertEqual(close_ref, {"AAA/USDT:USDT": 10.0, "BBB/USDT:USDT": 5.0})
        s = rc.summarize(fills, funding, close_ref, minute_ref)
        self.assertAlmostEqual(s["notional"], 50.5 + 49.0)
        self.assertAlmostEqual(s["fees"], 0.02525 + 0.024)
        self.assertAlmostEqual(s["fees_assumed"], 99.5 * 0.0004)
        # bought 10.1 vs 10.0 close: +0.5 cost; sold 4.9 vs 5.0 close: +1.0 cost
        self.assertAlmostEqual(s["slip_close"], 1.5)
        # vs the minute's open: bought 10.1 vs 10.05 (+0.25), sold 4.9 vs 4.95 (+0.5)
        self.assertAlmostEqual(s["slip_exec"], 0.75)
        self.assertAlmostEqual(s["funding"], -0.20)
        self.assertAlmostEqual(s["total"], 0.04925 + 1.5 + 0.20)

    def test_a_better_price_is_a_negative_cost(self):
        s = rc.summarize([{"symbol": "X", "side": "sell", "price": 11.0, "amount": 1, "fee_usdt": 0.0, "time": D0}], [],
                         {"X": 10.0}, {})
        self.assertAlmostEqual(s["slip_close"], -1.0)
        self.assertEqual(s["slip_exec_notional"], 0)                           # no minute price: not counted as zero

    def test_report_names_each_cost_against_the_backtest(self):
        text = rc.report(rc.summarize(*rc.collect(FakeEx(), DAY, 6)), DAY, 6)
        for part in ("2026-11-09", "2 تنفيذ على 2 عملة", "0.04%", "إقفال 00:00", "الدقيقة", "اتدفع", "التكلفة كلها", "BBB"):
            self.assertIn(part, text)
        self.assertIn("مفيش صفقات", rc.report(rc.summarize([], [], {}, {}), DAY, 6))

    def test_a_fee_in_a_coin_without_a_price_is_counted_as_unknown(self):
        ex = FakeEx(); ex.fetch_ticker = lambda sym: (_ for _ in ()).throw(OSError("no market"))
        s = rc.summarize(*rc.collect(ex, DAY, 6))
        self.assertEqual(s["missing_fee"], 1)
        self.assertIn("من غير رسوم معروفة", rc.report(s, DAY, 6))


if __name__ == "__main__":
    unittest.main()

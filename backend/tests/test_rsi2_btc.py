"""The second RSI-2 paper bot: no new entries while BTC is below its 200-day average (owner, 2026-11-07; research §28)."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_full_review_code as base
botmod = base.botmod

DAY = 86_400_000


def rising_then_dip(n=216):
    """An uptrend with a sharp two-day dip at the end: still above its 200-day average, RSI-2 far below 5."""
    c = [100.0 + i for i in range(n)]
    c[-3] = c[-4] - 10; c[-2] = c[-3] - 10; c[-1] = c[-2]          # the last candle is today's, still open
    return c


class FakeEx:
    def __init__(self, btc_up=True, btc_fails=False):
        self.btc_up, self.btc_fails = btc_up, btc_fails
    def fetch_ohlcv(self, sym, tf, limit=200):
        if sym.startswith("BTC/"):
            if self.btc_fails: raise TimeoutError("down")
            c = [1000.0 + (i if self.btc_up else -i) for i in range(limit)]
        else:
            c = rising_then_dip(limit)
        return [[i * DAY, x, x, x, x, 1.0] for i, x in enumerate(c)]
    def fetch_ticker(self, sym):
        return {"last": rising_then_dip()[-2]}


class Rsi2BtcTests(unittest.TestCase):
    def run_day(self, ex, btc_ma, public_name=None):
        state = {"positions": {}, "stats": {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}, "history": []}
        opened = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            cfg = {"paper_trading": True, "public_dir": d, "notify": False}
            if public_name: cfg["public_name"] = public_name
            with mock.patch.dict(botmod.CONFIG, cfg), mock.patch.dict(botmod.RSI2, {"btc_ma": btc_ma}), \
                 mock.patch.object(botmod, "load_state", return_value=state), mock.patch.object(botmod, "save_state"), \
                 mock.patch.object(botmod, "process_paper_closes"), mock.patch.object(botmod, "_guard_stops"), \
                 mock.patch.object(botmod, "volume_universe", return_value=["SOL/USDT:USDT"]), \
                 mock.patch.object(botmod, "_paper_open", side_effect=lambda st, sym, *a, **k: opened.append(sym)):
                if not public_name: botmod.CONFIG.pop("public_name", None)
                botmod.run_once_rsi2(ex)
            files = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in Path(d).glob("*.json")}
        return opened, files

    def test_without_the_filter_the_dip_is_bought_as_today(self):
        opened, files = self.run_day(FakeEx(btc_up=False), 0)
        self.assertEqual(opened, ["SOL/USDT:USDT"])
        self.assertEqual(list(files), ["rsi2.json"])                         # the first RSI-2 bot's file is unchanged
        self.assertIsNone(files["rsi2.json"]["btc_filter"])

    def test_btc_below_its_average_blocks_the_entry(self):
        opened, files = self.run_day(FakeEx(btc_up=False), 200, "rsi2_btc")
        self.assertEqual(opened, [])
        self.assertEqual(list(files), ["rsi2_btc.json"])
        self.assertFalse(files["rsi2_btc.json"]["btc_filter"]["above"])

    def test_btc_above_its_average_lets_it_in(self):
        opened, files = self.run_day(FakeEx(btc_up=True), 200, "rsi2_btc")
        self.assertEqual(opened, ["SOL/USDT:USDT"])
        self.assertTrue(files["rsi2_btc.json"]["btc_filter"]["above"])

    def test_no_btc_data_means_no_new_entry(self):
        opened, files = self.run_day(FakeEx(btc_fails=True), 200, "rsi2_btc")
        self.assertEqual(opened, [])
        self.assertEqual(files["rsi2_btc.json"]["btc_filter"]["error"], "TimeoutError")


if __name__ == "__main__":
    unittest.main()

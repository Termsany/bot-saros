"""The two paper bots from research/traders_*: Williams volatility breakout and Connors RSI-2 (fake exchange)."""
import os, sys, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod

DAY = 86_400_000


class FakeEx:
    def __init__(self, candles, last):
        self.candles, self.last = candles, last          # {sym: [[ts,o,h,l,c,v], ...]} oldest first; {sym: price}
    def fetch_ohlcv(self, sym, tf, limit=100): return self.candles[sym][-limit:]
    def fetch_ticker(self, sym): return {"last": self.last[sym]}
    def fetch_funding_rate_history(self, sym, since=None, limit=1000): return []


def today_ms(now): return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


class Base(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # Windows can still hold a file open
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "s.json"; botmod.LOG_PATH = Path(self.td.name) / "s.log"
        botmod.CONFIG.update({"paper_trading": True, "leverage": 2, "trade_amount_usdt": 100, "use_percent_risk": False, "public_dir": None})
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg); botmod.STATE_PATH, botmod.LOG_PATH = self._paths; self.td.cleanup()


class BreakoutTests(Base):
    def _candles(self, t0, closes_up=True, prev_range=10.0, today_open=100.0, yclose=99.0):
        rows = []
        for i in range(25, 0, -1):                               # 24 closed days + today's forming candle
            c = 80 + (25 - i) * (1 if closes_up else -1)
            rows.append([t0 - i * DAY, c, c + 1, c - 1, c, 1000])
        rows[-1] = [t0 - DAY, 98, 98 + prev_range / 2, 98 - prev_range / 2, yclose, 1000]   # yesterday: range 10
        rows.append([t0, today_open, today_open, today_open, today_open, 10])
        return rows

    def test_buys_on_the_breakout_and_sells_at_the_next_open(self):
        now = datetime.now(timezone.utc); t0 = today_ms(now)
        ex = FakeEx({"SOL/USDT:USDT": self._candles(t0)}, {"SOL/USDT:USDT": 106.0})   # trigger = 100 + 0.7 x 10 = 107
        with mock.patch.object(botmod, "volume_universe", return_value=["SOL/USDT:USDT"]):
            botmod.run_once_breakout(ex)
            st = botmod.load_state(); self.assertEqual(st["positions"], {})              # 106 < 107: waiting
            self.assertAlmostEqual(st["vb_plan"]["SOL/USDT:USDT"]["trigger"], 107.0)
            ex.last["SOL/USDT:USDT"] = 107.5
            botmod.run_once_breakout(ex)
            pos = botmod.load_state()["positions"]["SOL/USDT:USDT"]
            self.assertAlmostEqual(pos["entry"], 107.5 * 1.001)                            # 0.1% slippage
            self.assertAlmostEqual(pos["qty"], 100 * 2 / pos["entry"])
            ex.last["SOL/USDT:USDT"] = 90.0                                                 # same day: no second entry, no exit
            botmod.run_once_breakout(ex)
            self.assertEqual(len(botmod.load_state()["positions"]), 1)
            # next UTC day: closes at that day's open
            st = botmod.load_state(); st["vb_day"] = (datetime.fromisoformat(st["vb_day"]) - timedelta(days=1)).isoformat(); botmod.save_state(st)
            ex.candles["SOL/USDT:USDT"][-1][1] = 110.0
            botmod.run_once_breakout(ex)
            st = botmod.load_state()
            self.assertEqual(st["positions"], {})
            self.assertEqual(st["history"][-1]["exit"], 110.0); self.assertEqual(st["history"][-1]["reason"], "خروج افتتاح اليوم")

    def test_no_trade_below_the_20_day_average(self):
        now = datetime.now(timezone.utc); t0 = today_ms(now)
        ex = FakeEx({"SOL/USDT:USDT": self._candles(t0, closes_up=False, today_open=60.0, yclose=50.0)}, {"SOL/USDT:USDT": 500.0})
        with mock.patch.object(botmod, "volume_universe", return_value=["SOL/USDT:USDT"]):
            botmod.run_once_breakout(ex)
        self.assertEqual(botmod.load_state()["positions"], {})


class Rsi2Tests(Base):
    def _candles(self, t0, closes):
        rows = [[t0 - (len(closes) - i) * DAY, c, c, c, c, 1000] for i, c in enumerate(closes)]
        return rows + [[t0, closes[-1], closes[-1], closes[-1], closes[-1], 1]]          # today's forming candle

    def test_buys_a_sharp_dip_in_an_uptrend_and_sells_above_the_5_day_average(self):
        now = datetime.now(timezone.utc); t0 = today_ms(now)
        closes = [50 + i * 0.25 for i in range(210)] + [100, 96, 92]                    # long uptrend, then 2 down days
        ex = FakeEx({"ETH/USDT:USDT": self._candles(t0, closes)}, {"ETH/USDT:USDT": 92.0})
        with mock.patch.object(botmod, "volume_universe", return_value=["ETH/USDT:USDT"]):
            botmod.run_once_rsi2(ex)
            pos = botmod.load_state()["positions"]["ETH/USDT:USDT"]
            self.assertAlmostEqual(pos["entry"], 92.0); self.assertAlmostEqual(pos["sl"], 92.0 * 0.6)
            botmod.run_once_rsi2(ex)                                                     # same day: nothing new
            self.assertEqual(len(botmod.load_state()["history"]), 0)
            st = botmod.load_state(); st["rsi2_day"] = "2000-01-01T00:00:00+00:00"; botmod.save_state(st)
            closes2 = closes + [101]                                                     # closes back above its 5-day average
            ex.candles["ETH/USDT:USDT"] = self._candles(t0, closes2); ex.last["ETH/USDT:USDT"] = 101.0
            botmod.run_once_rsi2(ex)
        st = botmod.load_state()
        self.assertEqual(st["positions"], {}); self.assertEqual(st["history"][-1]["exit"], 101.0)
        self.assertGreater(st["history"][-1]["pnl"], 0)

    def test_no_buy_below_the_200_day_average(self):
        now = datetime.now(timezone.utc); t0 = today_ms(now)
        closes = [200 - i * 0.4 for i in range(210)] + [110, 104, 98]                   # downtrend
        ex = FakeEx({"ETH/USDT:USDT": self._candles(t0, closes)}, {"ETH/USDT:USDT": 98.0})
        with mock.patch.object(botmod, "volume_universe", return_value=["ETH/USDT:USDT"]):
            botmod.run_once_rsi2(ex)
        self.assertEqual(botmod.load_state()["positions"], {})

    def test_rsi_wilder_matches_the_research(self):
        sys.path.insert(0, str(ROOT / "research"))
        import numpy as np, traders_study as ts
        c = [100, 101, 99, 97, 98, 95, 96, 99, 94, 92.5]
        self.assertAlmostEqual(botmod.rsi_wilder(c, 2), float(ts.rsi(np.array(c, dtype=float), 2)[-1]), places=6)


if __name__ == "__main__":
    unittest.main()


class TrendBreakoutTests(Base):
    def _candles(self, t0, closes, highs=None):
        highs = highs or [c * 1.01 for c in closes]
        rows = [[t0 - (len(closes) - i) * DAY, c, h, c * 0.99, c, 1000] for i, (c, h) in enumerate(zip(closes, highs))]
        return rows + [[t0, closes[-1], closes[-1], closes[-1], closes[-1], 1]]

    def test_buys_a_20_day_high_in_a_stage_2_uptrend_and_sells_below_the_20_day_average(self):
        now = datetime.now(timezone.utc); t0 = today_ms(now)
        closes = [50 + i * 0.3 for i in range(230)]; highs = [c * 1.01 for c in closes]
        closes[-1] = closes[-2] * 1.05; highs[-1] = closes[-1]                    # closes above the last 20 days' highs
        ex = FakeEx({"SOL/USDT:USDT": self._candles(t0, closes, highs)}, {"SOL/USDT:USDT": closes[-1]})
        with mock.patch.object(botmod, "volume_universe", return_value=["SOL/USDT:USDT"]):
            botmod.run_once_tbreak(ex)
            pos = botmod.load_state()["positions"]["SOL/USDT:USDT"]
            self.assertAlmostEqual(pos["entry"], closes[-1] * 1.0005)
            st = botmod.load_state(); st["tb_day"] = "2000-01-01T00:00:00+00:00"; botmod.save_state(st)
            closes2 = closes + [closes[-1] * 0.8]                                  # a close well below the 20-day average
            ex.candles["SOL/USDT:USDT"] = self._candles(t0, closes2); ex.last["SOL/USDT:USDT"] = closes2[-1]
            botmod.run_once_tbreak(ex)
        st = botmod.load_state()
        self.assertEqual(st["positions"], {}); self.assertEqual(st["history"][-1]["reason"], "قفل تحت متوسط 20 يوم")

    def test_no_buy_without_the_trend_template(self):
        now = datetime.now(timezone.utc); t0 = today_ms(now)
        closes = [150 - i * 0.3 for i in range(230)]; closes[-1] = closes[-2] * 1.2  # a jump inside a downtrend
        ex = FakeEx({"SOL/USDT:USDT": self._candles(t0, closes)}, {"SOL/USDT:USDT": closes[-1]})
        with mock.patch.object(botmod, "volume_universe", return_value=["SOL/USDT:USDT"]):
            botmod.run_once_tbreak(ex)
        self.assertEqual(botmod.load_state()["positions"], {})

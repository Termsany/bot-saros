"""Percent-of-equity position sizing — Phase 2 (1).

run_trend_daily_live_cycle's real default path sizes margin as a percent of the
user's own live equity (bot._fetch_equity_usdt) times their consented
risk_per_trade_pct, bounded by a sane absolute floor/ceiling, while the explicit
margin_usdt param remains available as a back-compat/test override.
"""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import user_live_trading as ult
from app import user_live_activation as ula
from app import user_keys_vault as ukv

from backend.tests.test_user_live_trading import FakeBinance  # type: ignore
SIG_ON = {"price": 100.0, "trend": {"on": True, "ts": 1, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}


class PercentEquityMathTests(unittest.TestCase):
    def test_known_equity_and_risk_pct_produce_expected_margin(self):
        # 10,000 equity * 0.25% = 25 -> below the floor would clamp, but 25 > 10 floor so unclamped.
        self.assertAlmostEqual(ult.percent_equity_margin_usdt(10_000, 0.25), 25.0)

    def test_tiny_equity_clamps_to_the_floor(self):
        self.assertEqual(ult.percent_equity_margin_usdt(100, 0.25), ult.MIN_MARGIN_USDT_FLOOR)

    def test_huge_equity_clamps_to_the_ceiling(self):
        self.assertEqual(ult.percent_equity_margin_usdt(10_000_000, 1.0), ult.MAX_MARGIN_USDT_CEILING)

    def test_invalid_inputs_fail_closed_to_the_floor_not_zero(self):
        self.assertEqual(ult.percent_equity_margin_usdt(None, 0.25), ult.MIN_MARGIN_USDT_FLOOR)
        self.assertEqual(ult.percent_equity_margin_usdt(10_000, 0), ult.MIN_MARGIN_USDT_FLOOR)
        self.assertEqual(ult.percent_equity_margin_usdt(-5, 0.25), ult.MIN_MARGIN_USDT_FLOOR)

    def test_custom_floor_ceiling_are_respected(self):
        self.assertEqual(ult.percent_equity_margin_usdt(1_000_000, 5.0, floor_usdt=50.0, ceiling_usdt=200.0), 200.0)
        self.assertEqual(ult.percent_equity_margin_usdt(1, 0.25, floor_usdt=50.0, ceiling_usdt=200.0), 50.0)


class PercentEquityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.bot_dir = Path(self.tmp.name)
        self.activation_path = self.bot_dir / "user_live_activation.sqlite3"
        self.vault_patch = mock.patch.object(ukv, "VAULT_PATH", self.bot_dir / "user_vault.json")
        self.vault_patch.start()
        import os
        self._old_master = os.environ.get("VAULT_MASTER_KEY")
        from cryptography.fernet import Fernet
        os.environ["VAULT_MASTER_KEY"] = Fernet.generate_key().decode()

    def tearDown(self):
        self.vault_patch.stop()
        import os
        if self._old_master is None: os.environ.pop("VAULT_MASTER_KEY", None)
        else: os.environ["VAULT_MASTER_KEY"] = self._old_master
        self.tmp.cleanup()

    def _enable(self, user_id, exchange="binance", **kw):
        ukv.save_user_keys(user_id, exchange, "AKEY", "ASECRET", "")
        ula.enable_user_live(self.activation_path, user_id=user_id, exchange=exchange,
                              confirm=ula.CONSENT_TEXT, actor=user_id, **kw)

    def test_default_margin_is_derived_from_equity_when_not_overridden(self):
        self._enable("u1", risk_per_trade_pct=1.0, max_aggregate_risk_pct=1.0)
        ex = FakeBinance(balance=50_000.0)  # bot._fetch_equity_usdt reads fetch_balance -> 50,000 free
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                                  analysis=SIG_ON, activation_path=self.activation_path)
        self.assertTrue(result["fired"])
        self.assertEqual(result["action"], "enter")
        # 50,000 * 1% = 500 margin -> well within the sane ceiling, no override needed
        buy = next(o for o in ex.orders if o["side"] == "buy")
        self.assertAlmostEqual(buy["qty"], ult.percent_equity_margin_usdt(50_000.0, 1.0) * 2 / 100.0, places=4)

    def test_explicit_margin_usdt_override_still_works_for_back_compat(self):
        self._enable("u1")
        ex = FakeBinance(balance=50_000.0)
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                                  analysis=SIG_ON, activation_path=self.activation_path,
                                                  margin_usdt=100.0)
        self.assertTrue(result["fired"])
        buy = next(o for o in ex.orders if o["side"] == "buy")
        self.assertAlmostEqual(buy["qty"], 100.0 * 2 / 100.0, places=4)  # leverage=2, price=100


if __name__ == "__main__":
    unittest.main()

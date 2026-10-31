"""Telegram card per closed trade (owner, 2026-10-31): one card per new history row, never repeated after a restart,
never a backlog on upgrade, and the caption alone when the image can't be made or sent."""
import io, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod
import trade_card as tc

ROW = {"symbol": "AIN/USDT:USDT", "side": "long", "entry": 0.14394, "exit": 0.25483, "qty": 1389.47, "pnl": 153.2,
       "reason": "تبديل أسبوعي", "opened": "2026-10-30T00:01:00+00:00", "time": "2026-11-06T00:02:00+00:00"}


class CardTests(unittest.TestCase):
    def test_exit_kinds(self):
        self.assertEqual(tc.exit_kind("وقف المنصة"), "stop")
        self.assertEqual(tc.exit_kind("وقف لونج SL 1.2"), "stop")
        self.assertEqual(tc.exit_kind("الترند وقف"), "rule")                  # trend turned off, not a stop
        self.assertEqual(tc.exit_kind("هدف شورت TP 0.5"), "target")
        self.assertEqual(tc.exit_kind("قفل يدوي من الموقع"), "manual")
        self.assertEqual(tc.exit_kind("تبديل أسبوعي"), "rebalance")
        self.assertEqual(tc.exit_kind(None), "rule")

    def test_outcomes_and_return_on_margin(self):
        c = tc.build(ROW, strategy="momentum_ls", env="demo", leverage=2)
        self.assertEqual((c["outcome"], c["symbol"], round(c["pct"])), ("profit", "AIN", 153))
        self.assertEqual(tc.build({**ROW, "pnl": -80, "reason": "وقف المنصة"}, strategy="x", env="live", leverage=2)["outcome"], "stop")
        self.assertEqual(tc.build({**ROW, "pnl": -5, "reason": "الترند وقف"}, strategy="x", env="live", leverage=2)["outcome"], "loss")
        self.assertEqual(tc.build({**ROW, "reason": "هدف لونج TP 1"}, strategy="x", env="paper", leverage=2)["outcome"], "target")
        pair = tc.build({"symbol": "A|B", "long": "ETH/USDT:USDT", "short": "BTC/USDT:USDT", "pnl": -1}, strategy="ratio_trend", env="demo", leverage=2)
        self.assertEqual((pair["symbol"], pair["side"], pair["pct"]), ("ETH / BTC", "pair", None))

    def test_bad_numbers_dont_raise(self):
        c = tc.build({"symbol": "X/USDT", "pnl": "nan", "entry": None, "time": "garbage"}, strategy="x", env="paper", leverage=0)
        self.assertEqual(c["pnl"], 0.0); self.assertIn("X", tc.caption(c))

    def test_prices(self):
        self.assertEqual([tc.price(v) for v in (64250.5, 182.4, 0.25483, 0.0000123, None)], ["64,250.50", "182.4", "0.25483", "0.0000123", "—"])

    def test_render_is_a_png(self):
        try: from PIL import Image
        except ImportError: self.skipTest("Pillow not installed")
        for row in (ROW, {**ROW, "pnl": -80, "side": "short", "reason": "وقف المنصة"},
                    {"symbol": "A|B", "long": "ETH/USDT:USDT", "short": "BTC/USDT:USDT", "pnl": -1}):
            png = tc.render(tc.build(row, strategy="momentum_ls", env="live", leverage=2))
            self.assertEqual(Image.open(io.BytesIO(png)).size, (tc.W, tc.H))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.patches = [mock.patch.object(botmod, "STATE_PATH", Path(self.td.name) / "s.json"),
                        mock.patch.dict(botmod.CONFIG, {"notify": True, "paper_trading": True}),
                        mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}),
                        mock.patch.object(botmod, "_tg_put")]
        for p in self.patches: p.start()
        self.put = botmod._tg_put
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.td.cleanup()

    def test_no_backlog_on_upgrade_then_one_card_per_new_trade(self):
        s = {"positions": {}, "history": [ROW, ROW]}                    # state from before the upgrade: no marker
        botmod.save_state(s); self.put.assert_not_called()
        s["history"].append({**ROW, "pnl": -3}); botmod.save_state(s); botmod.save_state(s)
        self.assertEqual(self.put.call_count, 1)
        kind, tok, chat, card = self.put.call_args[0][0]
        self.assertEqual((kind, tok, chat, card["outcome"], card["env"]), ("card", "t", "c", "loss", "paper"))

    def test_a_restart_doesnt_repeat(self):
        s = {"positions": {}, "history": []}; botmod.save_state(s)
        s["history"].append(ROW); botmod.save_state(s)
        reloaded = botmod.load_state(); botmod.save_state(reloaded)
        self.assertEqual(self.put.call_count, 1)

    def test_notify_off_sends_nothing_but_keeps_count(self):
        with mock.patch.dict(botmod.CONFIG, {"notify": False}):
            s = {"positions": {}, "history": []}; botmod.save_state(s)
            s["history"].append(ROW); botmod.save_state(s)
        self.put.assert_not_called(); self.assertEqual(s["alerted_closes"], 1)


class WorkerTests(unittest.TestCase):
    def test_caption_alone_when_the_photo_fails(self):
        card = tc.build(ROW, strategy="momentum_ls", env="demo", leverage=2)
        with mock.patch.object(tc, "send_photo", side_effect=OSError("network")), \
             mock.patch.object(botmod, "_tg_text") as text, mock.patch.object(botmod.time, "sleep"):
            botmod._tg_card("t", "c", card)
        text.assert_called_once_with("t", "c", tc.caption(card))


if __name__ == "__main__":
    unittest.main()

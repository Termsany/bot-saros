"""Full review (2026-10-30), API and IPC: a paper bot could swap its commands folder for a link into the real-money
bot's; a FIFO in a request folder froze the bot; a live bot ran paper closes; the LLM lab could run next to the
real-money ledger."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
import bot as botmod
from fastapi import HTTPException


class DropRequestTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.root = Path(self.td.name) / "paper"
        (self.root / "status" / "commands").mkdir(parents=True)
        self.elsewhere = Path(self.td.name) / "live_commands"; self.elsewhere.mkdir()
        import app.main as m; self.m = m
    def tearDown(self): self.td.cleanup()

    def test_request_lands_in_its_folder(self):
        self.m._drop_request(self.root / "status" / "commands", self.root, "a" * 32, {"id": "a" * 32})
        self.assertEqual([p.name for p in (self.root / "status" / "commands").iterdir()], ["close-" + "a" * 32 + ".json"])

    def test_folder_swapped_for_a_link_is_refused(self):
        d = self.root / "status" / "commands"; d.rmdir()
        try: os.symlink(self.elsewhere, d, target_is_directory=True)
        except OSError: self.skipTest("no symlink permission here")
        with self.assertRaises(HTTPException): self.m._drop_request(d, self.root, "b" * 32, {"id": "b" * 32})
        self.assertEqual(list(self.elsewhere.iterdir()), [])


class ReadRequestTests(unittest.TestCase):
    def test_regular_small_file_is_read_and_others_are_not(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            ok = Path(d) / "close-1.json"; ok.write_text('{"id": "x"}', encoding="utf-8")
            big = Path(d) / "close-2.json"; big.write_text('{"id": "' + "x" * 70000 + '"}', encoding="utf-8")
            self.assertEqual(botmod._read_request(ok), {"id": "x"})
            self.assertIsNone(botmod._read_request(big)); self.assertIsNone(botmod._read_request(Path(d) / "missing.json"))
            if hasattr(os, "mkfifo"):
                fifo = Path(d) / "close-3.json"; os.mkfifo(fifo)
                self.assertIsNone(botmod._read_request(fifo))                   # returns at once instead of blocking


class PaperCloseInLiveTests(unittest.TestCase):
    def test_live_bot_ignores_paper_close_requests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, \
             mock.patch.dict(os.environ, {"RAQM_PAPER_IPC": d}), mock.patch.dict(botmod.CONFIG, {"paper_trading": False}):
            (Path(d) / "breakout" / "commands").mkdir(parents=True)
            (Path(d) / "breakout" / "commands" / ("close-" + "c" * 32 + ".json")).write_text('{"id": "%s", "symbol": "SOL/USDT", "at_epoch": %f}' % ("c" * 32, __import__("time").time()))
            state = {"positions": {"SOL/USDT:USDT": {"side": "long", "entry": 1, "qty": 1}}, "history": [], "stats": {"trades": 0, "pnl": 0, "wins": 0, "losses": 0}, "last_trade": {}}
            ex = mock.Mock(); ex.fetch_ticker.return_value = {"last": 1.0}
            with mock.patch.object(botmod, "_paper_close") as pc, mock.patch.object(botmod, "notify"):
                botmod.process_paper_closes(state, ex, "breakout")
            pc.assert_not_called(); self.assertIn("SOL/USDT:USDT", state["positions"])


class LlmLabTests(unittest.TestCase):
    def test_lab_stays_off_on_a_host_sharing_the_real_money_ledger(self):
        import app.main as m
        with mock.patch.dict(os.environ, {"ENABLE_LLM_LAB": "true", "ALLOW_LIVE_TRADING": "", "RAQM_RISK_DIR": "/opt/raqm-risk"}):
            self.assertFalse(m.llm_lab_allowed())
        with mock.patch.dict(os.environ, {"ENABLE_LLM_LAB": "true", "ALLOW_LIVE_TRADING": "", "RAQM_RISK_DIR": ""}):
            self.assertTrue(m.llm_lab_allowed())


if __name__ == "__main__":
    unittest.main()

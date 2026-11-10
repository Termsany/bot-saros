"""Daily backup of the real-orders bots' records (scripts/backup.py, owner 2026-11-01)."""
import io, sqlite3, sys, tarfile, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import backup

NOW = datetime(2026, 11, 1, 3, 30, tzinfo=timezone.utc)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = Path(self.td.name)
        self.state, self.risk = d / "state", d / "risk"
        self.state.mkdir(); self.risk.mkdir(); (self.state / "first-start").mkdir()
        (self.state / "demo-trend_daily.json").write_text('{"positions": {}}', encoding="utf-8")
        (self.state / "first-start" / "x.json").write_text("{}", encoding="utf-8")
        (self.state / "demo-trend_daily.json.tmp").write_text("half", encoding="utf-8")
        db = sqlite3.connect(self.risk / "risk_state.sqlite3"); db.execute("create table t (v)"); db.execute("insert into t values (7)")
        db.commit(); self.open_db = db                                    # still open, as a bot would hold it
    def tearDown(self):
        self.open_db.close(); self.td.cleanup()

    def members(self, data):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}

    def test_every_record_goes_in_and_half_written_files_do_not(self):
        data, n = backup.build(NOW, {"state": self.state, "risk-demo": self.risk, "absent": Path(self.td.name) / "nope"})
        self.assertEqual(set(self.members(data)), {"raqm-backup-20261101/state/demo-trend_daily.json",
                                                   "raqm-backup-20261101/state/first-start/x.json",
                                                   "raqm-backup-20261101/risk-demo/risk_state.sqlite3"})
        self.assertEqual(n, 3)

    def test_a_ledger_in_use_is_copied_whole_and_readable(self):
        data, _ = backup.build(NOW, {"risk-demo": self.risk})
        out = Path(self.td.name) / "restored.sqlite3"
        out.write_bytes(self.members(data)["raqm-backup-20261101/risk-demo/risk_state.sqlite3"])
        db = sqlite3.connect(out); self.assertEqual(db.execute("select v from t").fetchall(), [(7,)]); db.close()

    def test_a_failure_says_so_in_the_chat(self):
        sent = []
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), \
             mock.patch.object(backup, "build", side_effect=OSError("disk")), \
             mock.patch.object(backup, "_post", side_effect=lambda m, f, files=None: sent.append((m, f))):
            with self.assertRaises(OSError): backup.main()
        self.assertEqual(sent[0][0], "sendMessage"); self.assertIn("disk", sent[0][1]["text"])

    def test_the_document_is_sent_silently(self):
        sent = []
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), \
             mock.patch.object(backup, "build", return_value=(b"x", 1)), \
             mock.patch.object(backup, "_post", side_effect=lambda m, f, files=None: sent.append((m, f, files))):
            backup.main()
        m, f, files = sent[0]
        self.assertEqual((m, f["disable_notification"]), ("sendDocument", "true")); self.assertIn("document", files)

    def test_the_unit_can_open_the_ledgers_and_setup_installs_it(self):
        unit = (ROOT / "deploy" / "vps" / "raqm-backup.service").read_text(encoding="utf-8")
        paths = " ".join(l.split("=", 1)[1] for l in unit.splitlines() if l.startswith("ReadWritePaths=")).split()
        for name in ("risk-demo", "risk-live"): self.assertIn(f"-{backup.SOURCES[name].as_posix()}", paths)
        setup = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        for s in ("scripts/backup.py", "raqm-backup.timer", "enable --now raqm-backup.timer"): self.assertIn(s, setup)


if __name__ == "__main__":
    unittest.main()

"""scripts/restore_check.py: an archive made by backup.build restores and passes; a damaged ledger, a missing real
ledger, positions that differ from today's are each a ❌; it never unpacks into an existing folder, nor a link, an
absolute path or '..' from the archive."""
import io, json, sqlite3, sys, tarfile, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import backup, restore_check as rcheck

NOW = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)


class RestoreCheckTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name)
        state, live, demo = self.d / "state", self.d / "risk-live", self.d / "risk-demo"
        for p in (state, live, demo): p.mkdir()
        (state / "live-momentum_ls.json").write_text(json.dumps({"positions": {"A/USDT:USDT": {}, "B/USDT:USDT": {}}}), encoding="utf-8")
        (state / "demo-trend_daily.json").write_text(json.dumps({"positions": {"C/USDT:USDT": {}}}), encoding="utf-8")
        (state / "demo-ratio_trend.json").write_text(json.dumps({"positions": {}, "pairs": {"BTC-ETH": {}}}), encoding="utf-8")
        (state / "demo_e2e_20261029-0136.json").write_text(json.dumps({"positions": {}}), encoding="utf-8")   # not a bot's state
        for db in (live / "risk_state.sqlite3", demo / "risk_state.sqlite3"):
            con = sqlite3.connect(db); con.execute("create table open_risk(strategy text, symbol text)")
            con.execute("insert into open_risk values('momentum_ls','A')"); con.commit(); con.close()
        self.sources = {"state": state, "risk-demo": demo, "risk-live": live}

    def tearDown(self):
        self.td.cleanup()

    def archive(self, sources=None):
        data, n = backup.build(NOW, sources or self.sources)
        p = self.d / "raqm-backup.tar.gz"; p.write_bytes(data); return p

    def bad(self, res):
        return [t for ok, t in res if not ok]

    def test_a_backup_restores_and_matches_today(self):
        top = rcheck.unpack(self.archive(), self.d / "out")
        self.assertEqual(top.name, "raqm-backup-20261104")
        res = rcheck.verify(top, compare=self.sources["state"])
        self.assertEqual(self.bad(res), [])
        self.assertTrue(any("2 صفقة في النسخة = اللي شغالة" in t for _, t in res))
        self.assertTrue(any(t.startswith("demo-ratio_trend.json: 1 صفقة") for _, t in res))   # a pair counts
        self.assertFalse(any("demo_e2e" in t for _, t in res))

    def test_a_pair_closed_since_the_backup(self):
        top = rcheck.unpack(self.archive(), self.d / "out")
        (self.sources["state"] / "demo-ratio_trend.json").write_text(json.dumps({"positions": {}, "pairs": {}}), encoding="utf-8")
        self.assertTrue(any("demo-ratio_trend" in t for t in self.bad(rcheck.verify(top, compare=self.sources["state"]))))

    def test_positions_changed_since_the_backup(self):
        top = rcheck.unpack(self.archive(), self.d / "out")
        (self.sources["state"] / "live-momentum_ls.json").write_text(json.dumps({"positions": {"Z/USDT:USDT": {}}}), encoding="utf-8")
        self.assertTrue(any("live-momentum_ls" in t for t in self.bad(rcheck.verify(top, compare=self.sources["state"]))))

    def test_a_damaged_ledger_and_a_missing_real_ledger(self):
        top = rcheck.unpack(self.archive(), self.d / "out")
        (top / "risk-demo" / "risk_state.sqlite3").write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
        (top / "risk-live" / "risk_state.sqlite3").unlink()
        bad = self.bad(rcheck.verify(top))
        self.assertTrue(any("risk-live/risk_state.sqlite3" in t for t in bad))
        self.assertTrue(any("SQLite" in t and "risk-demo" in t for t in bad))

    def test_never_into_an_existing_folder(self):
        (self.d / "out").mkdir()
        with self.assertRaises(FileExistsError):
            rcheck.unpack(self.archive(), self.d / "out")

    def test_an_archive_escaping_its_folder_is_refused(self):
        for name, link in (("../evil.json", False), ("/abs.json", False), ("raqm-backup-x/state/l", True)):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                info = tarfile.TarInfo(name)
                if link: info.type = tarfile.SYMTYPE; info.linkname = "/opt/raqm-risk/risk_state.sqlite3"; tar.addfile(info)
                else: info.size = 2; tar.addfile(info, io.BytesIO(b"{}"))
            p = self.d / f"evil{hash(name)}.tar.gz"; p.write_bytes(buf.getvalue())
            with self.assertRaises(ValueError, msg=name):
                rcheck.unpack(p, self.d / f"out{hash(name)}")

    def test_setup_installs_it(self):
        self.assertIn("scripts/restore_check.py", (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

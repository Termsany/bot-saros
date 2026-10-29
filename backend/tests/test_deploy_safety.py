"""Nothing that root runs may sit where a less privileged user can write (second pre-production review, 2026-10-29)."""
import re, unittest
from pathlib import Path
VPS = Path(__file__).resolve().parent.parent.parent / "deploy" / "vps"


class UpdaterTests(unittest.TestCase):
    def test_root_timer_runs_a_root_owned_copy(self):
        unit = (VPS / "api" / "raqm-api-update.service").read_text(encoding="utf-8")
        self.assertNotRegex(unit, r"(?m)^User=")                                  # runs as root...
        self.assertRegex(unit, r"(?m)^ExecStart=/bin/sh /usr/local/sbin/raqm-api-update$")   # ...so only root's file
        self.assertNotIn("/opt/raqm-api/update.sh", re.sub(r"(?m)^#.*$", "", unit))

    def test_installer_takes_the_folder_back(self):
        s = (VPS / "api" / "install-updater.sh").read_text(encoding="utf-8")
        self.assertIn("install -m 755 -o root -g root \"$HERE/update.sh\" /usr/local/sbin/raqm-api-update", s)
        self.assertIn("chown root:raqmapi /opt/raqm-api", s)
        self.assertIn("rm -f /opt/raqm-api/update.sh", s)

    def test_auto_deploy_freezes_once_a_real_money_bot_exists(self):
        s = (VPS / "api" / "update.sh").read_text(encoding="utf-8")
        self.assertIn("real_money_bot()", s)
        self.assertIn("--expect-env demo", s)


class SetupLiveTests(unittest.TestCase):
    S = (VPS / "setup-live.sh").read_text(encoding="utf-8")

    def test_only_key_lines_reach_the_live_env_file(self):
        self.assertIn("^(BINANCE_API_KEY|BINANCE_SECRET|BINANCE_LIVE_ACCOUNT)=", self.S)
        self.assertNotIn('install -o raqmlive -g raqmlive -m 600 "$B/.env.demo"', self.S)   # no whole-file copy

    def test_root_never_writes_through_the_shared_folders(self):
        code = "\n".join(l for l in self.S.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("backup(", code)                               # the ledger migration ran root's sqlite there
        self.assertNotRegex(code, r"(chmod|chown)(?! -h)[^\n]*/opt/raqm-(risk|ipc)")
        self.assertNotRegex(code, r"install -d[^\n]*/opt/raqm-(risk|ipc)")

    def test_python_environment_is_locked(self):
        unit = (VPS / "raqm-trend-demo.service").read_text(encoding="utf-8")
        self.assertRegex(unit, r"(?m)^ExecStart=/opt/raqm-live/venv/bin/python -E -s ")
        self.assertRegex(unit, r"(?m)^UnsetEnvironment=.*PYTHONPATH")


if __name__ == "__main__":
    unittest.main()

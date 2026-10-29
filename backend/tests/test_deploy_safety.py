"""Nothing that root runs may sit where a less privileged user can write (second pre-production review, 2026-10-29)."""
import re, subprocess, tempfile, unittest
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


class GroupMembershipTests(unittest.TestCase):
    """Third pre-production review, finding 2(ii) HIGH: /opt/raqm-risk and /opt/raqm-ipc-paper are
    <owner>:raqmapi setgid dirs with files already chmod 660 by risk_manager.py/live_activation.py —
    but group PERMISSION bits are useless without group MEMBERSHIP. raqmlive/raqm were only ever in
    their own primary group on the live server, never in raqmapi, so whichever side didn't create a
    given file first still couldn't open it."""

    def test_raqmlive_joins_the_api_group(self):
        s = (VPS / "setup-live.sh").read_text(encoding="utf-8")
        self.assertRegex(s, r"(?m)^usermod -aG raqmapi raqmlive$")
        # must run after the user exists, not before
        self.assertLess(s.index("useradd --system"), s.index("usermod -aG raqmapi raqmlive"))

    def test_paper_bot_joins_the_api_group(self):
        s = (VPS / "setup-paper-ipc.sh").read_text(encoding="utf-8")
        self.assertRegex(s, r"(?m)^usermod -aG raqmapi raqm$")


class RealMoneyBotDetectionTests(unittest.TestCase):
    """Third pre-production review, finding 3 HIGH: real_money_bot()'s SECOND grep scanned the WHOLE
    unit file for the literal text '--expect-env demo', including comments — not just the ExecStart
    line. A copied-and-edited real-money unit file that still has that text in a leftover comment made
    this wrongly return 1 (not real-money), leaving automatic GitHub-triggered updates ON for it.

    Runs the actual real_money_bot() function body extracted from update.sh (not a reimplementation)
    against a fixture unit file, with the hardcoded /etc/systemd/system glob parameterized so this can
    run without touching any real systemd state."""

    def _real_money_bot(self, unit_glob):
        s = (VPS / "api" / "update.sh").read_text(encoding="utf-8")
        m = re.search(r"(?ms)^real_money_bot\(\)\s*\{.*?\n\}\n", s)
        self.assertIsNotNone(m, "real_money_bot() not found in update.sh")
        func_src = m.group(0).replace("/etc/systemd/system/raqm-*.service", unit_glob)
        script = func_src + "\nreal_money_bot\n"
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    def test_copied_demo_comment_does_not_hide_a_real_money_live_flag(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            unit = Path(d) / "raqm-newbot.service"
            unit.write_text(
                "[Unit]\n"
                "Description=Copied from raqm-trend-demo.service (--expect-env demo) for the new real-money bot\n"
                "[Service]\n"
                "ExecStart=/opt/raqm-live/venv/bin/python bot.py --live --strategy trend_daily\n")
            r = self._real_money_bot(str(Path(d) / "*.service"))
        self.assertEqual(r.returncode, 0, "a --live unit with no --expect-env demo on ExecStart must be real-money")

    def test_demo_unit_with_expect_env_on_execstart_is_not_real_money(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            unit = Path(d) / "raqm-trend-demo.service"
            unit.write_text(
                "[Service]\n"
                "ExecStart=/opt/raqm-live/venv/bin/python bot.py --live --strategy trend_daily --expect-env demo\n")
            r = self._real_money_bot(str(Path(d) / "*.service"))
        self.assertNotEqual(r.returncode, 0)

    def test_no_live_flag_is_not_real_money(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            unit = Path(d) / "raqm-paper.service"
            unit.write_text("[Service]\nExecStart=/opt/raqm-bot/venv/bin/python bot.py --strategy trend_daily\n")
            r = self._real_money_bot(str(Path(d) / "*.service"))
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

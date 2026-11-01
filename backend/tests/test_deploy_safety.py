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
        for name in ("raqm-demo@.service", "raqm-live@.service"):
            unit = (VPS / name).read_text(encoding="utf-8")
            self.assertRegex(unit, r"(?m)^ExecStart=/opt/raqm-live/venv/bin/python -E -s ")
            self.assertRegex(unit, r"(?m)^UnsetEnvironment=.*PYTHONPATH")


class SharedGroupTests(unittest.TestCase):
    """Full review (2026-10-30): sharing through raqmapi's group let the paper user and the real-money user write the
    API's code, venv, the risk ledger and the activation record. Each shared folder now has its own two-user group."""
    LIVE = (VPS / "setup-live.sh").read_text(encoding="utf-8")
    PAPER = (VPS / "setup-paper-ipc.sh").read_text(encoding="utf-8")

    def test_nobody_joins_the_api_group(self):
        for name, s in (("setup-live.sh", self.LIVE), ("setup-paper-ipc.sh", self.PAPER)):
            self.assertNotRegex(s, r"(?m)^[^#]*usermod -aG raqmapi ", name)

    def test_live_and_api_share_raqmrisk_only(self):
        self.assertIn("usermod -aG raqmrisk raqmlive; usermod -aG raqmrisk raqmapi", self.LIVE)
        self.assertIn("gpasswd -d raqmlive raqmapi", self.LIVE)
        self.assertIn("chown -h raqmlive:raqmrisk", self.LIVE)

    def test_paper_tree_is_root_owned_down_to_each_bot(self):
        self.assertIn("usermod -aG raqmpaper raqm; usermod -aG raqmpaper raqmapi", self.PAPER)
        self.assertIn("gpasswd -d raqm raqmapi", self.PAPER)
        self.assertIn('own_dir "$P/$b" root:raqmpaper 0750', self.PAPER)
        self.assertIn('own_dir "$P/$b/commands" raqmapi:raqmpaper', self.PAPER)


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
            r = self._real_money_bot(Path(d).as_posix() + "/*.service")
        self.assertEqual(r.returncode, 0, "a --live unit with no --expect-env demo on ExecStart must be real-money")

    def test_demo_unit_with_expect_env_on_execstart_is_not_real_money(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            unit = Path(d) / "raqm-trend-demo.service"
            unit.write_text(
                "[Service]\n"
                "ExecStart=/opt/raqm-live/venv/bin/python bot.py --live --strategy trend_daily --expect-env demo\n")
            r = self._real_money_bot(Path(d).as_posix() + "/*.service")
        self.assertNotEqual(r.returncode, 0)

    def test_a_user_bot_on_real_money_in_a_drop_in_is_found(self):
        # Phase 2: raqm-user@.service runs nothing itself; the provisioner's drop-in holds the real command
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            (Path(d) / "raqm-user@.service").write_text("[Service]\nExecStart=/bin/false\n", encoding="utf-8")
            dd = Path(d) / "raqm-user@u--trend_daily.service.d"; dd.mkdir()
            (dd / "user.conf").write_text("[Service]\nExecStart=\nExecStart=/opt/raqm-users/code/venv/bin/python bot.py --live --expect-env live\n", encoding="utf-8")
            self.assertEqual(self._real_money_bot(Path(d).as_posix() + "/raqm-*.service").returncode, 0)
            (dd / "user.conf").write_text("[Service]\nExecStart=\nExecStart=/opt/raqm-users/code/venv/bin/python bot.py --live --expect-env demo\n", encoding="utf-8")
            self.assertNotEqual(self._real_money_bot(Path(d).as_posix() + "/raqm-*.service").returncode, 0)

    def test_no_live_flag_is_not_real_money(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            unit = Path(d) / "raqm-paper.service"
            unit.write_text("[Service]\nExecStart=/opt/raqm-bot/venv/bin/python bot.py --strategy trend_daily\n")
            r = self._real_money_bot(Path(d).as_posix() + "/*.service")
        self.assertNotEqual(r.returncode, 0)


class ManualDeployShaTests(unittest.TestCase):
    """Third pre-production review, finding 6 MEDIUM: '--manual' used to skip the freeze check but still
    fall through to the script's unconditional tail, which always deploys origin/main's CURRENT tip —
    not the commit a human actually reviewed. The invocation contract must become
    'raqm-api-update --manual <full 40-char sha>', mirroring setup-live.sh's own <sha> convention,
    with the same sha validation setup-live.sh already uses."""
    S = (VPS / "api" / "update.sh").read_text(encoding="utf-8")

    def test_manual_requires_a_sha_argument_like_setup_live_sh_does(self):
        self.assertIn("--manual", self.S)
        self.assertRegex(self.S, r"\$\{2:-\}")                    # a second positional argument is read
        self.assertRegex(self.S, r"\^\[0-9a-f\]\{40\}\$")         # same 40-hex-char sha pattern setup-live.sh uses

    def test_manual_path_exits_before_the_unconditional_main_tip_merge(self):
        # the manual branch must exit on its own before the script's shared tail, which always deploys
        # origin/main's current tip regardless of what sha was reviewed
        m = re.search(r'if \[ "\$\{1:-\}" = "--manual" \].*?\nfi\n', self.S, re.S)
        self.assertIsNotNone(m, "no dedicated --manual branch found")
        manual_block = m.group(0)
        self.assertIn("exit 0", manual_block)
        self.assertNotIn("git merge -q --ff-only origin/main", manual_block)

    def test_sha_validation_rejects_missing_and_malformed_shas_but_accepts_a_well_formed_one(self):
        m = re.search(r"grep -qE '(\^\[0-9a-f\]\{40\}\$)'", self.S)
        self.assertIsNotNone(m, "sha validation regex not found")
        pattern = m.group(1)

        def matches(sha):
            r = subprocess.run(["sh", "-c", f"echo \"$1\" | grep -qE '{pattern}'", "sh", sha], capture_output=True)
            return r.returncode == 0

        self.assertFalse(matches(""))                 # missing
        self.assertFalse(matches("not-a-sha"))        # malformed
        self.assertFalse(matches("a" * 39))           # one char short
        self.assertFalse(matches("g" * 40))           # right length, not hex
        self.assertTrue(matches("a" * 40))             # well-formed


class KeyOverwriteGuardTests(unittest.TestCase):
    """Third pre-production review, finding 7 MEDIUM: if $SRCENV's lines don't match the $KEYS regex
    exactly as expected (different quoting, leading whitespace, a renamed variable...), grep matches
    nothing, '|| true' swallows that, and the extracted file is installed EMPTY over the existing,
    presumably-correct $L/.env.live — destroying the real keys on a re-run of this idempotent script.

    Runs the actual key-sync block extracted from setup-live.sh (not a reimplementation) against a
    fixture directory tree; only the -o/-g ownership flags on 'install' are stripped for the harness
    (this test doesn't run as root), the guard logic under test is untouched."""

    @staticmethod
    def _key_sync_block():
        s = (VPS / "setup-live.sh").read_text(encoding="utf-8")
        m = re.search(r'KEYS=.*?\nif \[ -f "\$SRCENV" \].*?\nfi\n', s, re.S)
        assert m, "key-sync block not found in setup-live.sh"
        return re.sub(r"install -o raqmlive -g raqmlive ", "install ", m.group(0))

    def _run(self, L, B, T):
        script = f'set -eu\nL="{L.as_posix()}"; B="{B.as_posix()}"; T="{T.as_posix()}"\n' + self._key_sync_block()
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    def test_an_unmatched_rerun_source_does_not_wipe_the_existing_live_keys(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)
            L, B, T = d / "L", d / "B", d / "T"
            L.mkdir(); B.mkdir(); T.mkdir()
            # a re-run: $L/.env.live already exists, but in a format (spaces around '=') the $KEYS
            # regex doesn't match -> extraction into $T/env.live would be empty
            (L / ".env.live").write_text("BINANCE_API_KEY = realkey\nBINANCE_SECRET = realsecret\n")
            r = self._run(L, B, T)
        self.assertNotEqual(r.returncode, 0, "must abort rather than silently install an empty key file")

    def test_a_normal_rerun_with_matching_keys_still_succeeds(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)
            L, B, T = d / "L", d / "B", d / "T"
            L.mkdir(); B.mkdir(); T.mkdir()
            (L / ".env.live").write_text("BINANCE_API_KEY=realkey\nBINANCE_SECRET=realsecret\n")
            r = self._run(L, B, T)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("BINANCE_API_KEY=realkey", (L / ".env.live").read_text())

    def test_first_time_setup_with_no_existing_live_env_still_proceeds(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)
            L, B, T = d / "L", d / "B", d / "T"
            L.mkdir(); B.mkdir(); T.mkdir()
            (B / ".env.demo").write_text("BINANCE_API_KEY=demokey\nBINANCE_SECRET=demosecret\n")
            r = self._run(L, B, T)
            self.assertEqual(r.returncode, 0, r.stderr)   # nothing existing to destroy: fine to proceed


if __name__ == "__main__":
    unittest.main()

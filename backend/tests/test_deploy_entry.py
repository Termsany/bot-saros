"""deploy/vps/deploy.sh, the one way code reaches the VPS (2026-11-11). It runs as root next to the real-money bots, so
each promise it makes is pinned here: a sha on origin/main only, files from git only (checked after), the previous
commit printed, real-money units never touched, Demo by name only, every paper bot covered, the page's owner and mode.

The behaviour tests source the real script (RAQM_DEPLOY_LIB=1 defines its functions without running it) and call its
functions with a fake `systemctl` on PATH that records every call — nothing here needs root or a server."""
import os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

VPS = Path(__file__).resolve().parent.parent.parent / "deploy" / "vps"
DEPLOY = (VPS / "deploy.sh").read_text(encoding="utf-8")       # universal newlines: LF even from a Windows checkout
CODE = "\n".join(l for l in DEPLOY.splitlines() if not l.lstrip().startswith("#"))
SH = shutil.which("sh")

FAKE_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$FAKE/calls"
case "$1" in
    cat) [ -f "$FAKE/units/$2" ] && cat "$FAKE/units/$2"; exit 0;;
    is-active|is-enabled) v=$(grep -F "$1 $2 " "$FAKE/answers" 2>/dev/null | awk '{print $3}')
        if [ -n "$v" ]; then echo "$v"; else echo inactive; fi; exit 0;;
esac
exit 0
"""


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           "-c", "core.autocrlf=false", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(SH, "needs a POSIX sh")
class _Harness(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        (self.d / "lib.sh").write_text(DEPLOY, encoding="utf-8", newline="\n")
        self.fake = self.d / "fake"; (self.fake / "units").mkdir(parents=True)
        (self.fake / "answers").write_text("", encoding="utf-8")
        b = self.d / "bin"; b.mkdir()
        (b / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8", newline="\n")
        os.chmod(b / "systemctl", 0o755)
        self.bin = b

    def run_lib(self, body, **env):
        e = dict(os.environ, FAKE=self.fake.as_posix(), RAQM_DEPLOY_LIB="1",
                 PATH=self.bin.as_posix() + os.pathsep + os.environ.get("PATH", ""), **env)
        script = f'. "{(self.d / "lib.sh").as_posix()}"\n' + body
        return subprocess.run([SH, "-c", script], capture_output=True, text=True, env=e)

    def calls(self):
        p = self.fake / "calls"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def unit(self, name, execstart):
        (self.fake / "units" / name).write_text(f"[Service]\nExecStart={execstart}\n", encoding="utf-8", newline="\n")

    def answer(self, line):
        with open(self.fake / "answers", "a", encoding="utf-8", newline="\n") as f:
            f.write(line + " \n")


class ShaTests(_Harness):
    def setUp(self):
        super().setUp()
        o = self.d / "origin"; o.mkdir()
        git(o, "init", "-q")
        (o / "a.txt").write_bytes(b"one\n")
        git(o, "add", "a.txt"); git(o, "commit", "-qm", "main")
        self.main_sha = git(o, "rev-parse", "HEAD")
        git(o, "checkout", "-qb", "side")
        (o / "a.txt").write_bytes(b"two\n")
        git(o, "commit", "-qam", "side")
        self.side_sha = git(o, "rev-parse", "HEAD")
        git(o, "checkout", "-q", "main")
        self.src = self.d / "src"
        git(self.d, "clone", "-q", o.as_posix(), self.src.as_posix())
        git(self.src, "fetch", "-q", "origin", "side:refs/remotes/origin/side")   # the commit is there, just not on main

    def check(self, sha):
        return self.run_lib(f'check_sha "{sha}"', RAQM_SRC=self.src.as_posix())

    def test_refuses_a_commit_that_is_not_on_main(self):
        r = self.check(self.side_sha)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not on origin/main", r.stderr)

    def test_refuses_a_short_or_malformed_sha(self):
        for bad in ("", self.main_sha[:12], "HEAD", "g" * 40, self.main_sha + "0"):
            self.assertEqual(self.check(bad).returncode, 2, bad)

    def test_accepts_a_commit_on_main(self):
        r = self.check(self.main_sha)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_installed_files_are_checked_against_git(self):
        dest = self.d / "dest"; dest.mkdir()
        (dest / "a.txt").write_bytes(b"one\n")
        body = f'SHA={self.main_sha}; check_file a.txt "{(dest / "a.txt").as_posix()}"; echo "fails=$FAILS checked=$CHECKED"'
        r = self.run_lib(body, RAQM_SRC=self.src.as_posix())
        self.assertIn("fails=0 checked=1", r.stdout, r.stderr)
        (dest / "a.txt").write_bytes(b"one\r\n")                     # a Windows checkout's CRLF is a difference
        r = self.run_lib(body, RAQM_SRC=self.src.as_posix())
        self.assertIn("fails=1 checked=0", r.stdout, r.stderr)
        (dest / "a.txt").unlink()
        r = self.run_lib(body, RAQM_SRC=self.src.as_posix())
        self.assertIn("fails=1", r.stdout, r.stderr)

    def test_the_sha_is_checked_before_anything_is_written(self):
        main = CODE[CODE.index("main() {"):]
        first_write = min(main.index(s) for s in ('install -d -o root -g root -m 700 "$STATE"', "mktemp -d"))
        self.assertLess(main.index('check_sha "$SHA" || exit 2'), first_write)
        self.assertLess(main.index("check_clone || exit 2"), first_write)


class RestartTests(_Harness):
    def test_real_money_units_are_never_restarted(self):
        for unit in ("raqm-live@momentum_ls", "raqm-live@trend_daily.service", "raqm-user@u1--momentum_ls"):
            for action in ("restart", "try-restart", "start", "stop", "enable"):
                r = self.run_lib(f'guarded {action} "{unit}"')
                self.assertNotEqual(r.returncode, 0, (action, unit))
                self.assertIn(f"systemctl {action} '{unit}'", r.stderr)      # the owner's command, printed
        self.assertNotRegex(self.calls(), r"(?m)^(restart|try-restart|start|stop|enable) ")

    def test_a_unit_run_with_live_outside_demo_counts_as_real_money(self):
        self.unit("raqm-newbot", "/opt/raqm-live/venv/bin/python bot.py --live --strategy trend_daily")
        r = self.run_lib('guarded restart raqm-newbot')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("restart raqm-newbot", self.calls())

    def test_patterns_are_refused(self):
        for unit in ("raqm-demo@*", "raqm-*", "raqm-demo@trend_[a-z]*", "raqm-demo@?", ""):
            self.assertNotEqual(self.run_lib(f"guarded restart '{unit}'").returncode, 0, unit)
        self.assertNotRegex(self.calls(), r"(?m)^restart ")

    def test_demo_restarts_by_name(self):
        self.unit("raqm-demo@trend_daily", "/opt/raqm-live/venv/bin/python -E -s bot.py --live --expect-env demo --strategy %i")
        r = self.run_lib('DEMO="trend_daily"; demo_ok trend_daily && restart_demo')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("restart raqm-demo@trend_daily\n", self.calls())

    def test_demo_momentum_ls_stays_masked(self):
        for body in ("demo_ok momentum_ls", "guarded restart raqm-demo@momentum_ls", "guarded start raqm-demo@momentum_ls.service"):
            self.assertNotEqual(self.run_lib(body).returncode, 0, body)
        self.assertNotIn("raqm-demo@momentum_ls", "".join(l for l in self.calls().splitlines(True) if not l.startswith(("cat", "is-"))))

    def test_demo_refused_when_masked_or_its_real_twin_runs(self):
        self.answer("is-enabled raqm-demo@vol_breakout masked")
        self.answer("is-active raqm-live@ratio_trend active")
        self.answer("is-enabled raqm-live@rsi2_pullback enabled")
        for s in ("vol_breakout", "ratio_trend", "rsi2_pullback", "trend_daily;reboot", "Trend", "a b", ""):
            self.assertNotEqual(self.run_lib(f"demo_ok '{s}'").returncode, 0, s)
        self.assertEqual(self.run_lib("demo_ok trend_breakout").returncode, 0)

    def test_every_service_action_goes_through_guarded(self):
        actions = r"systemctl\s+(restart|try-restart|start|stop|enable|disable|mask|unmask|kill|reload|isolate)\b"
        code = re.sub(r'(say|err) "[^"\n]*"', "", CODE)                      # messages may name the owner's commands
        self.assertNotRegex(code, actions)
        self.assertNotRegex(CODE, r"systemctl\s+\"?\$\{?[a-z]")                   # no action from a variable...
        self.assertEqual(len(re.findall(r'systemctl "\$1" "\$2"', CODE)), 1)       # ...except guarded's own line
        self.assertNotRegex(CODE, r"for [a-z]+ in [^\n]*raqm-(live|user)@")         # never a loop over real units

    def test_demo_restart_needs_the_live_target_and_validates_first(self):
        main = CODE[CODE.index("main() {"):]
        self.assertIn("--restart-demo goes with the live target", main)
        self.assertLess(main.index('demo_ok "$s" || exit 2'), main.index("mktemp -d"))


class PaperTests(_Harness):
    OWN = {"momentum", "momentum-daily", "ratio-nobtc", "ratio-trail", "ratio-trail-btc", "retail-fade", "rsi2-btc"}

    def found(self):
        r = self.run_lib(f'paper_bots "{VPS.as_posix()}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(l.split(" ", 1) for l in r.stdout.splitlines())

    def test_every_paper_bot_is_covered(self):
        expected = {}
        for p in VPS.glob("raqm-*.service"):
            s = p.read_text(encoding="utf-8")
            ex = [l for l in s.splitlines() if l.startswith("ExecStart=")]
            if re.search(r"(?m)^User=raqm$", s) and ex and " --paper " in ex[-1]:
                expected[p.stem] = re.findall(r"(?m)^WorkingDirectory=(.*)$", s)[-1]
        found = self.found()
        self.assertEqual(found, expected)
        own = {u[len("raqm-"):] for u, d in found.items() if d != "/opt/raqm-bot"}
        self.assertLessEqual(self.OWN, own)                       # the six own-folder bots of 2026-11-11 at least
        self.assertIn("raqm-bot", found)                          # and the bots of /opt/raqm-bot
        for u, d in found.items():
            self.assertTrue(d.startswith("/opt/raqm-"), u)
            self.assertNotIn(d, ("/opt/raqm-live", "/opt/raqm-users", "/opt/raqm-api"), u)

    def test_paper_bots_get_their_strategies_and_backend(self):
        m = re.search(r'(?m)^PAPER_FILES="([^"]+)"', DEPLOY)
        files = m.group(1).split()
        for f in ("bot.py", "bots", "backend/app", "assets/fonts", "trade_card.py"):
            self.assertIn(f, files)
        self.assertIn('check_git_files "$2" \'\' $PAPER_FILES', DEPLOY)          # each one checked against git after

    def test_copies_into_the_bots_folders_run_as_their_user(self):
        self.assertIn('as_raqm cp -R "$S/." "$D/"', DEPLOY)
        self.assertIn('as_raqm cp -R "$S/." "$B/"', DEPLOY)
        self.assertNotRegex(CODE, r"chown -R")

    def test_old_install_scripts_are_wrappers(self):
        names = set()
        for p in sorted(VPS.glob("install-*.sh")):
            s = p.read_text(encoding="utf-8")
            m = re.search(r'remote-deploy\.sh" "\$\{1:\?commit\}" \$\{2:\+"\$2"\} -- paper:([a-z0-9-]+) --restart$', s, re.M)
            self.assertIsNotNone(m, p.name)
            self.assertNotIn("archive", s, p.name)                  # nothing leaves this checkout
            names.add(m.group(1))
        self.assertEqual(names, self.OWN)
        self.assertLessEqual(names, set(u[len("raqm-"):] for u in self.found()))

    def test_remote_deploy_sends_no_file(self):
        s = (VPS / "remote-deploy.sh").read_text(encoding="utf-8")
        for bad in ("archive", "scp", "rsync", "| $SSH", "| ssh"):
            self.assertNotIn(bad, s)
        self.assertIn('sh \\$SRC/deploy/vps/deploy.sh $COMMIT $*', s)


class SourceAndRecordTests(unittest.TestCase):
    def test_files_come_from_git_never_a_working_tree(self):
        self.assertEqual(len(re.findall(r'git -C "\$SRC" -c core\.autocrlf=false -c tar\.umask=022 archive "\$SHA"', CODE)), 2)
        self.assertNotRegex(CODE, r'(cp|install|cat|tar|rsync)\b[^\n]*"\$SRC/(?!\.git)')
        self.assertNotRegex(CODE, r"/opt/raqm-(bot|api)[^\n]*\| *tar")

    def test_the_clone_must_be_roots(self):
        self.assertIn('[ "$(stat -c %u "$p")" = 0 ]', CODE)
        self.assertIn('-perm /022', CODE)

    def test_previous_commits_are_printed_before_anything_changes(self):
        main = CODE[CODE.index("main() {"):]
        i = main.index('say "previous commits:"')
        for target in ("previous live", "previous paper-shared", 'previous "paper-${u#raqm-}"', "previous page", "previous api"):
            self.assertLess(main.index(target), main.index('install -d -o root -g root -m 700 "$STATE"'), target)
            self.assertGreater(main.index(target), i)
        self.assertLess(main.index('if [ $DRY = 1 ]; then say "dry run: nothing written"; exit 0; fi'),
                        main.index('install -d -o root -g root -m 700 "$STATE"'))
        self.assertIn('say "      rollback: sh $SELF $p ${4:-$1}   (clone left at this commit)"', CODE)
        # a rollback to a commit from before deploy.sh is deployed by this version, not refused
        self.assertIn("predates deploy.sh; this version deploys that commit's files", CODE)

    def test_the_page_is_installed_raqm_www_data_644(self):
        self.assertIn("PAGE=/var/www/bot.da3m.io/index.html", DEPLOY)
        self.assertIn('install -o raqm -g www-data -m 644 "$T/deploy/vps/page/index.html" "$PAGE"', CODE)
        self.assertIn('[ "$m" = "raqm:www-data 644" ]', CODE)
        self.assertIn('check_file deploy/vps/page/index.html "$PAGE"', CODE)

    def test_live_runs_that_commits_setup_and_checks_every_unit_it_installs(self):
        self.assertIn('sh "$T/deploy/vps/setup-live.sh" "$SHA"', CODE)
        setup = (VPS / "setup-live.sh").read_text(encoding="utf-8")
        installed = set(re.findall(r'"\$T/deploy/vps/(raqm-[^"/]+)" /etc/systemd/system/', setup))
        loop = re.search(r"(?m)^for u in ([^;]+); do\n\s+install [^\n]*/etc/systemd/system/", setup)
        installed |= set(loop.group(1).split())
        listed = set(re.search(r'(?s)LIVE_UNITS="([^"]+)"', DEPLOY).group(1).split())
        self.assertEqual(listed, installed)
        self.assertNotIn("raqm-live@.service", listed)              # the real-money template stays the owner's
        for s in ("check_present \"$R\" backend/app", "check_present \"$R\" scripts", 'for R in "$L" "$U"'):
            self.assertIn(s, CODE)

    def test_a_failed_check_stops_restarts_and_fails_the_run(self):
        self.assertIn("if [ $FAILS = $f0 ]; then record live; restart_demo;", CODE)
        self.assertIn('if [ $FAILS = $f0 ]; then\n                    record "paper-${u#raqm-}"\n                    if [ $RESTART = 1 ]', CODE)
        self.assertRegex(CODE, r"FAILS -gt 0 \]; then[^\n]*exit 5")

    def test_api_keeps_the_manual_updater_and_backs_up_its_unit(self):
        self.assertIn('/usr/local/sbin/raqm-api-update --manual "$SHA"', CODE)
        self.assertIn('cp -p "$UNITS/raqm-api.service" "$STATE/raqm-api.service.', CODE)

    @unittest.skipUnless(SH, "needs a POSIX sh")
    def test_scripts_parse(self):
        for name in ("deploy.sh", "remote-deploy.sh", *[p.name for p in VPS.glob("install-*.sh")]):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                f = Path(d) / name
                f.write_text((VPS / name).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
                r = subprocess.run([SH, "-n", f.as_posix()], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, (name, r.stderr))


if __name__ == "__main__":
    unittest.main()

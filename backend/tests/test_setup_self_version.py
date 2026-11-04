"""setup-live.sh runs the setup of the commit it installs: the block that compares the running script with that
commit's copy, run in sh — another version hands over to the commit's own, the same version goes on (and removes the
temporary copy it was started from), and a copy that still differs after the hand-over refuses instead of looping."""
import os, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
SETUP = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
START, END = "# Run the setup of that very commit.", 'then rm -f "$0"; fi'
SHA = "a" * 40


def block():
    i, j = SETUP.index(START), SETUP.index(END) + len(END)
    return SETUP[i:j]


@unittest.skipUnless(shutil.which("sh") and shutil.which("cmp"), "needs sh and cmp")
class SetupSelfVersionTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name)
        (self.d / "T" / "deploy" / "vps").mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def script(self, path, tail):
        path.write_text(f'set -eu\nSHA={SHA}\nT={(self.d / "T").as_posix()}\nmkdir -p "$T/deploy/vps"\n{block()}\n{tail}\n', encoding="utf-8", newline="\n")
        return path

    def run_sh(self, path, **env):
        e = {k: v for k, v in os.environ.items() if k != "RAQM_SETUP_OF"}; e.update(env)
        return subprocess.run(["sh", path.as_posix()], capture_output=True, text=True, env=e, timeout=30)

    def test_block_comes_before_anything_is_installed(self):
        self.assertLess(SETUP.index(START), SETUP.index("install "))
        self.assertLess(SETUP.index('git -C "$SRC" archive "$SHA"'), SETUP.index(START))

    def test_another_version_hands_over_to_the_commits_own(self):
        new = self.d / "T" / "deploy" / "vps" / "setup-live.sh"
        new.write_text('echo "NEW $1 ${RAQM_SETUP_OF:-}"\n', encoding="utf-8", newline="\n")
        r = self.run_sh(self.script(self.d / "old.sh", "echo OLD-WENT-ON"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"NEW {SHA} {SHA}", r.stdout); self.assertNotIn("OLD-WENT-ON", r.stdout)

    def test_the_same_version_goes_on_and_removes_its_temporary_copy(self):
        tmp = self.script(self.d / "copy.sh", "echo WENT-ON")
        shutil.copy(tmp, self.d / "T" / "deploy" / "vps" / "setup-live.sh")
        r = self.run_sh(tmp, RAQM_SETUP_OF=SHA)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("WENT-ON", r.stdout)
        self.assertFalse(tmp.exists())                                   # the copy made for the hand-over is gone
        same = self.script(self.d / "same.sh", "echo WENT-ON")
        r = self.run_sh(same)                                            # run by hand, not handed over: kept
        self.assertIn("WENT-ON", r.stdout); self.assertTrue(same.exists())

    def test_still_another_version_after_the_hand_over_refuses(self):
        (self.d / "T" / "deploy" / "vps" / "setup-live.sh").write_text("echo NEW\n", encoding="utf-8")
        r = self.run_sh(self.script(self.d / "old.sh", "echo OLD-WENT-ON"), RAQM_SETUP_OF=SHA)
        self.assertEqual(r.returncode, 2); self.assertIn("refusing", r.stderr)


if __name__ == "__main__":
    unittest.main()

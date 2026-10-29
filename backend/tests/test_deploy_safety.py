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


if __name__ == "__main__":
    unittest.main()

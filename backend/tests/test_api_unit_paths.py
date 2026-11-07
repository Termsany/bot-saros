"""The API runs with ProtectSystem=strict: it can write only the folders its unit lists (ReadWritePaths). On
2026-11-07 every user's bot save failed with "Read-only file system" — /opt/raqm-users/desired was never in the list,
so neither were the owner's approvals nor the real-money switch. Every folder the API writes must be in it."""
import sys, unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
UNIT = ROOT / "deploy" / "vps" / "api" / "raqm-api.service"


def writable():
    out = []
    for line in UNIT.read_text(encoding="utf-8").splitlines():
        if line.startswith("ReadWritePaths="):
            out += [PurePosixPath(p.lstrip("-")) for p in line.split("=", 1)[1].split()]
    return out


def covered(path):
    p = PurePosixPath(path)
    return any(p == w or w in p.parents for w in writable())


class ApiUnitPathsTests(unittest.TestCase):
    def test_every_folder_the_api_writes_is_writable_in_its_unit(self):
        from app import user_bots, live_accounts
        wants = {
            "the users' requests, approvals, real-money switch": "/opt/raqm-users/desired",
            "the users' close requests": "/opt/raqm-users/ipc/someone--momentum_ls/commands",
            "the owner's bots' close requests and status": "/opt/raqm-ipc/momentum_ls/commands",
            "the paper bots' close requests": "/opt/raqm-ipc-paper/trend",
            "the real ledger and activation": "/opt/raqm-risk",
            "the Demo ledger and yes/no": "/opt/raqm-risk-demo",
            "the sub-accounts' ledgers": live_accounts.RISK_ROOT.as_posix() + "/mom2",
            "the API's own data (vault, consents, audit)": "/opt/raqm-api/app/backend",
        }
        self.assertEqual(user_bots.DESIRED.as_posix(), "/opt/raqm-users/desired")    # the defaults the unit must cover
        self.assertEqual(user_bots.IPC_ROOT.as_posix(), "/opt/raqm-users/ipc")
        for what, path in wants.items():
            self.assertTrue(covered(path), f"{what}: {path} isn't in {UNIT.name}'s ReadWritePaths")

    def test_the_owners_keys_stay_out_of_reach(self):
        for path in ("/opt/raqm-live", "/etc/raqm-users", "/etc/raqm-live"):
            self.assertFalse(covered(path), path)


if __name__ == "__main__":
    unittest.main()

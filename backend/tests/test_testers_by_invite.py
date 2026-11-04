"""Testers on their own Demo bots (development-plan 4.1): the owner's gift invitation approves the account, the admin
page can approve or remove it, and the provisioner reads those approvals but never runs a user on the owner's key."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts"))
import test_plans_invites as tpi
from app import user_approvals, user_bots
import provision_users as pu

TESTER = {"id": "33333333-3333-4333-8333-333333333333", "email": "tester@example.com", "email_confirmed": True}
OTHER = "44444444-4444-4444-8444-444444444444"


class ApprovalListTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(user_bots, "DESIRED", Path(self.td.name)); self.p.start()

    def tearDown(self):
        self.p.stop(); self.td.cleanup()

    def test_add_remove_keep_order_no_repeats(self):
        self.assertEqual(user_approvals.read(), [])
        user_approvals.set_approved(TESTER["id"], True); user_approvals.set_approved(OTHER, True)
        user_approvals.set_approved(TESTER["id"], True)
        self.assertEqual(user_approvals.read(), [TESTER["id"], OTHER])
        self.assertEqual(user_approvals.set_approved(TESTER["id"], False), [OTHER])
        with self.assertRaises(ValueError): user_approvals.set_approved("../etc/passwd", True)
        self.assertFalse(any(p.name.endswith(".tmp") for p in Path(self.td.name).iterdir()))

    def test_lines_that_are_not_user_ids_are_ignored(self):
        (Path(self.td.name) / "approved.list").write_text(f"{OTHER}\nrm -rf /\n{OTHER}\n", encoding="utf-8")
        self.assertEqual(user_approvals.read(), [OTHER])

    def test_the_provisioners_desired_files_never_include_the_list(self):
        user_approvals.set_approved(OTHER, True)
        good, bad = pu.read_desired(Path(self.td.name))
        self.assertEqual((good, bad), ({}, {}))


class InviteApprovesTests(tpi.EndpointTests):
    def setUp(self):
        super().setUp()
        tpi.TOKENS["tester"] = TESTER
        self.dp = mock.patch.object(user_bots, "DESIRED", Path(self.tmp.name) / "desired"); self.dp.start()

    def tearDown(self):
        self.dp.stop(); tpi.TOKENS.pop("tester", None)
        super().tearDown()

    def test_accepting_the_gift_approves_the_account_for_demo_bots(self):
        inv = self.invite(email=TESTER["email"]).json()["invite"]
        self.assertEqual(user_approvals.read(), [])
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/accept", headers=tpi.H("tester")).status_code, 200)
        self.assertEqual(user_approvals.read(), [TESTER["id"]])
        listed = self.client.get("/api/admin/user-bots", headers=tpi.H("admin")).json()
        self.assertEqual([(u["user_id"], u["approved"], u["provision"]) for u in listed["users"]], [(TESTER["id"], True, None)])

    def test_the_admin_approves_and_removes_and_only_the_admin(self):
        url = f"/api/admin/user-bots/{OTHER}/approve"
        self.assertEqual(self.client.post(url, json={"on": True}, headers=tpi.H("sara")).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/user-bots/not-a-uid/approve", json={"on": True}, headers=tpi.H("admin")).status_code, 400)
        self.assertEqual(self.client.post(url, json={"on": True}, headers=tpi.H("admin")).json(), {"ok": True, "approved": True})
        self.assertEqual(user_approvals.read(), [OTHER])
        self.assertEqual(self.client.post(url, json={"on": False}, headers=tpi.H("admin")).json(), {"ok": True, "approved": False})
        self.assertEqual(user_approvals.read(), [])


class ProvisionerTests(unittest.TestCase):
    def test_roots_list_first_then_the_sites_approvals(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "allow").write_text(f"{OTHER}\n", encoding="utf-8")
            (d / "approved").write_text(f"{TESTER['id']}\n{OTHER}\nbad\n", encoding="utf-8")
            self.assertEqual(pu.read_allow(d / "allow", d / "approved"), [OTHER, TESTER["id"]])
            self.assertEqual(pu.read_allow(d / "missing", d / "approved"), [TESTER["id"], OTHER])

    def test_the_owners_keys_are_read_from_both_bot_env_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "live").write_text("BINANCE_ENV=demo\nBINANCE_API_KEY=DEMOKEY\nBINANCE_API_SECRET=x\n", encoding="utf-8")
            (d / "real").write_text("BINANCE_API_KEY='REALKEY'\n", encoding="utf-8")
            self.assertEqual(pu.owner_keys((d / "live", d / "real", d / "missing")), {"DEMOKEY", "REALKEY"})

    def test_a_user_on_the_owners_key_gets_no_bot_and_is_told_why(self):
        uid = TESTER["id"]
        d = {"user_id": uid, "env": "demo", "enabled": True, "strategies": ["trend_daily"], "leverage": 2,
             "risk_per_trade_pct": 1.0, "max_aggregate_risk_pct": 3.0, "capital_usdt": 1000, "capital_margin_override_usdt": 20}
        desired = {uid: pu.validate(uid, d)}
        args = (desired, [uid], {uid: "demo"}, {uid: ("DEMOKEY", "s")}, {}, lambda u, s: True)
        ok = pu.plan(*args)
        self.assertIn(("ensure", uid), [a[:2] for a in ok])
        refused = pu.plan(*args, owner_key={uid})
        self.assertNotIn("ensure", [a[0] for a in refused]); self.assertNotIn("keys", [a[0] for a in refused])
        self.assertEqual(next(a[2]["state"] for a in refused if a[0] == "answer"), "owner_key")


if __name__ == "__main__":
    unittest.main()

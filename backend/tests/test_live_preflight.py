"""scripts/live_preflight.py: every real-money check fails on a server where nothing is set up, passes on one set up
as deploy/vps/README.md says, and the Binance checks catch a key that can withdraw, isn't IP-restricted, or an account
in hedge mode — on fake clients, never a real exchange. Owner and mode reads are patched to what each test wrote
(no pwd on Windows, and Windows keeps no group/other permission bits)."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import live_preflight as lp
from backend.app import risk_manager as rm
from backend.app import testnet_readiness as tr

SHA = "a" * 40
CAPS = ("RAQM_CAP_RISK_PER_TRADE_PCT=2\nRAQM_CAP_AGGREGATE_RISK_PCT=20\nRAQM_CAP_CORRELATED_RISK_PCT=20\n"
        "RAQM_CAP_DAILY_LOSS_PCT=10\nRAQM_CAP_DRAWDOWN_PCT=25\n")


class Futures:
    def __init__(self, hedged=False, usdt=1500.0): self.hedged, self.usdt = hedged, usdt
    def fetch_position_mode(self): return {"hedged": self.hedged}
    def fetch_balance(self): return {"USDT": {"total": self.usdt}}


class Spot:
    def __init__(self, **r): self.r = {"enableWithdrawals": False, "ipRestrict": True, "enableFutures": True, **r}
    def sapi_get_account_apirestrictions(self): return dict(self.r)


def evidence(strategy, sha):
    doc = {"schema_version": 2, "strategies": {strategy: {f: {"value": True, "verified": True} for f in tr.EVIDENCE_FIELDS}},
           "provenance": {"reviewed_commit_sha": sha, "evidence_artifact_sha256": "", "evidence_id": "e1", "producer": "p",
                          "owner": "o", "independent_review": {"reviewers": ["r1", "r2"], "open_findings": 0}}}
    doc["provenance"]["evidence_artifact_sha256"] = tr.evidence_artifact_sha256(doc)
    return doc


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); t = Path(self.td.name)
        self.paths = {"live": t / "live", "api_env": t / "api.env", "evidence": t / "readiness_evidence.json",
                      "ledger": t / "risk" / "risk_state.json", "unit": t / "raqm-live@.service"}
        self.paths["live"].mkdir(); self.paths["ledger"].parent.mkdir()
        owners = {".env.real": "raqmlive", "allow-live.env": "root"}; self.modes = {}
        self.patches = [mock.patch.object(lp, "_owner", lambda p: owners.get(Path(p).name)),
                        mock.patch.object(lp, "_mode", lambda p: self.modes[Path(p).name])]
        for p in self.patches: p.start()
        self.saved = {k: os.environ.pop(k, None) for k in rm.HARD_CAP_ENV.values()}

    def tearDown(self):
        for p in self.patches: p.stop()
        for k, v in self.saved.items():
            if v is not None: os.environ[k] = v
        self.td.cleanup()

    def write(self, key, text, mode=0o600):
        p = self.paths["live"] / key
        p.write_text(text, encoding="utf-8"); self.modes[p.name] = mode; return p

    def set_up_server(self, strategy="momentum_ls"):
        import json
        self.write("DEPLOYED_COMMIT", SHA + "\n", 0o644)
        self.write(".env.real", "BINANCE_API_KEY=k\nBINANCE_SECRET=s\n")
        self.write("allow-live.env", "ALLOW_LIVE_TRADING=true\nBINANCE_LIVE_ACCOUNT=main\n" + CAPS)
        self.paths["unit"].write_text("ExecStart=/opt/raqm-live/venv/bin/python bot.py --live --expect-env live\n", encoding="utf-8")
        self.paths["api_env"].write_text(f"ALLOW_LIVE_TRADING=true\nREADINESS_EXPECTED_COMMIT_SHA={SHA}\n", encoding="utf-8")
        self.paths["evidence"].write_text(json.dumps(evidence(strategy, SHA)), encoding="utf-8")
        # the dashboard's capital plan and risk limits, as the owner sets them for the real account
        rm.update_limits(self.paths["ledger"], {"capital_usdt": 1500, "capital_margin_override_usdt": 26,
                                                "risk_per_trade_pct": 2, "max_aggregate_risk_pct": 20, "max_correlated_risk_pct": 20})

    def failed(self, rows):
        return [name for name, ok, _ in rows if not ok]

    def test_nothing_set_up_fails_every_real_money_check(self):
        failed = self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot())))
        for name in ("deployed commit", "real account keys file", "allow-live.env (root, 600)", "risk ceilings (RAQM_CAP_*_PCT)",
                     "raqm-live@ unit installed", "ALLOW_LIVE_TRADING=true for the API", "readiness evidence for momentum_ls",
                     "Binance real account"):
            self.assertIn(name, failed)

    def test_server_set_up_as_documented_passes(self):
        self.set_up_server()
        rows = lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))
        self.assertEqual(self.failed(rows), [], rows)
        why = dict((n, w) for n, _, w in rows)["momentum_ls basket fits the risk limits"]
        self.assertIn("10 leg(s)", why)                              # 10 × 26×2×0.4/1500 = 13.9% under 20%

    def test_dashboard_limits_left_at_their_defaults_refuse_the_basket(self):
        # the gate takes the lower of the dashboard's limit and root's ceiling: 0.25% per trade by default, under a
        # 1.39% leg, though the ceiling (2%) would allow it — seen on the VPS on 2026-11-03
        self.set_up_server()
        rm.update_limits(self.paths["ledger"], {k: rm.DEFAULT_LIMITS[k] for k in ("risk_per_trade_pct", "max_aggregate_risk_pct", "max_correlated_risk_pct")})
        rows = lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))
        self.assertIn("momentum_ls basket fits the risk limits", self.failed(rows))
        self.assertIn("dashboard", dict((n, w) for n, _, w in rows)["momentum_ls basket fits the risk limits"])

    def test_one_side_of_the_basket_counts_against_the_correlated_limit(self):
        self.set_up_server()
        rm.update_limits(self.paths["ledger"], {"max_correlated_risk_pct": 5})   # 5 longs × 1.39% = 6.9% > 5%
        rows = lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))
        self.assertIn("one side of the basket", dict((n, w) for n, _, w in rows)["momentum_ls basket fits the risk limits"])

    def test_key_that_can_withdraw_or_is_not_ip_restricted_fails(self):
        self.set_up_server()
        self.assertIn("key: withdrawals OFF", self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot(enableWithdrawals=True)))))
        self.assertIn("key: restricted to this server's IP", self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot(ipRestrict=False)))))

    def test_hedge_mode_account_fails(self):
        self.set_up_server()
        self.assertIn("account in one-way mode", self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(hedged=True), Spot()))))

    def test_basket_above_the_ceilings_fails(self):
        self.set_up_server()
        rm.update_limits(self.paths["ledger"], {"capital_margin_override_usdt": 60})   # 10 × 3.2% = 32% > 20%; a leg 3.2% > 2%
        self.assertIn("momentum_ls basket fits the risk limits", self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))))

    def test_wrong_file_mode_or_owner_fails(self):
        self.set_up_server()
        self.modes[".env.real"] = 0o644                               # readable by everyone on the server
        self.assertIn("real account keys file", self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))))
        self.modes[".env.real"] = 0o600
        with mock.patch.object(lp, "_owner", lambda p: "raqmapi"):
            self.assertIn("allow-live.env (root, 600)", self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))))

    def test_readiness_must_match_the_deployed_commit(self):
        self.set_up_server()
        self.write("DEPLOYED_COMMIT", "b" * 40 + "\n", 0o644)
        failed = self.failed(lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot())))
        self.assertIn("readiness bound to the deployed commit", failed)

    def test_ceilings_do_not_leak_into_the_environment(self):
        self.set_up_server()
        lp.run(self.paths, "momentum_ls", clients=(Futures(), Spot()))
        self.assertFalse(any(k in os.environ for k in rm.HARD_CAP_ENV.values()))

    def test_setup_live_installs_the_preflight_and_its_module(self):
        s = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/live_preflight.py", s); self.assertIn("testnet_readiness", s)


if __name__ == "__main__":
    unittest.main()

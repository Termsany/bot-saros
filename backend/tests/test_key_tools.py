"""deploy/vps/tools: the owner's key and evidence helpers are installed by setup-live.sh, never write before checking
(the key against Binance Demo, the evidence against the API's own rule), never touch the real-money key file, restart
the Demo bots by name only; set_reviewers writes the digest the API checks."""
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ROOT / "deploy" / "vps" / "tools"
sys.path.insert(0, str(ROOT / "backend"))
from app.testnet_readiness import evidence_artifact_sha256, _valid_v2_provenance


class KeyToolsTests(unittest.TestCase):
    def test_setup_installs_both_and_never_suggests_a_demo_wildcard_restart(self):
        s = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        for f in ("set_demo_keys.sh", "set_reviewers.py"):
            self.assertIn(f"deploy/vps/tools/{f}\" /usr/local/lib/raqm/{f}", s)
        self.assertNotIn("restart 'raqm-demo@*'", s)

    def test_set_demo_keys_checks_before_writing_and_keeps_away_from_real_money(self):
        s = (TOOLS / "set_demo_keys.sh").read_text(encoding="utf-8")
        self.assertNotIn(".env.real", s.split("\n", 6)[-1])      # only named in the header comment
        self.assertNotIn("raqm-demo@*", s); self.assertNotIn("restart raqm-live", s); self.assertNotIn('restart "raqm-live', s)
        self.assertLess(s.index("fetch_balance"), s.index('mv "$T" "$F"'))   # Binance answers before the file changes
        self.assertIn("BINANCE_ENV=demo", s)
        if shutil.which("bash"):
            r = subprocess.run(["bash", "-n", str(TOOLS / "set_demo_keys.sh")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_set_reviewers_writes_a_digest_the_api_accepts(self):
        sha = "a" * 40
        doc = {"schema_version": 2, "strategies": {"momentum_ls": {"testnet_validated": {"value": True, "verified": True}}},
               "provenance": {"reviewed_commit_sha": sha, "evidence_artifact_sha256": "", "evidence_id": "x", "producer": "p",
                              "owner": "o", "independent_review": {"reviewers": ["reviewer 1", "reviewer 2"], "open_findings": 0}}}
        doc["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(doc)
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / "e.json"; ev.write_text(json.dumps(doc), encoding="utf-8")
            env = Path(td) / ".env"; env.write_text(f"READINESS_EXPECTED_COMMIT_SHA={sha}\n", encoding="utf-8")
            code = (TOOLS / "set_reviewers.py").read_text(encoding="utf-8").replace("/opt/raqm-api/.env", str(env).replace("\\", "/"))
            with mock.patch.object(sys, "argv", ["set_reviewers.py", "--file", str(ev), "Owner (not independent)", "AI review (not independent)"]):
                exec(compile(code, "set_reviewers.py", "exec"), {"__name__": "__main__"})
            out = json.loads(ev.read_text(encoding="utf-8"))
        self.assertEqual(out["provenance"]["independent_review"]["reviewers"], ["Owner (not independent)", "AI review (not independent)"])
        self.assertEqual(out["provenance"]["evidence_artifact_sha256"], evidence_artifact_sha256(out))
        self.assertTrue(_valid_v2_provenance(out["provenance"], out, sha))

    def test_set_reviewers_refuses_one_name_twice(self):
        code = (TOOLS / "set_reviewers.py").read_text(encoding="utf-8")
        with mock.patch.object(sys, "argv", ["set_reviewers.py", "--file", "unused.json", "Same", "Same"]):
            with self.assertRaises(SystemExit):
                exec(compile(code, "set_reviewers.py", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    unittest.main()

"""The owner's tool to sign off one more real-money strategy (deploy/vps/tools/add_strategy_evidence.py, 2026-11-07)."""
import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.testnet_readiness import EVIDENCE_FIELDS, build_live_activation_readiness, evidence_artifact_sha256  # noqa: E402

SHA = "a" * 40


def load_tool():
    os.environ["RAQM_BACKEND"] = str(ROOT / "backend")
    spec = importlib.util.spec_from_file_location("add_strategy_evidence", ROOT / "deploy" / "vps" / "tools" / "add_strategy_evidence.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def momentum_doc(sha=SHA):
    doc = {"schema_version": 2, "strategies": {"momentum_ls": {f: {"value": True, "verified": True} for f in EVIDENCE_FIELDS}},
           "provenance": {"reviewed_commit_sha": sha, "evidence_artifact_sha256": "", "evidence_id": "e1", "producer": "p", "owner": "o",
                          "independent_review": {"reviewers": ["A", "B"], "open_findings": 0}}}
    doc["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(doc)
    return doc


class AddStrategyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.d = Path(tempfile.mkdtemp())
        self.ev, self.env = self.d / "e.json", self.d / ".env"
        self.ev.write_text(json.dumps(momentum_doc()), encoding="utf-8")
        self.env.write_text(f"OTHER=1\nREADINESS_EXPECTED_COMMIT_SHA={SHA}\n", encoding="utf-8")

    def ready(self):
        return build_live_activation_readiness(strategies=["momentum_ls", "rsi2_pullback"], evidence=json.loads(self.ev.read_text(encoding="utf-8")),
                                               live_enabled=True, expected_reviewed_commit_sha=SHA)

    def run_tool(self, *args):
        return self.tool.main(["--file", str(self.ev), "--env", str(self.env), *args])

    def test_adding_rsi2_keeps_momentum_and_both_pass_the_apis_rule(self):
        self.assertEqual(self.ready(), {"momentum_ls": True, "rsi2_pullback": False})
        self.assertIsNone(self.run_tool("rsi2_pullback", "A", "B"))
        self.assertEqual(self.ready(), {"momentum_ls": True, "rsi2_pullback": True})
        self.assertIsNone(self.tool.main(["--remove", "--file", str(self.ev), "--env", str(self.env), "rsi2_pullback", "A", "B"]))
        self.assertEqual(self.ready(), {"momentum_ls": True, "rsi2_pullback": False})

    def test_rebinding_moves_every_strategy_to_the_reviewed_commit(self):
        new = "c" * 40
        self.assertIsNotNone(self.tool.main(["--file", str(self.ev), "--rebind", "abc", "A", "B"]))       # not a full commit
        self.assertIsNone(self.tool.main(["--file", str(self.ev), "--rebind", new, "A", "B"]))
        doc = json.loads(self.ev.read_text(encoding="utf-8"))
        self.assertEqual(doc["provenance"]["reviewed_commit_sha"], new)
        self.assertEqual(build_live_activation_readiness(strategies=["momentum_ls"], evidence=doc, live_enabled=True,
                                                         expected_reviewed_commit_sha=new), {"momentum_ls": True})
        self.assertIsNotNone(self.run_tool("rsi2_pullback", "A", "B"))              # the API's .env still says the old commit
        self.env.write_text(f"READINESS_EXPECTED_COMMIT_SHA={new}\n", encoding="utf-8")
        self.assertIsNone(self.run_tool("rsi2_pullback", "A", "B"))

    def test_nothing_is_written_without_two_names_a_known_strategy_or_the_bound_commit(self):
        before = self.ev.read_text(encoding="utf-8")
        self.assertIsNotNone(self.run_tool("rsi2_pullback", "A"))
        self.assertIsNotNone(self.run_tool("rsi2_pullback", "A", "A"))
        self.assertIsNotNone(self.run_tool("not_a_strategy", "A", "B"))
        self.assertIsNotNone(self.run_tool("default", "A", "B"))
        self.env.write_text(f"READINESS_EXPECTED_COMMIT_SHA={'b' * 40}\n", encoding="utf-8")
        self.assertIsNotNone(self.run_tool("rsi2_pullback", "A", "B"))                 # the file is bound to another commit
        self.assertEqual(self.ev.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()

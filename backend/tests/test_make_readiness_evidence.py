"""The evidence generator must refuse anything less than a passing Demo run, passing tests, and a named sign-off."""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))

SPEC = importlib.util.spec_from_file_location("make_readiness_evidence", ROOT / "scripts" / "make_readiness_evidence.py")
mre = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(mre)

STRATEGIES = list(mre.LIVE_STRATEGIES)
HEAD = "a" * 40
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def stamp(delta=timedelta(0), now=NOW):
    return (now + delta).isoformat()


def demo_report(strategies=STRATEGIES, now=NOW, **overrides):
    report = {
        "started": stamp(-timedelta(hours=1), now), "finished": stamp(-timedelta(minutes=5), now),
        "endpoint": "https://demo-fapi.binance.com/fapi", "commit": HEAD,
        "scenarios": [{"name": f"cli: {s}", "ok": True} for s in strategies],
        "cleanup": [],
    }
    report.update(overrides)
    return report


def test_report(now=NOW, **overrides):
    report = {"ok": True, "tests_run": 630, "failures": 0, "errors": 0, "skipped": 3,
              "finished": stamp(-timedelta(minutes=4), now), "command": "python -m unittest", "commit": HEAD}
    report.update(overrides)
    return report


def signoff(now=NOW, **overrides):
    report = {"approved_by": "Jane Security", "approved_at": stamp(-timedelta(minutes=10), now), "commit": HEAD,
              "scope": "all", "statement": "Reviewed execution, recovery and secret handling; no blocking findings."}
    report.update(overrides)
    return report


class EvidenceGeneratorTests(unittest.TestCase):
    def build(self, demo=None, tests=None, sign=None, strategies=STRATEGIES):
        with mock.patch.object(mre, "_git_head", return_value=HEAD):
            return mre.build(ROOT, demo_report=demo or demo_report(), test_report=tests or test_report(),
                             security_signoff=sign or signoff(), strategies=strategies, now=NOW)

    def assert_refused(self, fragment, **kwargs):
        with self.assertRaises(mre.EvidenceError) as raised:
            self.build(**kwargs)
        self.assertIn(fragment, " ".join(raised.exception.errors).lower())

    def test_emits_exactly_the_schema_the_api_verifies(self):
        evidence, provenance = self.build()
        self.assertEqual(set(evidence), {"schema_version", "provenance", "strategies"})
        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(evidence["provenance"], {"source": "trusted-readiness", "verified": True})
        self.assertEqual(set(evidence["strategies"]), set(STRATEGIES))
        for row in evidence["strategies"].values():
            self.assertEqual(set(row), set(mre.EVIDENCE_FIELDS))
            self.assertTrue(all(v == {"value": True, "verified": True} for v in row.values()))
        self.assertEqual(provenance["repo_commit"], HEAD)
        self.assertEqual(provenance["evidence_sha256"], mre.hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_failed_scenario_is_refused(self):
        report = demo_report(); report["scenarios"][0]["ok"] = False
        self.assert_refused("failed scenarios", demo=report)

    def test_non_demo_endpoint_is_refused(self):
        self.assert_refused("not binance demo", demo=demo_report(endpoint="https://fapi.binance.com/fapi"))

    def test_missing_strategy_coverage_is_refused(self):
        self.assert_refused("no scenario", demo=demo_report(strategies=["trend_daily"]))

    def test_stale_demo_report_is_refused(self):
        self.assert_refused("older than", demo=demo_report(finished=stamp(-timedelta(days=31))))

    def test_future_timestamp_is_refused(self):
        self.assert_refused("future", demo=demo_report(finished=stamp(timedelta(hours=1))))

    def test_failing_test_report_is_refused(self):
        self.assert_refused("failures", tests=test_report(failures=2))
        self.assert_refused("tests_run", tests=test_report(tests_run=0))

    def test_signoff_must_name_a_person(self):
        self.assert_refused("named person", sign=signoff(approved_by="admin"))

    def test_signoff_must_bind_the_current_commit(self):
        self.assert_refused("current commit", sign=signoff(commit="b" * 40))

    def test_signoff_scope_must_cover_every_selected_strategy(self):
        self.assert_refused("does not cover", sign=signoff(scope=["trend_daily"]))

    def test_cleanup_failure_is_refused(self):
        self.assert_refused("cleanup", demo=demo_report(cleanup=["COULD NOT CLOSE BTC/USDT 1"]))

    def test_main_writes_evidence_and_a_provenance_sidecar(self):
        # main() uses the real clock, so its fixtures must be relative to now (not to the pinned NOW).
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, payload in (("demo.json", demo_report(now=now)), ("tests.json", test_report(now=now)),
                                  ("sign.json", signoff(now=now))):
                (d / name).write_text(json.dumps(payload), encoding="utf-8")
            out = d / "readiness_evidence.json"
            with mock.patch.object(mre, "_git_head", return_value=HEAD):
                code = mre.main(["--demo-report", str(d / "demo.json"), "--test-report", str(d / "tests.json"),
                                 "--security-signoff", str(d / "sign.json"), "--out", str(out), "--repo", str(ROOT)])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            sidecar = d / "readiness_evidence.provenance.json"
            self.assertTrue(sidecar.exists())
            self.assertEqual(json.loads(sidecar.read_text(encoding="utf-8"))["repo_commit"], HEAD)

    def test_main_writes_nothing_when_validation_fails(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, payload in (("demo.json", demo_report(now=now)), ("tests.json", test_report(now=now, failures=1)),
                                  ("sign.json", signoff(now=now))):
                (d / name).write_text(json.dumps(payload), encoding="utf-8")
            out = d / "readiness_evidence.json"
            with mock.patch.object(mre, "_git_head", return_value=HEAD):
                code = mre.main(["--demo-report", str(d / "demo.json"), "--test-report", str(d / "tests.json"),
                                 "--security-signoff", str(d / "sign.json"), "--out", str(out), "--repo", str(ROOT)])
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())
            self.assertFalse((d / "readiness_evidence.provenance.json").exists())


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.app.testnet_readiness import build_admin_readiness


class ReadinessSchemaV2Tests(unittest.TestCase):
    def evidence(self):
        fields = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
        return {"schema_version": 2, "provenance": {
            "reviewed_commit_sha": "a" * 40, "evidence_artifact_sha256": "b" * 64,
            "evidence_id": "evidence-20261102-001", "producer": "testnet-readiness-job",
            "owner": "readiness-owner", "independent_review": {"reviewers": ["a", "b"], "open_findings": 0}},
            "strategies": {"trend_daily": {f: {"value": True, "verified": True} for f in fields}}}

    def test_legacy_self_asserted_schema_is_rejected(self):
        evidence = self.evidence()
        evidence["schema_version"] = 1
        evidence["provenance"] = {"source": "trusted-readiness", "verified": True}
        result = build_admin_readiness(strategies=["trend_daily"], evidence=evidence, live_locked=False, environment="testnet")
        self.assertFalse(result["strategies"]["trend_daily"]["testnet_ready"])

    def test_review_binding_requires_exact_hashes_owner_producer_and_clean_review(self):
        for field, value in (("reviewed_commit_sha", "bad"), ("evidence_artifact_sha256", "bad"), ("evidence_id", ""), ("producer", ""), ("owner", "")):
            evidence = self.evidence()
            evidence["provenance"][field] = value
            result = build_admin_readiness(strategies=["trend_daily"], evidence=evidence, live_locked=False, environment="testnet")
            self.assertFalse(result["strategies"]["trend_daily"]["testnet_ready"], field)
        evidence = self.evidence()
        evidence["provenance"]["independent_review"]["reviewers"] = ["a"]
        self.assertFalse(build_admin_readiness(strategies=["trend_daily"], evidence=evidence, live_locked=False, environment="testnet")["testnet_ready"])
        evidence = self.evidence()
        evidence["provenance"]["independent_review"]["open_findings"] = 1
        self.assertFalse(build_admin_readiness(strategies=["trend_daily"], evidence=evidence, live_locked=False, environment="testnet")["testnet_ready"])

import unittest

from backend.app.testnet_readiness import build_admin_readiness, evidence_artifact_sha256


class ReadinessSchemaV2Tests(unittest.TestCase):
    def evidence(self, *, commit="a" * 40, open_findings=0):
        fields = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
        return {"schema_version": 2, "provenance": {
            "reviewed_commit_sha": commit, "evidence_artifact_sha256": "",
            "evidence_id": "evidence-20261102-001", "producer": "testnet-readiness-job",
            "owner": "readiness-owner", "independent_review": {"reviewers": ["a", "b"], "open_findings": open_findings}},
            "strategies": {"trend_daily": {f: {"value": True, "verified": True} for f in fields}}}

    def trusted_evidence(self, **kwargs):
        evidence = self.evidence(**kwargs)
        evidence["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(evidence)
        return evidence

    def ready(self, evidence):
        return build_admin_readiness(strategies=["trend_daily"], evidence=evidence, live_locked=False,
                                     environment="testnet", expected_reviewed_commit_sha="a" * 40)

    def test_legacy_self_asserted_schema_is_rejected(self):
        evidence = self.trusted_evidence()
        evidence["schema_version"] = 1
        evidence["provenance"] = {"source": "trusted-readiness", "verified": True}
        self.assertFalse(self.ready(evidence)["strategies"]["trend_daily"]["testnet_ready"])

    def test_review_binding_requires_exact_hashes_owner_producer_and_clean_review(self):
        for field, value in (("reviewed_commit_sha", "bad"), ("evidence_artifact_sha256", "bad"), ("evidence_id", ""), ("producer", ""), ("owner", "")):
            evidence = self.trusted_evidence()
            evidence["provenance"][field] = value
            self.assertFalse(self.ready(evidence)["strategies"]["trend_daily"]["testnet_ready"], field)
        evidence = self.trusted_evidence()
        evidence["provenance"]["independent_review"]["reviewers"] = ["a"]
        self.assertFalse(self.ready(evidence)["testnet_ready"])
        evidence = self.trusted_evidence(open_findings=1)
        self.assertFalse(self.ready(evidence)["testnet_ready"])

    def test_fabricated_hashes_and_missing_external_commit_binding_fail_closed(self):
        evidence = self.evidence()
        evidence["provenance"]["evidence_artifact_sha256"] = "b" * 64
        self.assertFalse(self.ready(evidence)["testnet_ready"])
        evidence = self.trusted_evidence()
        self.assertFalse(build_admin_readiness(strategies=["trend_daily"], evidence=evidence, live_locked=False, environment="testnet")["testnet_ready"])

    def test_open_findings_must_be_integer_not_boolean(self):
        self.assertFalse(self.ready(self.trusted_evidence(open_findings=False))["testnet_ready"])

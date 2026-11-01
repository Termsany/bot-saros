"""Offline/read-only Testnet readiness checks; never submits an order."""
from __future__ import annotations
import math
import os
import re

ALL_STRATEGIES = (
    "trend_daily", "listing_short", "momentum_ls", "ratio_trend",
    "vol_breakout", "rsi2_pullback", "trend_breakout", "default",
)

EVIDENCE_FIELDS = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _valid_v2_provenance(provenance):
    if not isinstance(provenance, dict) or set(provenance) != {
        "reviewed_commit_sha", "evidence_artifact_sha256", "evidence_id", "producer", "owner", "independent_review"
    }:
        return False
    review = provenance["independent_review"]
    return (
        isinstance(provenance["reviewed_commit_sha"], str) and bool(_SHA40.fullmatch(provenance["reviewed_commit_sha"]))
        and isinstance(provenance["evidence_artifact_sha256"], str) and bool(_SHA256.fullmatch(provenance["evidence_artifact_sha256"]))
        and isinstance(provenance["evidence_id"], str) and bool(provenance["evidence_id"].strip())
        and all(isinstance(provenance[k], str) and bool(provenance[k].strip()) for k in ("producer", "owner"))
        and isinstance(review, dict) and set(review) == {"reviewers", "open_findings"}
        and isinstance(review["reviewers"], list)
                and all(isinstance(r, str) and r.strip() for r in review["reviewers"])
                and len(set(review["reviewers"])) >= 2
        and review["open_findings"] == 0
    )


def build_admin_readiness(*, strategies, evidence=None, live_locked, environment=None):
    """Build readiness only from a versioned, provenance-bearing evidence document."""
    evidence = evidence if isinstance(evidence, dict) else {}
    provenance = evidence.get("provenance")
    valid_document = (
        evidence.get("schema_version") == 2
        and _valid_v2_provenance(provenance)
        and isinstance(evidence.get("strategies"), dict)
        and set(evidence) == {"schema_version", "provenance", "strategies"}

    )
    env = environment if environment is not None else os.getenv("BINANCE_ENV", "")
    rows = {}
    for strategy in strategies or []:
        supplied = (evidence.get("strategies", {}).get(strategy) or {}) if valid_document else {}
        row = {field: bool(valid_document and set(supplied) == set(EVIDENCE_FIELDS) and isinstance(supplied.get(field), dict) and set(supplied[field]) == {"value", "verified"} and supplied[field].get("value") is True and supplied[field].get("verified") is True) for field in EVIDENCE_FIELDS}
        row["paper_ready"] = row["adapter_implemented"]
        row["testnet_ready"] = env == "testnet" and row["paper_ready"] and row["recovery_tests"] and row["security_approved"] and row["testnet_validated"]
        row["live_ready"] = row["testnet_ready"] and not bool(live_locked)
        row["reasons"] = [f"missing {field.replace('_', ' ')} evidence" for field in EVIDENCE_FIELDS if not row[field]]
        if not valid_document:
            row["reasons"].append("unverified readiness evidence")
        if env != "testnet":
            row["reasons"].append("testnet environment is unavailable")
        if row["testnet_ready"] and live_locked:
            row["reasons"].append("live trading remains locked")
        row["status"] = "live-ready" if row["live_ready"] else ("testnet-ready" if row["testnet_ready"] else ("paper-ready" if row["paper_ready"] else "not-ready"))
        rows[strategy] = row
    return {
        "strategies": rows,
        "paper_ready": bool(rows) and all(r["paper_ready"] for r in rows.values()),
        "testnet_ready": bool(rows) and all(r["testnet_ready"] for r in rows.values()),
        "live_ready": bool(rows) and all(r["live_ready"] for r in rows.values()),
    }


def build_live_activation_readiness(*, strategies, evidence=None, live_enabled):
    """Server-derived readiness for the live activation record: bool per strategy.

    Unlike build_admin_readiness, this does not require the current process to be running on testnet. The evidence
    document itself is the testnet validation record (`testnet_validated` must be a verified True), so the live server
    can act on evidence gathered on testnet without pretending it is still there. The server's live switch must also be
    on: evidence alone never unlocks real money.
    """
    if not live_enabled:
        return {s: False for s in strategies or []}
    report = build_admin_readiness(strategies=strategies, evidence=evidence, live_locked=False, environment="testnet")
    return {s: bool(report["strategies"].get(s, {}).get("live_ready")) for s in strategies or []}


def check_testnet_readiness(exchange, *, strategies, risk_state_loader, environment=None):
    """Return structured readiness evidence without touching order endpoints."""
    checks = {}
    env = environment or os.getenv("BINANCE_ENV", "")
    checks["testnet_environment"] = env == "testnet"
    checks["live_locked"] = os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true"
    selected = list(strategies or [])
    checks["strategies_declared"] = bool(selected) and all(s in ALL_STRATEGIES for s in selected)
    required_methods = ("fetch_balance", "fetch_positions", "fetch_order", "fetch_open_orders", "create_order", "cancel_order")
    checks["exchange_capabilities"] = all(callable(getattr(exchange, name, None)) for name in required_methods)
    try:
        markets = exchange.load_markets()
        contracts = [m for m in markets.values() if m.get("contract")]
        checks["linear_contract_metadata"] = bool(contracts) and all(
            m.get("linear") is True and not m.get("inverse") and math.isfinite(float(m.get("contractSize"))) and float(m.get("contractSize")) > 0
            for m in contracts
        )
    except Exception:
        checks["linear_contract_metadata"] = False
    try:
        state = risk_state_loader()
        checks["risk_ledger_readable"] = isinstance(state, dict) and not (state.get("kill_switch") or {}).get("tripped")
    except Exception:
        checks["risk_ledger_readable"] = False
    return {"ready": all(checks.values()), "checks": checks, "orders_submitted": 0}

#!/usr/bin/env python3
"""Build the trusted ``readiness_evidence.json`` from three signed-off inputs.

Nothing here talks to an exchange and nothing produces readiness by itself: it checks that a Demo end-to-end run, a
test run, and a named security review all passed and belong to the current commit, then writes the only document the
API and the live activation gate will accept as readiness evidence.

Inputs (JSON):
  --demo-report       output of ``python scripts/demo_e2e.py --out demo.json``. Must name the Binance Demo endpoint,
                      contain no failed scenario, and cover every selected strategy.
  --test-report       a passing test summary, for example::

                          {"ok": true, "tests_run": 630, "failures": 0, "errors": 0,
                           "finished": "2026-11-02T10:00:00+00:00", "commit": "<sha>"}

                      ``command`` and ``skipped`` are recorded when present. Failures or errors > 0 are refused.
  --security-signoff  a named person's approval::

                          {"approved_by": "Full Name", "approved_at": "2026-11-02T09:00:00+00:00",
                           "commit": "<sha>", "scope": ["trend_daily", "..."], "statement": "..."}

                      ``scope`` may be ``"all"``. ``commit`` must be the commit under test.

The evidence document is exactly ``{schema_version, provenance, strategies}`` (the schema the API verifies). A
sidecar, ``<out>.provenance.json``, records the input file hashes, timestamps, commit, and the evidence hash. Both
files are generated artefacts and are ignored by git.

Refuses to write anything unless every check passes - a partial or optimistic document would be worse than none.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_FIELDS = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
LIVE_STRATEGIES = ("trend_daily", "listing_short", "momentum_ls", "ratio_trend",
                   "vol_breakout", "rsi2_pullback", "trend_breakout")
DEMO_HOST = "demo-fapi.binance.com"
GENERIC_APPROVERS = {"", "admin", "administrator", "system", "root", "owner", "operator"}


class EvidenceError(ValueError):
    """Validation failed. ``errors`` holds every reason, so the operator can fix them in one pass."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvidenceError([f"{path}: cannot read: {exc}"])
    except json.JSONDecodeError as exc:
        raise EvidenceError([f"{path}: invalid JSON: {exc}"])


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_time(value, label, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: missing ISO-8601 timestamp")
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label}: not a valid ISO-8601 timestamp")
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _check_fresh(stamp, label, now, max_age_days, errors):
    if stamp is None:
        return
    if stamp > now + timedelta(minutes=5):
        errors.append(f"{label}: timestamp is in the future ({stamp.isoformat()})")
    elif stamp < now - timedelta(days=max_age_days):
        errors.append(f"{label}: older than {max_age_days} days ({stamp.isoformat()}) - run it again")


def _commit_matches(value, head):
    return isinstance(value, str) and len(value.strip()) >= 7 and head.lower().startswith(value.strip().lower())


def _scenario_covers(name, strategy):
    if not isinstance(name, str):
        return False
    name = name.strip()
    if name == strategy:
        return True
    for prefix in ("loop:", "cli:"):
        if name.startswith(prefix) and name[len(prefix):].strip() == strategy:
            return True
    return name.startswith(strategy + ":")


def _validate_demo(report, strategies, head, now, max_age_days):
    errors = []
    if not isinstance(report, dict):
        return ["demo report: not a JSON object"], {}
    endpoint = report.get("endpoint")
    host = ""
    if isinstance(endpoint, str) and endpoint.strip():
        parsed = urlsplit(endpoint if "://" in endpoint else "//" + endpoint)
        host = parsed.hostname or ""
    if DEMO_HOST not in host:
        errors.append(f"demo report: endpoint is not Binance Demo ({endpoint!r})")
    started = _parse_time(report.get("started"), "demo report started", errors)
    finished = _parse_time(report.get("finished"), "demo report finished", errors)
    if started and finished and finished < started:
        errors.append("demo report: finished is before started")
    _check_fresh(finished, "demo report finished", now, max_age_days, errors)
    if report.get("commit") is not None and not _commit_matches(report.get("commit"), head):
        errors.append(f"demo report: commit {report.get('commit')!r} is not the current commit {head}")
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("demo report: no scenarios")
        scenarios = []
    failed = []
    for item in scenarios:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            errors.append("demo report: a scenario has no name")
            continue
        if item.get("ok") is not True:
            failed.append(name)
    if failed:
        errors.append("demo report: failed scenarios: " + ", ".join(failed))
    covered = [s for s in strategies if any(_scenario_covers(i.get("name"), s) for i in scenarios if isinstance(i, dict))]
    missing = [s for s in strategies if s not in covered]
    if missing:
        errors.append("demo report: no scenario for " + ", ".join(missing))
    cleanup = report.get("cleanup")
    if not isinstance(cleanup, list):
        errors.append("demo report: cleanup list missing")
    elif any("could not" in str(item).lower() for item in cleanup):
        errors.append("demo report: cleanup left something open: " + "; ".join(map(str, cleanup)))
    return errors, {"endpoint": host, "started": started.isoformat() if started else None,
                    "finished": finished.isoformat() if finished else None,
                    "scenarios": len(scenarios), "covered": covered}


def _validate_tests(report, head, now, max_age_days):
    errors = []
    if not isinstance(report, dict):
        return ["test report: not a JSON object"], {}
    try:
        tests_run = int(report.get("tests_run"))
    except (TypeError, ValueError):
        tests_run = 0
    if tests_run <= 0:
        errors.append("test report: tests_run must be a positive integer")
    for field in ("failures", "errors"):
        try:
            count = int(report.get(field, 0) or 0)
        except (TypeError, ValueError):
            count = -1
        if count != 0:
            errors.append(f"test report: {field} is {report.get(field)!r}")
    if report.get("ok") is not None and report.get("ok") is not True:
        errors.append("test report: ok is not true")
    finished = _parse_time(report.get("finished"), "test report finished", errors)
    _check_fresh(finished, "test report finished", now, max_age_days, errors)
    if report.get("commit") is not None and not _commit_matches(report.get("commit"), head):
        errors.append(f"test report: commit {report.get('commit')!r} is not the current commit {head}")
    return errors, {"finished": finished.isoformat() if finished else None, "tests_run": tests_run,
                    "failures": report.get("failures", 0), "errors": report.get("errors", 0),
                    "skipped": report.get("skipped", 0), "command": report.get("command")}


def _validate_signoff(doc, strategies, head, now, max_age_days):
    errors = []
    if not isinstance(doc, dict):
        return ["security sign-off: not a JSON object"], {}
    approved_by = str(doc.get("approved_by") or "").strip()
    if approved_by.lower() in GENERIC_APPROVERS:
        errors.append("security sign-off: a named person is required in approved_by")
    statement = str(doc.get("statement") or "").strip()
    if len(statement) < 10:
        errors.append("security sign-off: statement is missing or too short")
    approved_at = _parse_time(doc.get("approved_at"), "security sign-off approved_at", errors)
    _check_fresh(approved_at, "security sign-off approved_at", now, max_age_days, errors)
    commit = doc.get("commit", doc.get("reviewed_commit"))
    if not _commit_matches(commit, head):
        errors.append(f"security sign-off: commit {commit!r} is not the current commit {head}")
    scope = doc.get("scope", doc.get("strategies"))
    if isinstance(scope, str):
        scope = [part.strip() for part in scope.split(",") if part.strip()]
    if scope == "all" or scope == ["all"]:
        scope = list(strategies)
    if not isinstance(scope, list):
        errors.append("security sign-off: scope must be 'all' or a list of strategies")
        scope = []
    missing = [s for s in strategies if s not in scope]
    if missing:
        errors.append("security sign-off: scope does not cover " + ", ".join(missing))
    return errors, {"approved_by": approved_by, "approved_at": approved_at.isoformat() if approved_at else None,
                    "commit": commit, "scope": scope, "role": doc.get("role")}


def build(repo, *, demo_report, test_report, security_signoff, strategies=None, now=None, max_age_days=30):
    """Validate the three inputs and return ``(evidence, provenance)``. Raises ``EvidenceError`` on any failure."""
    strategies = list(dict.fromkeys(strategies or LIVE_STRATEGIES))
    unknown = [s for s in strategies if s not in LIVE_STRATEGIES]
    if not strategies or unknown:
        raise EvidenceError(["strategies: " + (", ".join(unknown) if unknown else "none selected")])
    now = now or datetime.now(timezone.utc)
    head = _git_head(repo)
    errors, demo = _validate_demo(demo_report, strategies, head, now, max_age_days)
    test_errors, tests = _validate_tests(test_report, head, now, max_age_days)
    sign_errors, signoff = _validate_signoff(security_signoff, strategies, head, now, max_age_days)
    errors += test_errors + sign_errors
    if errors:
        raise EvidenceError(errors)
    evidence = {
        "schema_version": 1,
        "provenance": {"source": "trusted-readiness", "verified": True},
        "strategies": {
            s: {field: {"value": True, "verified": True} for field in EVIDENCE_FIELDS}
            for s in strategies
        },
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    provenance = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "generator": "scripts/make_readiness_evidence.py",
        "repo_commit": head,
        "strategies": strategies,
        "evidence_sha256": hashlib.sha256(canonical).hexdigest(),
        "inputs": {"demo": demo, "tests": tests, "security_signoff": signoff},
    }
    return evidence, provenance


def _git_head(repo):
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError([f"git: cannot read the current commit: {exc}"])
    head = (result.stdout or "").strip()
    if result.returncode != 0 or not head:
        raise EvidenceError(["git: cannot read the current commit: " + (result.stderr or "").strip()[:300]])
    return head


def _write(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo-report", required=True)
    ap.add_argument("--test-report", required=True)
    ap.add_argument("--security-signoff", required=True)
    ap.add_argument("--out", default=str(ROOT / "readiness_evidence.json"))
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--strategies", default=",".join(LIVE_STRATEGIES))
    ap.add_argument("--max-age-days", type=int, default=30)
    args = ap.parse_args(argv)
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    try:
        demo = _load_json(args.demo_report)
        tests = _load_json(args.test_report)
        signoff = _load_json(args.security_signoff)
        evidence, provenance = build(args.repo, demo_report=demo, test_report=tests,
                                     security_signoff=signoff, strategies=strategies,
                                     max_age_days=args.max_age_days)
    except EvidenceError as exc:
        print("refusing to write readiness evidence:", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    out = Path(args.out)
    sidecar = out.with_name(out.stem + ".provenance.json")
    provenance["inputs"].update({
        "demo_report_path": str(Path(args.demo_report).resolve()),
        "demo_report_sha256": _sha256(args.demo_report),
        "test_report_path": str(Path(args.test_report).resolve()),
        "test_report_sha256": _sha256(args.test_report),
        "security_signoff_path": str(Path(args.security_signoff).resolve()),
        "security_signoff_sha256": _sha256(args.security_signoff),
    })
    _write(out, evidence)
    _write(sidecar, provenance)
    print(f"wrote {out} for {len(strategies)} strategies at {provenance['repo_commit'][:12]}")
    print(f"wrote {sidecar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

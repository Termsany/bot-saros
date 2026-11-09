# The owner's sign-off in readiness_evidence.json (owner, 2026-11-07): add one more real-money strategy, take one
# back, or bind the whole record to another reviewed commit. Run it yourself — your names are the signature; nothing
# else may write them:
#   sudo -u raqmapi /opt/raqm-api/venv/bin/python -I /usr/local/lib/raqm/add_strategy_evidence.py rsi2_pullback "First Reviewer" "Second Reviewer"
#   sudo -u raqmapi /opt/raqm-api/venv/bin/python -I /usr/local/lib/raqm/add_strategy_evidence.py --rebind <40-hex commit> "First Reviewer" "Second Reviewer"
# Adding marks the strategy's four rows true and verified — adapter implemented, recovery tested, security approved,
# validated on Binance Demo — for the commit the API is bound to (READINESS_EXPECTED_COMMIT_SHA), keeps every other
# strategy as it is, recomputes the digest and writes only if the API's own rule then accepts it. --rebind moves the
# record (every strategy in it) to the commit you reviewed; then READINESS_EXPECTED_COMMIT_SHA in /opt/raqm-api/.env
# must be set to the same commit (the tool prints the line). --remove STRATEGY takes a sign-off back.
# --file PATH / --env PATH work on copies (tests).
import json, os, re, sys, tempfile
sys.path.insert(0, os.getenv("RAQM_BACKEND", "/opt/raqm-api/app/backend"))
from app.testnet_readiness import (ALL_STRATEGIES, EVIDENCE_FIELDS, build_live_activation_readiness,  # noqa: E402
                                   evidence_artifact_sha256, _valid_v2_provenance)


def main(argv):
    path, env, remove, rebind = "/opt/raqm-api/app/readiness_evidence.json", "/opt/raqm-api/.env", False, None
    while argv[:1] and argv[0] in ("--file", "--env", "--remove", "--rebind"):
        if argv[0] == "--remove": remove, argv = True, argv[1:]
        elif argv[0] == "--file": path, argv = argv[1], argv[2:]
        elif argv[0] == "--env": env, argv = argv[1], argv[2:]
        else: rebind, argv = (argv[1] if len(argv) > 1 else "").strip().lower(), argv[2:]
    if rebind is not None and not re.fullmatch(r"[0-9a-f]{40}", rebind):
        return "--rebind محتاج رقم الكومِت كامل (40 حرف)"
    strategy = None
    if rebind is None:
        if not argv or argv[0] not in ALL_STRATEGIES or argv[0] == "default":
            return f"اكتب اسم الاستراتيجية الأول: {', '.join(s for s in ALL_STRATEGIES if s != 'default')}"
        strategy, argv = argv[0], argv[1:]
    names = [a.strip() for a in argv]
    if len(names) < 2 or len(set(names)) != len(names) or not all(names):
        return "محتاج اسمين مختلفين على الأقل للمراجعين، كل اسم بين علامتين \"...\""
    doc = json.load(open(path, encoding="utf-8"))
    if rebind:
        expected = rebind
        doc["provenance"]["reviewed_commit_sha"] = rebind
    else:
        expected = next((l.split("=", 1)[1].strip() for l in open(env, encoding="utf-8") if l.startswith("READINESS_EXPECTED_COMMIT_SHA=")), "")
        if doc.get("provenance", {}).get("reviewed_commit_sha") != expected:
            return f"الملف مربوط بكومِت {str(doc.get('provenance', {}).get('reviewed_commit_sha'))[:12]} والـ API مستني {expected[:12]} — اربطه الأول (--rebind)"
        if remove:
            doc["strategies"].pop(strategy, None)
        else:
            doc["strategies"][strategy] = {f: {"value": True, "verified": True} for f in EVIDENCE_FIELDS}
    doc["provenance"]["independent_review"]["reviewers"] = names
    doc["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(doc)
    if not _valid_v2_provenance(doc["provenance"], doc, expected):
        return "الملف بعد التعديل مش هيعدّي فحص الـ API — ماتكتبش حاجة"
    asked = sorted(set(doc["strategies"]) | ({strategy} if strategy else set()))
    ready = build_live_activation_readiness(strategies=asked, evidence=doc, live_enabled=True, expected_reviewed_commit_sha=expected)
    if strategy and (ready.get(strategy) if remove else not ready.get(strategy)):
        return "الـ API مش هيقبل الاستراتيجية بالشكل ده — ماتكتبش حاجة"
    if rebind and not all(ready.get(s) for s in doc["strategies"]):
        return "بعد الربط في استراتيجية مش هتعدّي — ماتكتبش حاجة"
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".evidence-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o640); os.replace(tmp, path)
    what = f"اتربط بـ {rebind[:12]}" if rebind else f"{'اتشال' if remove else 'اتضاف'} {strategy}"
    print(f"✅ {what} · جاهز: {', '.join(s for s, ok in ready.items() if ok) or '—'} · "
          f"المراجعين: {', '.join(names)} · digest {doc['provenance']['evidence_artifact_sha256'][:12]}")
    if rebind:
        print(f"الخطوة الجاية: READINESS_EXPECTED_COMMIT_SHA={rebind} في /opt/raqm-api/.env وبعدها restart للـ API")
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

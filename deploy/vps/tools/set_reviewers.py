# Put the owner's reviewer names into readiness_evidence.json, recompute its digest, check it with the API's own rule.
#   sudo -u raqmapi /opt/raqm-api/venv/bin/python -I /usr/local/lib/raqm/set_reviewers.py "First Reviewer" "Second Reviewer"
# --file PATH works on a copy (test). Nothing is written unless the result passes the same check the API uses.
import json, os, sys, tempfile
sys.path.insert(0, "/opt/raqm-api/app/backend")
from app.testnet_readiness import evidence_artifact_sha256, _valid_v2_provenance

args = sys.argv[1:]
path = "/opt/raqm-api/app/readiness_evidence.json"
if args[:1] == ["--file"]:
    path, args = args[1], args[2:]
names = [a.strip() for a in args]
if len(names) < 2 or len(set(names)) != len(names) or not all(names):
    sys.exit("محتاج اسمين مختلفين على الأقل، كل اسم بين علامتين \"...\"")
expected = next(l.split("=", 1)[1].strip() for l in open("/opt/raqm-api/.env", encoding="utf-8") if l.startswith("READINESS_EXPECTED_COMMIT_SHA="))
doc = json.load(open(path, encoding="utf-8"))
doc["provenance"]["independent_review"]["reviewers"] = names
doc["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(doc)
if not _valid_v2_provenance(doc["provenance"], doc, expected):
    sys.exit("الملف بعد التعديل مش هيعدّي فحص الـ API — ماتكتبش حاجة")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".evidence-")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)
os.chmod(tmp, 0o640); os.replace(tmp, path)
print("✅ اتكتب:", ", ".join(names), "· digest", doc["provenance"]["evidence_artifact_sha256"][:12])

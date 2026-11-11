"""Stamp the paper page's asset links with each file's content hash (assets/<name>?v=<12 hex>), so a browser never
pairs a new index.html with an old script or stylesheet (nginx sends no cache header for them). Run after editing
anything in assets/; backend/tests/test_paper_page_files.py fails until it is run.

  python deploy/vps/page/stamp.py
"""
import hashlib, re
from pathlib import Path

PAGE = Path(__file__).resolve().parent
LINK = re.compile(r'(?P<pre>(?:src|href)=")assets/(?P<name>[a-z0-9_]+\.(?:js|css))(?:\?v=[0-9a-f]+)?(?P<post>")')


def digest(name):
    """Of the file as git holds it (LF): a Windows checkout's CRLF copy hashes the same as the server's and CI's."""
    return hashlib.sha256((PAGE / "assets" / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def stamped(html):
    return LINK.sub(lambda m: f'{m["pre"]}assets/{m["name"]}?v={digest(m["name"])}{m["post"]}', html)


if __name__ == "__main__":
    f = PAGE / "index.html"; old = f.read_text(encoding="utf-8"); new = stamped(old)
    if new != old: f.write_text(new, encoding="utf-8", newline="")
    print("stamped" if new != old else "already current")

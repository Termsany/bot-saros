"""The paper page in files (owner, 2026-11-11): deploy/vps/page/index.html + assets/ (page.css, i18n/live/bots/board.js).
Every asset is linked by its content hash, so a browser never pairs a new page with an old script, and deploy.sh
installs the assets before the page."""
import importlib.util, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PAGE = ROOT / "deploy" / "vps" / "page"
spec = importlib.util.spec_from_file_location("stamp", PAGE / "stamp.py"); stamp = importlib.util.module_from_spec(spec); spec.loader.exec_module(stamp)
HTML = (PAGE / "index.html").read_text(encoding="utf-8")


class PaperPageFilesTests(unittest.TestCase):
    def test_every_link_carries_its_files_current_hash(self):
        # editing a script without `python deploy/vps/page/stamp.py` fails here
        self.assertEqual(stamp.stamped(HTML), HTML)

    def test_the_page_links_every_asset_and_nothing_missing(self):
        linked = re.findall(r'(?:src|href)="assets/([a-z0-9_]+\.(?:js|css))\?v=[0-9a-f]{12}"', HTML)
        self.assertEqual(sorted(linked), sorted(p.name for p in (PAGE / "assets").iterdir()))
        self.assertEqual(linked[0], "page.css")

    def test_the_scripts_load_in_order_at_the_end_of_the_body_as_classic_scripts(self):
        # one shared scope: i18n's words, then the trend bot and its price stream, the bots, the leaderboard
        tags = re.findall(r'<script src="assets/([a-z0-9_]+)\.js\?v=[0-9a-f]+"></script>', HTML)
        self.assertEqual(tags, ["i18n", "live", "bots", "board"])
        self.assertNotRegex(HTML, r'<script[^>]+(defer|async|type="module")')
        self.assertLess(HTML.index('src="assets/board.js'), HTML.index("</body>"))
        self.assertGreater(HTML.index('src="assets/i18n.js'), HTML.index('<div class="wrap"'))   # FIXED reads the page's text

    def test_deploy_installs_the_assets_before_the_page_and_checks_them(self):
        d = (ROOT / "deploy" / "vps" / "deploy.sh").read_text(encoding="utf-8")
        body = d[d.index("deploy_page() {"):d.index("verify_page() {")]
        self.assertLess(body.index('"$PAGE_ASSETS/"'), body.index('"$PAGE"\n'))
        self.assertIn('install -d -o raqm -g www-data -m 755 "$PAGE_ASSETS"', body)
        verify = d[d.index("verify_page() {"):]
        self.assertIn('check_file "deploy/vps/page/assets/${f##*/}" "$PAGE_ASSETS/${f##*/}"', verify)


if __name__ == "__main__":
    unittest.main()

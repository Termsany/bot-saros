"""Every API endpoint, by method and path (development-plan 3.2): splitting app/main.py into routers must not add,
drop or rename one. After a deliberate change, update api_routes.txt in the same PR."""
import sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


class ApiRoutesTests(unittest.TestCase):
    def test_the_route_table_is_the_expected_one(self):
        from app.main import app
        from app.routes import all_routes
        now = sorted(f"{m} {r.path}" for r in all_routes(app) for m in (getattr(r, "methods", None) or ()))
        expected = [l for l in (HERE / "api_routes.txt").read_text(encoding="utf-8").splitlines() if l]
        self.assertEqual(now, expected)

    def test_the_auth_check_walks_the_routers_too(self):
        from app.main import app
        from app.routes import all_routes
        paths = {r.path for r in all_routes(app)}
        self.assertIn("/api/user/bots", paths); self.assertIn("/api/admin/invites", paths)
        self.assertGreater(len(paths), len([r for r in app.routes if hasattr(r, "methods")]))


if __name__ == "__main__":
    unittest.main()

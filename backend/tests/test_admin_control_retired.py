"""The admin overview crashed (KeyError 'wave_flats') on a database written before wave_flats was retired (PR #20)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import admin_control


class RetiredStrategyRowTests(unittest.TestCase):
    def test_old_rows_of_a_retired_strategy_are_ignored(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            con = admin_control.connect(Path(d))
            con.execute("INSERT INTO strategy_desired(strategy,enabled,paused,status,updated_at) VALUES('wave_flats',1,0,'stopped','x')")
            con.close()
            state = admin_control.read_state(Path(d))
            self.assertNotIn("wave_flats", state["strategies"]); self.assertIn("trend_daily", state["strategies"])


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for app.admin_users.compute_finance_summary and the TIER_PRICES_USD mirror
that backs the admin "المالية" (Finance) tab. Pure arithmetic — no network/DB calls.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import admin_users


class TierPricesSyncTests(unittest.TestCase):
    """TIER_PRICES_USD must always match lib/strategies.ts TIERS — the real source of truth."""

    def test_mirror_matches_lib_strategies_ts(self):
        ts = (ROOT / "lib" / "strategies.ts").read_text(encoding="utf-8")
        block_match = re.search(r"export const TIERS\s*=\s*\[(.*?)\n\]", ts, re.S)
        self.assertIsNotNone(block_match, "could not find TIERS array in lib/strategies.ts")
        block = block_match.group(1)
        entries = re.findall(r'id:"(\w+)".*?price:"(\d+)\$"', block)
        self.assertTrue(entries, "could not parse any {id, price} pairs out of TIERS")
        parsed_prices = {tier_id: int(price) for tier_id, price in entries}
        self.assertEqual(parsed_prices, admin_users.TIER_PRICES_USD,
                          "admin_users.TIER_PRICES_USD drifted from lib/strategies.ts TIERS — update both")


class ComputeFinanceSummaryTests(unittest.TestCase):
    def test_known_plan_counts_produce_correct_mrr_and_per_tier(self):
        plan_counts = {"free": 10, "starter": 5, "pro": 3, "elite": 1}
        out = admin_users.compute_finance_summary(plan_counts)
        # 5*29 + 3*59 + 1*99 + 10*0 = 145 + 177 + 99 = 421
        self.assertEqual(out["mrr_usd"], 421)
        self.assertEqual(out["per_tier"]["starter"], {"users": 5, "price_usd": 29, "revenue_usd": 145})
        self.assertEqual(out["per_tier"]["pro"], {"users": 3, "price_usd": 59, "revenue_usd": 177})
        self.assertEqual(out["per_tier"]["elite"], {"users": 1, "price_usd": 99, "revenue_usd": 99})
        self.assertEqual(out["per_tier"]["free"], {"users": 10, "price_usd": 0, "revenue_usd": 0})
        self.assertEqual(out["free_users"], 10)
        self.assertEqual(out["paying_users"], 9)
        self.assertEqual(out["total_users"], 19)

    def test_empty_plan_counts_is_zero_not_an_error(self):
        out = admin_users.compute_finance_summary({})
        self.assertEqual(out["mrr_usd"], 0)
        self.assertEqual(out["per_tier"], {})
        self.assertEqual(out["paying_users"], 0)
        self.assertEqual(out["free_users"], 0)
        self.assertEqual(out["total_users"], 0)

    def test_unknown_tier_id_prices_at_zero_instead_of_raising(self):
        out = admin_users.compute_finance_summary({"mystery_tier": 2})
        self.assertEqual(out["per_tier"]["mystery_tier"]["price_usd"], 0)
        self.assertEqual(out["mrr_usd"], 0)
        # not "free" so counted as paying even though it earns nothing — still correct accounting
        self.assertEqual(out["paying_users"], 2)


if __name__ == "__main__":
    unittest.main()

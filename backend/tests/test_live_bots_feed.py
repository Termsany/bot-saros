"""
TDD regression tests for the read-only live VPS paper-bots data layer.

All HTTP is faked via httpx.MockTransport — these tests never touch the
network, never contact bot.da3m.io, and never place/authenticate any
exchange order.
"""
import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import live_bots_feed as feed


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _sample_payload(updated_dt, *, open_count=1):
    return {
        "updated": _iso(updated_dt),
        "mode": "paper",
        "stats": {"closed": 5, "wins": 3, "losses": 2, "realized": 12.5, "unrealized": -1.5, "open": open_count},
        "positions": [
            {"symbol": "BTC/USDT", "side": "long", "entry": 60000, "price": 61000, "qty": 0.01,
             "margin": 10, "sl": 59000, "tp": 63000, "pnl": 10.0, "pnl_pct": 1.6, "opened": _iso(updated_dt)}
        ],
        "history": [
            {"symbol": "ETH/USDT", "side": "short", "entry": 3000, "exit": 2900, "qty": 1, "pnl": 100.0}
        ],
        "leverage": 3,
    }


def _mock_transport(responses):
    """responses: dict url -> ('json', payload) | ('status', code) | ('raise', exc)"""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for key, action in responses.items():
            if request.url.path.endswith(key):
                kind = action[0]
                if kind == "json":
                    return httpx.Response(200, json=action[1])
                if kind == "status":
                    return httpx.Response(action[1], json={})
                if kind == "raise":
                    raise action[1]
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


class StrategyMappingTests(unittest.TestCase):
    def test_all_seven_real_bots_are_mapped_to_distinct_files(self):
        expected = {
            "trend_daily": "status.json",
            "listing_short": "listing.json",
            "momentum_ls": "momentum.json",
            "ratio_trend": "ratio.json",
            "vol_breakout": "breakout.json",
            "rsi2_pullback": "rsi2.json",
            "trend_breakout": "tbreak.json",
        }
        self.assertEqual(feed.STRATEGY_FILES, expected)
        self.assertEqual(len(set(expected.values())), 7)

    def test_no_service_strategies_are_explicit(self):
        self.assertEqual(set(feed.NO_SERVICE_STRATEGIES), {"wave_flats", "default"})
        for sid in feed.NO_SERVICE_STRATEGIES:
            entry = feed.no_service_entry(sid)
            self.assertEqual(entry["status"], "no_service")
            self.assertIsNone(entry["updated"])
            self.assertEqual(entry["positions"], [])
            self.assertEqual(entry["history"], [])

    def test_no_service_strategies_never_fetched_over_network(self):
        async def run():
            # transport that explodes on ANY request — if fetch_all tried to
            # hit the network for wave_flats/default this test would fail.
            def boom(request):
                raise AssertionError(f"unexpected network call: {request.url}")
            transport = httpx.MockTransport(boom)
            result = await feed.fetch_all(strategies=["wave_flats", "default"], transport=transport)
            return result
        result = asyncio.run(run())
        self.assertEqual(result["wave_flats"]["status"], "no_service")
        self.assertEqual(result["default"]["status"], "no_service")


class StalenessDetectionTests(unittest.TestCase):
    def test_fresh_update_is_running(self):
        now = datetime.now(timezone.utc)
        entry = feed.normalize_bot_file("trend_daily", _sample_payload(now - timedelta(seconds=5)), now=now, stale_after=300)
        self.assertEqual(entry["status"], "running")

    def test_old_update_is_stale(self):
        now = datetime.now(timezone.utc)
        entry = feed.normalize_bot_file("trend_daily", _sample_payload(now - timedelta(seconds=600)), now=now, stale_after=300)
        self.assertEqual(entry["status"], "stale")

    def test_boundary_is_inclusive_of_threshold(self):
        now = datetime.now(timezone.utc)
        entry = feed.normalize_bot_file("trend_daily", _sample_payload(now - timedelta(seconds=300)), now=now, stale_after=300)
        self.assertEqual(entry["status"], "running")
        entry2 = feed.normalize_bot_file("trend_daily", _sample_payload(now - timedelta(seconds=301)), now=now, stale_after=300)
        self.assertEqual(entry2["status"], "stale")

    def test_missing_or_unparseable_updated_is_unavailable(self):
        now = datetime.now(timezone.utc)
        payload = _sample_payload(now)
        payload["updated"] = "not-a-timestamp"
        entry = feed.normalize_bot_file("trend_daily", payload, now=now, stale_after=300)
        self.assertEqual(entry["status"], "unavailable")

        payload2 = _sample_payload(now)
        del payload2["updated"]
        entry2 = feed.normalize_bot_file("trend_daily", payload2, now=now, stale_after=300)
        self.assertEqual(entry2["status"], "unavailable")

    def test_fetch_failure_yields_unavailable_with_no_fabricated_data(self):
        entry = feed.normalize_bot_file("trend_daily", None)
        self.assertEqual(entry["status"], "unavailable")
        self.assertEqual(entry["positions"], [])
        self.assertEqual(entry["history"], [])
        self.assertEqual(entry["stats"], {})


class PerFileFetchIsolationTests(unittest.TestCase):
    def test_one_bot_failing_does_not_break_the_others(self):
        now = datetime.now(timezone.utc)
        transport = _mock_transport({
            "status.json": ("json", _sample_payload(now)),
            "listing.json": ("raise", httpx.ConnectTimeout("boom")),
            "momentum.json": ("status", 500),
            "ratio.json": ("json", _sample_payload(now)),
            "breakout.json": ("raise", httpx.ConnectError("refused")),
            "rsi2.json": ("json", _sample_payload(now)),
            "tbreak.json": ("json", _sample_payload(now - timedelta(seconds=9999))),
        })
        result = asyncio.run(feed.fetch_all(transport=transport, base="https://bot.da3m.io", stale_after=300))
        self.assertEqual(result["trend_daily"]["status"], "running")
        self.assertEqual(result["listing_short"]["status"], "unavailable")
        self.assertEqual(result["momentum_ls"]["status"], "unavailable")
        self.assertEqual(result["ratio_trend"]["status"], "running")
        self.assertEqual(result["vol_breakout"]["status"], "unavailable")
        self.assertEqual(result["rsi2_pullback"]["status"], "running")
        self.assertEqual(result["trend_breakout"]["status"], "stale")
        self.assertEqual(result["wave_flats"]["status"], "no_service")
        self.assertEqual(result["default"]["status"], "no_service")
        # 9 total strategies always present, regardless of individual failures
        self.assertEqual(len(result), 9)

    def test_full_outage_returns_all_unavailable_not_an_exception(self):
        def boom(request):
            raise httpx.ConnectError("vps down")
        transport = httpx.MockTransport(boom)
        result = asyncio.run(feed.fetch_all(transport=transport))
        for sid in feed.STRATEGY_FILES:
            self.assertEqual(result[sid]["status"], "unavailable")


class AggregationTests(unittest.TestCase):
    def test_aggregate_summary_sums_only_real_bot_data(self):
        now = datetime.now(timezone.utc)
        transport = _mock_transport({
            "status.json": ("json", _sample_payload(now, open_count=2)),
            "listing.json": ("json", _sample_payload(now, open_count=1)),
            "momentum.json": ("status", 404),
            "ratio.json": ("json", _sample_payload(now, open_count=0)),
            "breakout.json": ("status", 404),
            "rsi2.json": ("status", 404),
            "tbreak.json": ("status", 404),
        })
        result = asyncio.run(feed.fetch_all(transport=transport))
        summary = feed.aggregate_summary(result)
        self.assertEqual(summary["strategies_total"], 9)
        self.assertEqual(summary["running"], 3)
        self.assertEqual(summary["unavailable"], 4)
        self.assertEqual(summary["no_service"], 2)
        self.assertEqual(summary["open_positions"], 3)
        self.assertAlmostEqual(summary["realized_pnl"], 37.5, places=2)
        self.assertAlmostEqual(summary["unrealized_pnl"], -4.5, places=2)


class NoLiveTradingCallsTests(unittest.TestCase):
    """Static regression guard: this module must never place or authenticate
    exchange orders — it is read-only HTTP GET against public status files."""

    def test_module_never_imports_exchange_or_order_machinery(self):
        import inspect
        src = inspect.getsource(feed)
        for forbidden in ("ccxt", "create_order", "exchange_manager", "place_order"):
            self.assertNotIn(forbidden, src, f"forbidden reference found: {forbidden}")

    def test_only_http_get_is_used(self):
        import inspect
        src = inspect.getsource(feed)
        self.assertNotIn(".post(", src)
        self.assertNotIn(".put(", src)
        self.assertNotIn(".delete(", src)


if __name__ == "__main__":
    unittest.main()

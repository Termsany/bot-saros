"""The against-the-crowd paper bot (owner, 2026-11-07; research §29): momentum_ls's weekly basket ranked by the
accounts' long/short ratio — long the crowd's shorts, short its longs, among the top 20 by volume."""
import json, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_full_review_code as base
botmod = base.botmod

DAY = 86_400_000
COINS = [f"C{i}" for i in range(25)]                         # C0 biggest volume; C24 smallest
RATIO = {c: 1.0 + i * 0.1 for i, c in enumerate(COINS)}    # C0 1.0 (the crowd least long) ... C24 3.4


class FakeEx:
    def __init__(self, young=()):
        self.young = set(young)
    def fetch_tickers(self):
        return {f"{c}/USDT:USDT": {"quoteVolume": 1000 - i} for i, c in enumerate(COINS)}
    def fetch_ohlcv(self, sym, tf, limit=200):
        c = sym.split("/")[0]; n = 100 if c in self.young else limit
        v = 1000.0 - COINS.index(c)
        return [[i * DAY, 1, 1, 1, 1.0, v] for i in range(n)]
    def fetch_ticker(self, sym):
        return {"last": 1.0}
    def fapiDataGetGlobalLongShortAccountRatio(self, params):
        c = params["symbol"][:-4]
        assert params["period"] == "1h" and params["limit"] == 72
        return [{"longShortRatio": str(RATIO[c])} for _ in range(72)]


class RetailFadeTests(unittest.TestCase):
    def rank(self, ex):
        with mock.patch.dict(botmod.MOM, botmod.RETAIL), \
             mock.patch.object(botmod, "listing_markets", return_value=[(f"{c}/USDT:USDT", 0, 0) for c in COINS]):
            return botmod.momentum_rank(ex)

    def test_the_top_20_ranked_with_the_crowds_most_long_first(self):
        r = self.rank(FakeEx())
        self.assertEqual([s.split("/")[0] for s, _ in r], [f"C{i}" for i in range(19, -1, -1)])   # top 20 only
        self.assertAlmostEqual(r[0][1], 2.9)
        r = self.rank(FakeEx(young={"C3"}))                                              # under 150 days: out
        self.assertNotIn("C3/USDT:USDT", [s for s, _ in r]); self.assertIn("C20/USDT:USDT", [s for s, _ in r])

    def test_the_weekly_basket_goes_against_the_crowd_and_writes_its_own_page_file(self):
        state = {"positions": {}, "stats": {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}, "history": []}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, \
             mock.patch.dict(botmod.CONFIG, {"paper_trading": True, "public_dir": d, "public_name": "retail_fade", "notify": False,
                                             "leverage": 2, "trade_amount_usdt": 20}), \
             mock.patch.dict(botmod.MOM, botmod.RETAIL), \
             mock.patch.object(botmod, "listing_markets", return_value=[(f"{c}/USDT:USDT", 0, 0) for c in COINS]), \
             mock.patch.object(botmod, "load_state", return_value=state), mock.patch.object(botmod, "save_state"), \
             mock.patch.object(botmod, "process_paper_closes"), mock.patch.object(botmod, "position_size", return_value=20.0):
            botmod.run_once_momentum(FakeEx())
            files = sorted(p.name for p in Path(d).glob("*.json"))
            page = json.loads((Path(d) / "retail_fade.json").read_text(encoding="utf-8"))
        longs = sorted(s.split("/")[0] for s, p in state["positions"].items() if p["side"] == "long")
        shorts = sorted(s.split("/")[0] for s, p in state["positions"].items() if p["side"] == "short")
        self.assertEqual((longs, shorts), (["C0", "C1", "C2"], ["C17", "C18", "C19"]))
        self.assertEqual(files, ["retail_fade.json"])                                   # momentum.json is the other bot's
        self.assertEqual({p["symbol"]: p["ratio"] for p in page["positions"]}["C0/USDT"], 1.0)
        self.assertNotIn("ret", page["positions"][0])
        self.assertEqual(datetime.fromisoformat(page["next_rebalance"]).weekday(), 2)   # Wednesdays, as the study
        self.assertEqual(page["ranking"][0]["symbol"], "C19/USDT")

    def test_momentum_itself_is_unchanged(self):
        self.assertEqual((botmod.MOM["score"], botmod.MOM["top"], botmod.MOM["n"], botmod.MOM["weekday"], botmod.MOM["min_ranked"]),
                         ("return", 50, 5, 0, 20))
        with mock.patch.dict(botmod.CONFIG, {}, clear=False):
            botmod.CONFIG.pop("public_name", None)
            self.assertEqual(botmod.momentum_public_name(), "momentum")


if __name__ == "__main__":
    unittest.main()

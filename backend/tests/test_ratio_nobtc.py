"""The second ratio paper bot: BTC and ETH left out, its own file and its own name (owner, 2026-11-07; research §25)."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_full_review_code as base
botmod = base.botmod


class FakeEx:
    """Seven-plus coins by volume, BTC and ETH the biggest; 150 daily candles each."""
    VOL = {"BTC": 900, "ETH": 800, "SOL": 70, "BNB": 60, "XRP": 50, "DOGE": 40, "ADA": 30, "AVAX": 20, "LINK": 10}
    def fetch_tickers(self):
        return {f"{c}/USDT:USDT": {"quoteVolume": v} for c, v in self.VOL.items()}
    def fetch_ohlcv(self, sym, tf, limit=200):
        v = self.VOL[sym.split("/")[0]]
        return [[i * 86_400_000, 1, 1, 1, 1.0, float(v)] for i in range(151)]


class RatioNoBtcTests(unittest.TestCase):
    def members(self, exclude):
        with mock.patch.object(botmod, "listing_markets", return_value=[(f"{c}/USDT:USDT", 0, 0) for c in FakeEx.VOL]), \
             mock.patch.dict(botmod.RATIO, {"exclude": exclude}):
            return [m.split("/")[0] for m in botmod.ratio_members(FakeEx(), {})]

    def test_btc_and_eth_are_left_out_and_the_next_coins_come_in(self):
        self.assertEqual(self.members([]), sorted(["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]))
        self.assertEqual(self.members(["BTC", "ETH"]), sorted(["SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK"]))

    def test_its_page_file_is_its_own_and_the_first_bots_stays_ratio_json(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            with mock.patch.dict(botmod.CONFIG, {"public_dir": d, "public_name": "ratio_nobtc"}):
                botmod.write_ratio_status({"pairs": {}, "history": [], "stats": {}}, {})
            with mock.patch.dict(botmod.CONFIG, {"public_dir": d}):
                botmod.CONFIG.pop("public_name", None)
                botmod.write_ratio_status({"pairs": {}, "history": [], "stats": {}}, {})
            self.assertEqual(sorted(p.name for p in Path(d).glob("*.json")), ["ratio.json", "ratio_nobtc.json"])
            self.assertEqual(json.loads((Path(d) / "ratio_nobtc.json").read_text(encoding="utf-8"))["margin"],
                             botmod.CONFIG.get("trade_amount_usdt"))

    def test_its_telegram_messages_say_which_bot(self):
        sent = []
        with mock.patch.dict(botmod.CONFIG, {"notify": True, "label": "ratio no BTC/ETH"}), \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), \
             mock.patch.object(botmod, "_tg_put", side_effect=sent.append):
            botmod.notify("🔝 ratio: x")
        self.assertEqual(sent[0][2], "[ratio no BTC/ETH] 🔝 ratio: x")


if __name__ == "__main__":
    unittest.main()

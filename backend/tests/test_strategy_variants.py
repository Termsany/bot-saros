"""Named variants (owner, 2026-11-11; bots/variants.py): `--strategy retail_fade` instead of momentum_ls + four flags.
A paper unit moved to its variant name must run exactly as before: the same settings, the same state and log files."""
import json, os, shlex, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bots import variants

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "BINANCE_ENV": "demo"}


def show(argv):
    r = subprocess.run([sys.executable, str(ROOT / "bot.py"), *argv, "--show-config"], capture_output=True, text=True,
                       encoding="utf-8", env=ENV, cwd=ROOT, timeout=120)
    return r.returncode, (json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else r.stderr)


def unit_args(text):
    line = next(l for l in text.splitlines() if l.startswith("ExecStart="))
    return shlex.split(line[line.index("bot.py") + len("bot.py"):])


# each unit's command before it moved to its variant (2026-11-11), the old flags as they were typed: still valid, and
# the unit's new command must resolve to the very same settings
LEGACY = {
    "raqm-retail-fade.service": '--paper --strategy momentum_ls --momentum-retail --public-name retail_fade --label "against the crowd" --amount 100 --leverage 2 --poll 60 --notify --public /var/www/bot.da3m.io --state state_retail_fade.json',
    "raqm-rsi2-btc.service": '--paper --strategy rsi2_pullback --rsi2-btc-ma 200 --public-name rsi2_btc --label "RSI-2 + BTC filter" --amount 100 --leverage 2 --poll 60 --notify --public /var/www/bot.da3m.io --state state_rsi2_btc.json',
    "raqm-ratio-nobtc.service": '--paper --strategy ratio_trend --ratio-exclude BTC,ETH --public-name ratio_nobtc --label "ratio no BTC/ETH" --amount 40 --leverage 2 --poll 60 --notify --public /var/www/bot.da3m.io --state state_ratio_nobtc.json',
    "raqm-ratio-trail.service": '--paper --strategy ratio_trend --ratio-exclude BTC,ETH --ratio-trail 0.20 --public-name ratio_trail --label "ratio trail 20%" --amount 40 --leverage 2 --poll 60 --notify --public /var/www/bot.da3m.io --state state_ratio_trail.json',
    "raqm-ratio-trail-btc.service": '--paper --strategy ratio_trend --ratio-trail 0.20 --public-name ratio_trail_btc --label "ratio trail 20% BTC/ETH" --amount 100 --leverage 2 --poll 60 --notify --public /var/www/bot.da3m.io --state state_ratio_trail_btc.json',
}


class VariantUnitTests(unittest.TestCase):
    def test_each_paper_unit_on_its_variant_runs_exactly_as_its_old_command(self):
        for name, old in LEGACY.items():
            new = unit_args((ROOT / "deploy" / "vps" / name).read_text(encoding="utf-8"))
            self.assertIn(new[new.index("--strategy") + 1], variants.VARIANTS, name)      # the unit names its variant
            ca, cb = show(shlex.split(old)), show(new)
            self.assertEqual(ca[0], 0, (name, ca)); self.assertEqual(cb[0], 0, (name, cb))
            sa, sb = dict(ca[1]), dict(cb[1])
            self.assertIsNone(sa.pop("variant")); sb.pop("variant")
            self.assertEqual(sa, sb, name)


class VariantRuleTests(unittest.TestCase):
    def test_a_variant_resolves_to_its_base_options_name_and_its_own_state(self):
        rc, c = show(["--paper", "--strategy", "ratio_net_nobtc"])
        self.assertEqual(rc, 0, c)
        self.assertEqual((c["variant"], c["strategies"], c["public_name"], c["state"]), ("ratio_net_nobtc", ["ratio_trend"], "ratio_net_nobtc", "state_ratio_net_nobtc.json"))
        self.assertEqual((c["RATIO"]["exclude"], c["RATIO"]["net"]), (["BTC", "ETH"], True))

    def test_a_paper_only_variant_still_refuses_live(self):
        rc, err = show(["--live", "--strategy", "retail_fade"])
        self.assertNotEqual(rc, 0); self.assertIn("paper momentum_ls only", err)

    def test_a_flag_that_disagrees_with_the_variant_is_refused_and_one_that_agrees_is_fine(self):
        rc, err = show(["--paper", "--strategy", "rsi2_btc", "--rsi2-btc-ma", "100"])
        self.assertNotEqual(rc, 0); self.assertIn("disagrees with the variant rsi2_btc", err)
        self.assertEqual(show(["--paper", "--strategy", "rsi2_btc", "--rsi2-btc-ma", "200"])[0], 0)

    def test_a_variant_runs_alone(self):
        rc, err = show(["--paper", "--strategy", "retail_fade,trend_daily"])
        self.assertNotEqual(rc, 0); self.assertIn("runs alone", err)

    def test_the_real_bots_keep_their_base_names(self):
        # the variant only names a paper/Demo unit: live and Demo units keep `--strategy %i`, the ledger keeps the base
        for u in ("raqm-live@.service", "raqm-demo@.service"):
            self.assertIn("--strategy %i", (ROOT / "deploy" / "vps" / u).read_text(encoding="utf-8"))
        self.assertFalse(set(variants.VARIANTS) & {"trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend"})
        self.assertTrue(all(v["base"] in {"momentum_ls", "rsi2_pullback", "ratio_trend"} for v in variants.VARIANTS.values()))


if __name__ == "__main__":
    unittest.main()

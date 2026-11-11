"""Named variants of the strategies (owner, 2026-11-11): `--strategy <variant>` instead of a base strategy plus a row of
flags. A variant is a base strategy with fixed options, a public name (its page file, its paper close requests) and a
Telegram label. It runs AS its base strategy — the risk ledger, the IPC folder, LIVE_READY_STRATEGIES and the real
bots' units keep the base name — so naming a variant changes nothing a real-money bot reads.

Every option is one of bot.py's flags, and the CLI applies it exactly as that flag, with the same checks (a paper-only
option still refuses --live). The old flags still work; a flag given next to a variant must agree with it.
`python bot.py --strategy <variant> --show-config` prints what a variant resolves to.
"""

VARIANTS = {
    # momentum_ls ranked against the crowd's long/short ratio (research §29) — paper only
    "retail_fade": {"base": "momentum_ls", "label": "against the crowd", "options": {"momentum_retail": True}},
    # momentum_ls with a new basket every day, held one day (owner 2026-11-11) — paper only
    "momentum_daily": {"base": "momentum_ls", "label": "momentum daily", "options": {"mom_daily": True}},
    # RSI-2 entries only while BTC closes above its 200-day average (research §28)
    "rsi2_btc": {"base": "rsi2_pullback", "label": "RSI-2 + BTC filter", "options": {"rsi2_btc_ma": 200}},
    # the ratio trend without BTC and ETH (research §25)
    "ratio_nobtc": {"base": "ratio_trend", "label": "ratio no BTC/ETH", "options": {"ratio_exclude": "BTC,ETH"}},
    # ... and out of a pair when its ratio falls 20% from its best since entry — paper pairs only
    "ratio_trail": {"base": "ratio_trend", "label": "ratio trail 20%", "options": {"ratio_exclude": "BTC,ETH", "ratio_trail": 0.20}},
    "ratio_trail_btc": {"base": "ratio_trend", "label": "ratio trail 20% BTC/ETH", "options": {"ratio_trail": 0.20}},
    # the netted book without BTC and ETH: the real-money candidate (docs/ratio-trend-live-plan.md, research §34)
    "ratio_net_nobtc": {"base": "ratio_trend", "label": "ratio net no BTC/ETH", "options": {"ratio_exclude": "BTC,ETH", "ratio_net": True}},
}
# the flags a variant may set, and their defaults (bot.py's argparse): a flag still at its default takes the variant's
OPTION_DEFAULTS = {"momentum_retail": False, "mom_daily": False, "rsi2_btc_ma": 0, "ratio_exclude": "", "ratio_trail": 0.0, "ratio_net": False}


def resolve(args):
    """Turn `--strategy <variant>` into its base strategy and flags, in place; returns the variant's name or None.
    Raises ValueError when a flag given next to the variant disagrees with it (or when a variant is combined)."""
    names = [s.strip() for s in (args.strategy or "").split(",") if s.strip()]
    hits = [n for n in names if n in VARIANTS]
    if not hits:
        return None
    if len(names) != 1:
        raise ValueError(f"a variant runs alone: {', '.join(hits)} can't be combined with other strategies")
    name = hits[0]; v = VARIANTS[name]
    for opt, val in v["options"].items():
        have = getattr(args, opt)
        if have != OPTION_DEFAULTS[opt] and have != val:
            raise ValueError(f"--{opt.replace('_', '-')} {have!r} disagrees with the variant {name} ({val!r})")
        setattr(args, opt, val)
    args.strategy = v["base"]
    if args.public_name is None: args.public_name = name
    if args.label is None: args.label = v["label"]
    return name

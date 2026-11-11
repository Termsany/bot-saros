"""
Crypto Auto-Trading Bot — 7 Strategies + 20 High-Liquidity Pairs
إيشيموكو + داو + جان + موجي + كلاسيكي + دعوم/مقاومات + RSI/MACD
Paper Trading (وهمي) — يعرض الصفقات بـ entry/SL/TP
python bot.py --paper   (وهمي كل 60s)  |  python bot.py --once  (مرة واحدة)
python bot.py --dashboard  (يشغّل البوت + داشبورد http://localhost:8765)
"""
import ccxt, pandas as pd, numpy as np, time, json, os, re, uuid, threading, http.server, socketserver, webbrowser
from datetime import datetime, timezone
from pathlib import Path
import strategies_advanced as adv
from backend.app.execution_safety import AmbiguousFill, authoritative_position_state, futures_net_pnl, linear_contracts_from_margin, normalize_filled_contracts
from backend.app import risk_manager as riskmgr
from backend.app.multi_leg_execution import MultiLegExecutionEngine
from backend.app import live_activation
import sys
# `python bot.py` runs this file as __main__ while the strategies in bots/ `import bot`: both names must be this one
# module, or they would load a second copy with its own CONFIG, state paths and entry block
if __name__ == "__main__": sys.modules["bot"] = sys.modules[__name__]

try:
    from dotenv import load_dotenv; load_dotenv()
except: pass

CONFIG = {
    # 20 زوج سيولة عالية — Binance USDT-M Futures (لونج/شورت)
    "market": "future",  # future = USDT-M perpetual, spot = spot
    "leverage": 5,
    "margin_type": "ISOLATED",
    "symbols": [
        "BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT",
        "DOGE/USDT","ADA/USDT","AVAX/USDT","1000SHIB/USDT","DOT/USDT",
        "LINK/USDT","TRX/USDT","LTC/USDT","BCH/USDT","UNI/USDT",
        "ETC/USDT","NEAR/USDT","1000PEPE/USDT","ARB/USDT","SUI/USDT",
    ],
    "timeframe": "4h",
    "weights": {"ichimoku":0.10,"dow":0.05,"gann":0.05,"elliott":0.08,"classical":0.05,"sr":0.05,"rsi_macd":0.12,"smc":0.10,"vwap":0.07,"supertrend":0.07,"bollinger":0.07,"harmonic":0.05,"ict":0.05,"heikin":0.05,"ai":0.04},
    "enabled_strategies": ["ict"],  # measured results per strategy: lib/strategy-stats.json (research/README.md)
    # Engine rules below match backtest.py and lib/strategy-engine.ts, so live trading behaves like the backtests:
    # |score| > 0.35 to enter, 3 candles of cooldown after a trade, fixed 3%/6% SL/TP, ADX >= 10, range filter.
    "buy_threshold": 0.35, "strong_buy": 0.35, "sell_threshold": -0.35, "strong_sell": -0.35,
    "trade_amount_usdt": 20,
    # === Week 1: Risk + Filters ===
    "risk_pct": 2.0,              # 2% من المحفظة لكل صفقة (لو balance معروف)
    "use_percent_risk": False,     # False = 20$ ثابت، True = % من الرصيد
    "adx_threshold": 10,          # فلتر ADX — أقل من 10 = سوق بلا اتجاه، لا تدخل (نفس الباك تست)
    "vol_filter": False,            # لازم حجم > متوسط 20
    "htf_filter": False,            # لا تدخل عكس ترند 4h
    "htf_timeframe": "4h",
    "dynamic_sl_tp": False, "atr_sl_mult": 2.0, "atr_tp_mult": 3.0, "atr_period": 14,  # ATR exits helped some strategies and hurt others in testing
    "regime_filter": True, "regime_adx_trend": 20,
    "max_daily_loss_pct": 5.0,     # لو خسر 5% في يوم يوقف
    "breakeven_enabled": True,         # بعد أول هدف ينقل الوقف لنقطة الدخول
    "breakeven_trigger_pct": 0.50,     # 50% من المسافة للهدف = أول هدف
    "breakeven_offset_pct": 0.001,     # 0.1% فوق الدخول لتغطية العمولة
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.06,
    "max_open_positions": 5,
    "cooldown_bars": 3,            # شموع انتظار بعد قفل أي صفقة على نفس الزوج (نفس الباك تست)
    "paper_trading": True,
    "poll_seconds": 60,
    "state_file": "state.json",
    "log_file": "trades.log",
    "dashboard_port": 8765,
}

STATE_PATH = Path(__file__).parent / CONFIG["state_file"]
LOG_PATH   = Path(__file__).parent / CONFIG["log_file"]
# shared Central Risk Manager ledger across ALL strategy processes and the dashboard API (RAQM_RISK_DIR)
RISK_PATH  = riskmgr.ledger_dir(Path(__file__).parent) / "risk_state.json"
ACTIVATION_PATH = riskmgr.ledger_dir(Path(__file__).parent) / "live_activation.sqlite3"

# These strategies route real orders through the same proven primitives (place_order + OCO stop/TP,
# risk_manager.pre_trade_gate/register_open_risk, reconcile_live, close_live_position/check_sl_tp):
# single-leg ones via _single_leg_live_entry/_single_leg_live_exit (or try_enter_trend for trend_daily),
# multi-leg ones via the durable basket engine (_phase2_live_basket). --live is gated on this list,
# not on a single hardcoded strategy name. All seven passed end to end on Binance Demo (PR #16, scripts/demo_e2e.py).
LIVE_READY_STRATEGIES = {"trend_daily", "vol_breakout", "rsi2_pullback",
                          "trend_breakout", "listing_short", "momentum_ls", "ratio_trend"}
# Dropped by the owner on 2026-10-29: refused by --strategy, paper or live. "ict" is the default indicator
# ensemble — the dashboard's paper loop still uses it, it just can't be run as a bot of its own.
RETIRED_STRATEGIES = {"ict", "wave_flats"}

# Crude correlation grouping for the correlated-risk cap: nearly every altcoin trades as
# BTC-beta, so "majors" vs "alts" is the conservative default until a real correlation
# matrix is computed. Override via CONFIG["correlation_groups"] = {symbol: group}.
_CORRELATION_MAJORS = {"BTC/USDT", "ETH/USDT"}


def _correlation_group(symbol):
    override = (CONFIG.get("correlation_groups") or {}).get(symbol)
    if override:
        return override
    base = symbol.split(":")[0]
    return "majors" if base in _CORRELATION_MAJORS else "alts"


def _current_strategy_name():
    if trend_mode(): return "trend_daily"
    if wave_mode(): return "wave_flats"
    if listing_mode(): return "listing_short"
    if momentum_mode(): return "momentum_ls"
    if ratio_mode(): return "ratio_trend"
    if breakout_mode(): return "vol_breakout"
    if rsi2_mode(): return "rsi2_pullback"
    if tbreak_mode(): return "trend_breakout"
    enabled = CONFIG.get("enabled_strategies") or []
    return enabled[0] if enabled else "default"


def _live_activation_gate(strategy):
    if binance_env() == "demo":   # the dashboard's Demo yes/no (Demo ledger folder; nothing chosen yet = allowed)
        return live_activation.demo_strategy_allowed(ACTIVATION_PATH, strategy=strategy)
    if binance_env() != "live":
        return True, None
    account = os.getenv("BINANCE_LIVE_ACCOUNT", "").strip()
    return live_activation.live_activation_allowed(ACTIVATION_PATH, strategy=strategy, account=account)


def _live_risk_share(strategy):
    """The activation record's allocation for this strategy (fraction of the aggregate risk budget), or None where no
    activation record applies (paper/Demo). On live, an unreadable/missing allocation returns 0.0 so the risk gate
    refuses the entry instead of silently trading uncapped."""
    if binance_env() != "live":
        return None
    account = os.getenv("BINANCE_LIVE_ACCOUNT", "").strip()
    try:
        share = live_activation.strategy_risk_share(ACTIVATION_PATH, strategy=strategy, account=account)
    except Exception:
        return 0.0
    return share if share and share > 0 else 0.0

def load_state():
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            data.setdefault("positions", {})
            data.setdefault("last_trade", {})
            data.setdefault("stats", {"trades":0,"wins":0,"losses":0,"pnl":0})
            data.setdefault("history", [])
            data.setdefault("pending_orders", {})
            data.setdefault("recovery_required", {})
            if not CONFIG.get("paper_trading"):
                for symbol, pos in data["positions"].items():
                    # contract_size_verified and entry_fee_rate are set at ENTRY time (every live entry
                    # path writes them) — missing them means genuinely pre-verification legacy state.
                    # funding_verified is deliberately close-only (set exclusively by
                    # _refresh_funding_evidence when a position is closed, never at entry) — requiring
                    # it here would flag every freshly-opened, perfectly healthy live position as
                    # needing recovery on every single restart, for any of the 9 strategies. PnL
                    # accounting still fails closed on missing funding evidence at close time via
                    # _funding_pnl(required=True); this load-time gate must not duplicate that check.
                    if pos.get("type") == "paper" or pos.get("contract_size_verified") is not True or pos.get("entry_fee_rate") is None:
                        data["recovery_required"].setdefault(symbol, {"reason": "legacy live position lacks verified contract or fee metadata", "at": datetime.now(timezone.utc).isoformat()})
            return data
        except: pass
    return {"positions":{},"last_trade":{},"stats":{"trades":0,"wins":0,"losses":0,"pnl":0},"history":[],"pending_orders":{},"recovery_required":{}}

def save_state(s):
    _alert_closed_trades(s)
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)

_LAST_BLOCK = {}   # the last entry this bot refused and why (⛔/⏸️ lines): the admin page's "why no trade"

def log(msg):
    ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); line=f"[{ts}] {msg}"
    print(line, flush=True)
    if str(msg).startswith(("⛔", "⏸️")):
        _LAST_BLOCK.update(reason=str(msg).lstrip("⛔⏸️ ").strip(), at=datetime.now(timezone.utc).isoformat())
    try:
        with open(LOG_PATH,"a",encoding="utf-8") as f: f.write(line+"\n")
    except: pass

def in_position(state,symbol): return symbol in state["positions"]
def cooldown_ok(state,symbol):
    last=state["last_trade"].get(symbol)
    if not last: return True
    try:
        mins=(datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()/60
        # same rule as the backtest: wait cooldown_bars candles of the trading timeframe after a trade closes
        tf_min={"15m":15,"30m":30,"1h":60,"2h":120,"4h":240,"1d":1440}.get(CONFIG.get("timeframe","4h"), 240)
        return mins >= int(CONFIG.get("cooldown_bars",3)) * tf_min
    except: return True

# ── the engine, one module per part (engine/): re-exported here — bot.<name> stays the one name the CLI, the API, bots/ and the tests use ──
from engine.exchange import (ED25519_DER_B64_PREFIX, KEYS_CREDENTIAL, STABLES, _TRANSFERS, _binance_keys, _equity_now, _estimate_trade_risk_usdt, _fetch_equity_usdt, _resolve_live_symbol, _resolve_live_symbols, _secret_for_ccxt, _transfers_recent, _universe, binance_env, cycle_symbols, get_exchange, volume_universe)
from engine.notify import (_alert_closed_trades, _paper_close, _r4, _tg_card, _tg_put, _tg_text, _tg_worker, listing_markets, notify, notify_trade, write_public_status)
from engine.analysis import (adx_value, analyze, analyze_wave, atr_value, candles_needed, classical_signal, dow_signal, dynamic_sl_tp, elliott_signal, fetch_ohlcv, gann_signal, htf_trend_ok, ichimoku_signal, regime_detect, rsi_macd_signal, sr_signal, volume_ok, wave_mode)
from engine.sizing import (_capital_plan, _meets_min_order, _strategies_sharing, _strategy_full, daily_pnl_ok, position_size)
from engine.orders import (ENTRY_RECHECK_S, FILL_LOOKUP_WAITS, HISTORY_MAX_PAGES, HISTORY_PAGE, TRADE_WINDOW_MS, _SL_AMEND_FAILED, _active_protective_readback, _amend_exchange_sl, _authoritative_close_fill, _build_futures_params, _cancel_all_protective_orders, _close_failure, _configured_hedge_mode, _contract_meta, _entry_failed_flat, _entry_order_outcome, _exchange_id, _exchange_position_qty, _fee_rate, _fetch_order_by_cid, _fill_from_trades, _funding_pnl, _funding_since, _is_hedge_mode, _mark_sl_recovery, _now_ms, _order_fee_rate, _persist_sl_boundary, _persist_sl_recovery, _position_contract_size, _reconcile_fills_by_client_id, _refresh_fee_evidence, _refresh_funding_evidence, _release_position_risk, _require_verified_close, _retain_unverified_replacement, _row_key, _summed_fee, _trades_since, _usdt_fee_cost, _verify_protective_stop, close_live_position, ensure_futures_setup, place_order)
from engine.positions import (check_sl_tp, try_enter_wave)
from engine.reconcile import (AUDIT_REASON, STOP_AUDIT_S, _ENTRY_BLOCK, _audit_stops, _expect_stop, _held_by_other_strategies, _ipc_dir, _live_label, _protect_pending, _stop_confirmed, _write_json_atomic, reconcile_live)
from engine.ipc import (MANUAL_CLOSE_MAX_AGE_S, PAIR_RE, _CLOSED_WRITTEN, _ipc_shared_with_another_bot, _read_request, _write_closed, process_manual_closes, process_paper_closes, write_live_status)
from engine.entries import (_enter_trend_live, _paper_open, _utc_day, try_enter)
from engine.basket import (_closed_cleanly, _guard_stops, _phase2_engine, _phase2_leg, _phase2_live_basket, _protect_unrecorded_entry, _retry_due_exits, _single_leg_live_entry, _single_leg_live_exit, write_simple_status)
from engine.loop import (DashHandler, MARKET_DATA_METHODS, _strategy_ex, _write_basket_live_status, run_loop, run_once, start_dashboard_server, strategy_exchange)

# ── the strategies, one file each (bots/): re-exported here — bot.<name> stays the one name the CLI, the API and the tests use ──
from bots.momentum_ls import MOM, RETAIL, momentum_public_name, retail_ratio, momentum_due, momentum_hold_over, momentum_next, momentum_mode, momentum_rank, run_once_momentum, write_momentum_status
from bots.ratio_trend import RATIO, ratio_public_name, ratio_mode, _daily_closed, _ratio_rank, ratio_members, ratio_signal, _ratio_close_pair, run_once_ratio, write_ratio_status
from bots.ratio_trend import ratio_targets, ratio_net_plan, run_once_ratio_net, write_ratio_net_status
from bots.listing_short import LISTING, listing_mode, _listing_close, run_once_listing, write_listing_status
from bots.vol_breakout import VB, breakout_mode, run_once_breakout
from bots.rsi2_pullback import RSI2, rsi2_public_name, rsi2_btc_ok, rsi2_mode, rsi_wilder, run_once_rsi2
from bots.trend_breakout import TB, tbreak_mode, run_once_tbreak
from bots.trend_daily import trend_mode, analyze_trend, try_enter_trend

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description="Crypto Bot 20 pairs")
    p.add_argument("--once", action="store_true", help="مرة واحدة")
    p.add_argument("--live", action="store_true", help="حقيقي")
    p.add_argument("--paper", action="store_true", help="وهمي")
    p.add_argument("--dashboard", action="store_true", help="شغل الداشبورد + البوت معًا")
    p.add_argument("--serve-only", action="store_true", help="داشبورد فقط بدون لوب")
    p.add_argument("--port", type=int, default=None, help="بورت الداشبورد")
    p.add_argument("--strategy", default=None, help="مثلا trend_daily — استراتيجية واحدة (أو أكتر بفاصلة)، أو نسخة باسمها من bots/variants.py (retail_fade, rsi2_btc, ratio_nobtc, ...)")
    p.add_argument("--leverage", type=int, default=None, choices=[1, 2, 3, 4, 5], help="الرافعة")
    p.add_argument("--universe", type=int, default=0, help="اشتغل على أعلى N عملة فوليوم بدل قائمة symbols")
    p.add_argument("--amount", type=float, default=None, help="هامش الصفقة USDT")
    p.add_argument("--poll", type=int, default=None, help="ثواني بين كل دورة")
    p.add_argument("--notify", action="store_true", help="رسايل تليجرام للدخول والخروج (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")
    p.add_argument("--public", default=None, help="مجلد يتكتب فيه status.json لصفحة البوت العامة (صفقات ونتايج بس)")
    p.add_argument("--expect-env", default=None, choices=["live", "demo", "testnet"],
                   help="refuse to start unless BINANCE_ENV is exactly this (the testnet service passes testnet)")
    p.add_argument("--ratio-exclude", default="", help="ratio trend: coins left out of the weekly pick, e.g. BTC,ETH (research §25)")
    p.add_argument("--ratio-net", action="store_true", help="ratio trend: one position per coin, the sum of its pairs — the only way a one-way account trades all of them (docs/ratio-trend-live-plan.md §1)")
    p.add_argument("--ratio-trail", type=float, default=0.0, help="ratio trend, paper pairs: out when the ratio is this far below its best since entry, e.g. 0.20 (research §35)")
    p.add_argument("--momentum-retail", action="store_true", help="momentum_ls ranked against the crowd's long/short ratio (paper only, research §29)")
    p.add_argument("--rsi2-btc-ma", type=int, default=0, help="RSI-2: new entries only while BTC closes above this daily average, e.g. 200 (research §28)")
    p.add_argument("--public-name", default=None, help="a second bot of the same strategy: its public file name (e.g. ratio_nobtc)")
    p.add_argument("--label", default=None, help="a second bot of the same strategy: its name on Telegram")
    p.add_argument("--state", default=None, help="ملف الحالة (لتشغيل أكتر من بوت في نفس المجلد) — اللوج بيبقى بنفس الاسم .log")
    # the momentum day experiment (research/README.md §23): Demo / paper only, the real bot keeps Monday and the full week
    p.add_argument("--mom-weekday", type=int, default=None, choices=range(7), help="مومنتم: يوم التبديل (0 = الاتنين) — Demo بس")
    p.add_argument("--mom-hold", type=int, default=None, choices=range(1, 8), help="مومنتم: يقفل السلة بعد كام يوم — Demo بس")
    p.add_argument("--show-config", action="store_true", help="print the settings these arguments resolve to (a variant included) and exit — places no order")
    args=p.parse_args()
    # a named variant (bots/variants.py): its base strategy and flags, then every check below as if they were typed
    from bots import variants as _variants
    try: VARIANT = _variants.resolve(args)
    except ValueError as e: p.error(str(e))
    if VARIANT and args.state is None: args.state = f"state_{VARIANT}.json"   # never its base strategy's book
    if args.strategy: CONFIG["enabled_strategies"]=[s.strip() for s in args.strategy.split(",") if s.strip()]
    retired = [s for s in (CONFIG.get("enabled_strategies") or []) if s in RETIRED_STRATEGIES]
    if args.strategy and retired: p.error(f"الاستراتيجية دي اتلغت: {', '.join(retired)}")
    if args.leverage: CONFIG["leverage"]=args.leverage
    elif trend_mode(): CONFIG["leverage"]=2
    if args.amount: CONFIG["trade_amount_usdt"]=args.amount
    if args.poll: CONFIG["poll_seconds"]=args.poll
    if args.universe:
        CONFIG["universe_size"]=args.universe
        CONFIG["max_open_positions"]=max(int(CONFIG["max_open_positions"]), args.universe)
    CONFIG["notify"]=args.notify
    if args.public: CONFIG["public_dir"]=args.public
    if args.ratio_exclude: RATIO["exclude"]=[c.strip().upper() for c in args.ratio_exclude.split(",") if c.strip()]
    if args.ratio_net:
        if args.strategy != "ratio_trend": p.error("--ratio-net: ratio_trend only")
        RATIO["net"]=True
    if args.ratio_trail:
        if args.strategy != "ratio_trend" or not args.paper or args.ratio_net or not 0 < args.ratio_trail < 1:
            p.error("--ratio-trail: paper ratio_trend pairs only (not --ratio-net), a fraction like 0.20")
        RATIO["trail"]=args.ratio_trail
    if args.momentum_retail:
        if args.strategy != "momentum_ls" or not args.paper: p.error("--momentum-retail: paper momentum_ls only")
        MOM.update(RETAIL)
    if args.rsi2_btc_ma:
        if not 20 <= args.rsi2_btc_ma <= 400: p.error("--rsi2-btc-ma: 20..400 days")
        RSI2["btc_ma"]=args.rsi2_btc_ma
    if args.public_name:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", args.public_name): p.error("--public-name: lowercase letters, digits, _")
        CONFIG["public_name"]=args.public_name
    if args.label: CONFIG["label"]=args.label[:40]
    if args.state:
        STATE_PATH=Path(__file__).parent / args.state
        LOG_PATH=STATE_PATH.with_suffix(".log")   # next to the state (the live bot keeps both in state/, its code folder is read-only)
    elif listing_mode():
        STATE_PATH=Path(__file__).parent / "state_listing.json"; LOG_PATH=Path(__file__).parent / "state_listing.log"
    elif momentum_mode():
        STATE_PATH=Path(__file__).parent / "state_momentum.json"; LOG_PATH=Path(__file__).parent / "state_momentum.log"
    elif ratio_mode():
        STATE_PATH=Path(__file__).parent / "state_ratio.json"; LOG_PATH=Path(__file__).parent / "state_ratio.log"
    if args.paper and args.live: p.error("--paper و --live مع بعض؟ اختار واحد")
    if args.mom_weekday is not None or args.mom_hold is not None:
        if not args.paper and binance_env() not in ("demo", "testnet"):
            p.error("--mom-weekday / --mom-hold تجربة على Demo بس — الحساب الحقيقي بيفضل على الاتنين والأسبوع كله")
        if args.mom_weekday is not None: MOM["weekday"] = args.mom_weekday
        if args.mom_hold is not None: MOM["hold_days"] = args.mom_hold
    if args.paper: CONFIG["paper_trading"]=True
    if args.expect_env and binance_env() != args.expect_env:
        p.error(f"BINANCE_ENV={binance_env()} لكن الخدمة متظبطة على {args.expect_env} — مش هيشتغل")
    if args.show_config:
        print(json.dumps({"variant": VARIANT, "strategies": CONFIG.get("enabled_strategies"), "paper": bool(CONFIG.get("paper_trading")),
                          "live": bool(args.live), "leverage": CONFIG.get("leverage"), "amount": CONFIG.get("trade_amount_usdt"),
                          "poll": CONFIG.get("poll_seconds"), "public_dir": CONFIG.get("public_dir"), "public_name": CONFIG.get("public_name"),
                          "label": CONFIG.get("label"), "state": STATE_PATH.name, "log": LOG_PATH.name,
                          "MOM": MOM, "RATIO": RATIO, "RSI2": RSI2}, ensure_ascii=False, sort_keys=True, default=str))
        sys.exit(0)
    if args.live:
        unsupported = [s for s in (CONFIG.get("enabled_strategies") or []) if s not in LIVE_READY_STRATEGIES]
        if unsupported:
            p.error(f"--live مش متاح لـ {', '.join(unsupported)} — الاستراتيجيات المتاحة: {', '.join(sorted(LIVE_READY_STRATEGIES))}")
        if binance_env() == "live" and os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
            p.error("فلوس حقيقية محتاجة ALLOW_LIVE_TRADING=true — أو BINANCE_ENV=demo للتجربة بفلوس وهمية على Binance")
        if binance_env() == "live" and not os.getenv("RAQM_RISK_DIR", "").strip():
            # without it the dashboard's kill switch, limits and revoke act on a ledger this process never reads
            p.error("فلوس حقيقية محتاجة RAQM_RISK_DIR — نفس فولدر دفتر المخاطرة اللي الـ API بيستخدمه")
        if binance_env() == "live":
            # the dashboard's limits are written by the API: real money needs root's ceilings over them (allow-live.env)
            try: riskmgr.hard_caps(required=True)
            except ValueError as e:
                p.error(f"فلوس حقيقية محتاجة سقف المخاطرة من root في allow-live.env ({', '.join(riskmgr.HARD_CAP_ENV.values())}): {e}")
        try:   # fail at start, not at the first trade: the ledger and the activation record must open read-write
            riskmgr.load_risk_state(RISK_PATH); live_activation.active_record(ACTIVATION_PATH)
        except Exception as e:
            p.error(f"دفتر المخاطرة مش متاح في {RISK_PATH.parent}: {e}")
        CONFIG["paper_trading"]=False
    if args.port: CONFIG["dashboard_port"]=args.port
    if args.serve_only:
        start_dashboard_server()
    elif args.dashboard:
        t=threading.Thread(target=start_dashboard_server, daemon=True); t.start()
        time.sleep(1)
        run_loop()
    elif args.once:
        run_once()
    else:
        run_loop()

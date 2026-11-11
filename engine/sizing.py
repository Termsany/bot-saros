"""the capital plan, strategy slots, position size and the daily loss check.
Moved from bot.py unchanged (2026-11-11): a bot-level name used in a function is read as bot.<name>, so the CLI's
settings, bot.py's state paths and the tests' patches on bot reach it. Import bot, not this module."""
import bot
import ccxt, pandas as pd, numpy as np, time, json, os, re, uuid, threading, http.server, socketserver, webbrowser
from datetime import datetime, timezone
from pathlib import Path
import strategies_advanced as adv
from backend.app.execution_safety import AmbiguousFill, authoritative_position_state, futures_net_pnl, linear_contracts_from_margin, normalize_filled_contracts
from backend.app import risk_manager as riskmgr
from backend.app.multi_leg_execution import MultiLegExecutionEngine
from backend.app import live_activation


def _capital_plan():
    """The owner's capital plan from the shared risk ledger (dashboard), capped by the last account equity; None = no
    plan set. A ledger that can't be read raises: the entry is refused rather than sized with the service's default."""
    state = riskmgr.load_risk_state(bot.RISK_PATH)
    # sized with the same ceilings the gate applies, so a capped risk per trade gives a smaller trade, not a refused one
    return riskmgr.capital_plan(riskmgr.capped_limits(state["limits"]), state.get("equity_last"))

def _strategies_sharing():
    """How many strategies share the account's open-trade count: the ones switched on for it (live: the activation
    record; Demo: the dashboard's yes/no, nothing chosen = all seven). None on paper. A choice that can't be read
    counts all seven: the smallest share, never the whole account."""
    if bot.CONFIG.get("paper_trading"):
        return None
    try:
        if bot.binance_env() == "demo":
            chosen = live_activation.demo_strategies(bot.ACTIVATION_PATH)
            on = bot.LIVE_READY_STRATEGIES if chosen is None else set(chosen) & bot.LIVE_READY_STRATEGIES
        elif not Path(bot.ACTIVATION_PATH).exists():   # no record yet (entries are refused anyway): read only, never create it
            on = set()
        else:
            on = set((live_activation.active_record(bot.ACTIVATION_PATH) or {}).get("strategies") or []) & bot.LIVE_READY_STRATEGIES
    except Exception:
        return len(bot.LIVE_READY_STRATEGIES)
    return max(1, len(on))

def _strategy_full(state, cap):
    """The strategy's own cap on open positions, as tested. On the owner's account with a capital plan set, also its
    even share of the account's count (risk_manager.strategy_slots): one strategy on gets the whole account (up to its
    own cap), several can't crowd each other out. The risk gate checks the same share for every strategy."""
    n = len(state["positions"])
    if n >= cap:
        return True
    if not bot.CONFIG.get("paper_trading"):
        try:
            slots = riskmgr.strategy_slots(bot._capital_plan(), bot._strategies_sharing())
        except Exception:
            return False   # the risk gate refuses when the ledger can't be read
        if slots is not None and n >= slots:
            return True
    return False

def _meets_min_order(ex, symbol, margin):
    """margin × leverage reaches the exchange's minimum order value for this coin (BTC $50, ETH $20 ... on Binance)."""
    try: min_cost = float(((ex.market(symbol).get("limits") or {}).get("cost") or {}).get("min") or 0)
    except Exception: return True
    return float(margin) * int(bot.CONFIG.get("leverage", 2)) >= min_cost * 1.02

def position_size(price, ex=None, stop_price=None):
    """Return quote margin; percent-risk mode targets configured worst-case stop loss. Live with a capital plan set on
    the dashboard: the plan's margin per trade, for every strategy (the gate caps how many trades are open)."""
    if not bot.CONFIG.get("paper_trading"):
        plan = bot._capital_plan()
        if plan: return float(plan["margin"])
    base=float(bot.CONFIG.get("trade_amount_usdt", 20))
    if not bot.CONFIG.get("use_percent_risk"):
        return base
    # % risk mode — نحسب من الرصيد
    try:
        if ex is None: return base
        bal=ex.fetch_balance()
        usdt=float(bal.get("USDT",{}).get("free", 0) or bal.get("free",{}).get("USDT",0) or 0)
        if usdt < 10: return base
        risk=float(bot.CONFIG.get("risk_pct",2))/100
        if stop_price is None or float(stop_price) <= 0 or float(price) <= 0:
            return base
        stop_pct=abs(float(price)-float(stop_price))/float(price)
        if stop_pct <= 0:
            return base
        lev=max(1, int(bot.CONFIG.get("leverage", 1)))
        return (usdt * risk) / (stop_pct * lev)
    except:
        return base

def daily_pnl_ok(state):
    """لو خسر أكثر من max_daily_loss_pct اليوم يوقف"""
    limit=float(bot.CONFIG.get("max_daily_loss_pct", 5))
    if limit <= 0: return True
    today=datetime.now(timezone.utc).date().isoformat()
    # نحسب PnL اليوم من history
    hist=state.get("history",[])
    today_pnl=sum(float(h.get("pnl",0)) for h in hist if str(h.get("time","")).startswith(today))
    # نحسب الرصيد المرجعي: لو paper نحسب على 1000$ افتراضي
    ref=1000.0
    # Check trades.log? use equity
    if today_pnl < -(ref * limit/100):
        return False
    return True

"""Arithmetic preflight for a live activation.

An activation record used to accept any allocation and any limits, including combinations whose own numbers make every
entry fail the risk gate: the record says "live", the bot is running, and it can never open a trade. The most common
case is the built-in capital plan (1 % margin, x2, 40 % stop = 80 % of the margin at risk) against the default
``risk_per_trade_pct`` of 0.25 %, or a seven-way split whose per-strategy share is smaller than one trade's risk.

This module only reads the limits and allocation; it never touches the exchange, a ledger, or an order. Activation
refuses when ``ok`` is false, so an impossible plan is visible at the moment it is chosen rather than as a silent
no-trade account.
"""
from __future__ import annotations

import math

from . import risk_manager


def _number(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def evaluate(*, strategies, allocation, limits, equity_usdt=None):
    """Return the activation preflight result.

    ``allocation`` is the already-normalised per-strategy share of the account's aggregate risk budget (the value the
    activation record stores). ``limits`` is the risk ledger's ``limits`` object. ``equity_usdt`` is optional: the
    capital plan falls back to the configured capital when the ledger has no equity yet.
    """
    names = list(dict.fromkeys(strategies or []))
    reasons, warnings, rows = [], [], {}
    if not names:
        reasons.append("no strategies selected")
    if not isinstance(allocation, dict):
        reasons.append("risk allocation is missing")
        allocation = {}
    if not isinstance(limits, dict):
        reasons.append("risk ledger limits are unreadable")
        limits = {}

    try:
        plan = risk_manager.capital_plan(limits, equity_usdt)
    except (TypeError, ValueError) as exc:
        plan = None
        reasons.append(f"capital plan is unreadable: {exc}")
    if plan is None:
        reasons.append("no capital plan is set (capital_usdt): the margin per trade is unknown, so the risk cannot be verified")
        per_trade = None
    else:
        per_trade = _number(plan.get("loss_per_trade_pct"))
        if per_trade is None:
            reasons.append("the capital plan has no per-trade risk figure")
        max_open = int(plan.get("max_open") or 0)
        if max_open < 1:
            reasons.append("the capital plan allows no open trade (max_open = 0): raise the capital or lower the margin")
        elif len(names) > max_open:
            warnings.append(f"the capital plan allows {max_open} open trade(s) for {len(names)} selected strategies: "
                            "they will take turns")

    per_trade_limit = _number(limits.get("risk_per_trade_pct",
                                         risk_manager.DEFAULT_LIMITS["risk_per_trade_pct"]))
    aggregate_limit = _number(limits.get("max_aggregate_risk_pct",
                                         risk_manager.DEFAULT_LIMITS["max_aggregate_risk_pct"]))
    correlated_limit = _number(limits.get("max_correlated_risk_pct",
                                          risk_manager.DEFAULT_LIMITS["max_correlated_risk_pct"]))
    for label, value in (("risk_per_trade_pct", per_trade_limit),
                         ("max_aggregate_risk_pct", aggregate_limit),
                         ("max_correlated_risk_pct", correlated_limit)):
        if value is None or value <= 0:
            reasons.append(f"{label} must be greater than 0")

    for strategy in names:
        share = _number(allocation.get(strategy))
        row = {"risk_allocation": share, "per_trade_risk_pct": per_trade,
               "strategy_cap_pct": None, "ok": True, "reasons": []}
        if share is None or not (0 < share <= 1.0):
            row["ok"] = False
            row["reasons"].append("risk allocation must be greater than 0 and at most 1")
        if per_trade is not None:
            if per_trade_limit is not None and per_trade_limit > 0 and per_trade > per_trade_limit + 1e-9:
                row["ok"] = False
                row["reasons"].append(
                    f"one trade risks {per_trade:.3f}% of equity, above risk_per_trade_pct "
                    f"{per_trade_limit:.3f}%: the gate would refuse every entry")
            if share is not None and aggregate_limit is not None:
                cap = aggregate_limit * share
                row["strategy_cap_pct"] = round(cap, 6)
                if per_trade > cap + 1e-9:
                    row["ok"] = False
                    row["reasons"].append(
                        f"one trade risks {per_trade:.3f}% of equity, above this strategy's allocation "
                        f"{share:.4g} of the aggregate budget ({cap:.3f}% of equity)")
            if correlated_limit is not None and correlated_limit > 0 and per_trade > correlated_limit + 1e-9:
                row["ok"] = False
                row["reasons"].append(
                    f"one trade risks {per_trade:.3f}% of equity, above max_correlated_risk_pct "
                    f"{correlated_limit:.3f}%: a single correlated entry would be refused")
        if not row["ok"]:
            reasons.append(f"{strategy}: " + "; ".join(row["reasons"]))
        rows[strategy] = row

    return {
        "ok": not reasons,
        "reasons": reasons,
        "warnings": warnings,
        "plan": plan,
        "limits_check": risk_manager.plan_vs_limits(limits, plan) if plan else None,
        "per_trade_risk_pct": per_trade,
        "strategies": rows,
    }

"""A user's monthly statement (owner, 2026-11-08): every trade their own bots closed in one month (UTC), per bot and in
total: how many, won / lost, the net result in dollars (after Binance's fees and funding, as the bot books it), the
funding where the bot knows it, the best and the worst trade. From each bot's closed.json (bot.py _write_closed: all
its closed real-orders trades, Demo or real money), read the way user_bots.status reads their status files.

Only the signed-in user's own folders; nothing here writes.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone

from app import user_bots

MONTH_RE = re.compile(r"^(20[2-9][0-9])-(0[1-9]|1[0-2])$")


def _when(s):
    try:
        t = datetime.fromisoformat(str(s))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def closed_by_strategy(uid, ipc=None):
    """{strategy: (env, rows)} from each of the user's bots' closed.json."""
    root = ipc or user_bots.IPC_ROOT
    out = {}
    for s in user_bots.STRATEGIES:
        doc = user_bots.read_json(user_bots.ipc_instance(uid, s, root) / "closed.json") or user_bots.read_json(root / uid / s / "closed.json")
        if isinstance(doc, dict) and isinstance(doc.get("closed"), list):
            out[s] = (doc.get("env") or "demo", [r for r in doc["closed"] if isinstance(r, dict)])
    return out


def months(closed):
    """The months that have a closed trade, newest first ("2026-11", ...)."""
    seen = {t.strftime("%Y-%m") for _, rows in closed.values() for r in rows if (t := _when(r.get("time")))}
    return sorted(seen, reverse=True)


def _summary(rows):
    pnls = [p for p in (_num(r.get("pnl")) for r in rows) if p is not None]
    funding = [f for f in (_num(r.get("funding_pnl")) for r in rows) if f is not None]
    return {"trades": len(rows), "wins": sum(1 for p in pnls if p > 0), "losses": sum(1 for p in pnls if p <= 0),
            "unknown": len(rows) - len(pnls), "net_usdt": round(sum(pnls), 4),
            "funding_usdt": round(sum(funding), 4) if funding else None,
            "best_usdt": round(max(pnls), 4) if pnls else None, "worst_usdt": round(min(pnls), 4) if pnls else None}


def build(closed, month, env=None):
    """The statement for `month` ("YYYY-MM"): per strategy and in total, and every trade (newest first)."""
    if not MONTH_RE.match(month or ""):
        raise ValueError("month must be YYYY-MM")
    per, trades = {}, []
    for s, (e, rows) in sorted(closed.items()):
        if env and e != env:
            continue
        mine = [r for r in rows if (t := _when(r.get("time"))) and t.strftime("%Y-%m") == month]
        if not mine:
            continue
        per[s] = {"env": e, **_summary(mine)}
        for r in mine:
            trades.append({"strategy": s, "env": e, **{k: r.get(k) for k in ("symbol", "side", "opened", "time", "entry", "exit",
                                                                              "qty", "pnl", "funding_pnl", "reason")}})
    trades.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
    return {"month": month, "env": env, "strategies": per, "total": _summary(trades), "trades": trades}

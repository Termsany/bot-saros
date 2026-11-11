"""the site's close requests, the IPC folder and the live status files.
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


MANUAL_CLOSE_MAX_AGE_S = 600   # a request the bot couldn't run within 10 minutes is dropped, never executed late

def _read_request(f):
    """A request file's JSON, or None. Opened without following a link and without blocking (a FIFO dropped in the
    shared folder made read_text wait forever and froze the live loop), and only if it is a small regular file."""
    import stat as _st
    try:
        fd = os.open(str(f), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not _st.S_ISREG(info.st_mode) or info.st_size > 65536: return None
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = None
            return json.loads(fh.read())
    except Exception:
        return None
    finally:
        if fd is not None: os.close(fd)

def process_manual_closes(state, ex, prices):
    """Close requests from the site's admin button: close the position now, record it, and don't buy the coin
    again until its trend turns off and back on. Only closes — a request can never open anything."""
    d = bot._ipc_dir()
    if not d: return
    cmd_dir, res_dir = d / "commands", d / "results"
    try: files = sorted(cmd_dir.glob("close-*.json"))
    except Exception: return
    try:   # results older than a day are of no use to anyone
        for old in res_dir.glob("*.json"):
            if time.time() - old.stat().st_mtime > 86400: old.unlink()
    except Exception: pass
    for f in files:
        if f.is_symlink() or not f.is_file():
            try: f.unlink()
            except OSError: pass
            continue
        req = bot._read_request(f) or {}
        rid, sym = str(req.get("id", "")), str(req.get("symbol", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", rid) or not re.fullmatch(r"[A-Z0-9]{1,20}/USDT(:USDT)?", sym):
            bot.log(f"⚠️ طلب قفل مرفوض (id أو عملة مش صحيحة): {f.name}")
            try: f.unlink()
            except OSError: pass
            continue
        out = {"id": rid, "symbol": sym, "done_at": datetime.now(timezone.utc).isoformat()}
        try:
            at = float(req.get("at_epoch") or 0); age = time.time() - at
            if at <= 0 or age < -60: age = bot.MANUAL_CLOSE_MAX_AGE_S + 1      # missing or in the future: treated as stale
            match = next((k for k in state["positions"] if k.split(":")[0] == sym.split(":")[0]), None)
            if not match and age <= bot.MANUAL_CLOSE_MAX_AGE_S and bot._ipc_shared_with_another_bot(d):
                continue   # another live bot shares this folder and may hold the coin: its request, not ours
            if age > bot.MANUAL_CLOSE_MAX_AGE_S:
                out.update(ok=False, msg="الطلب قديم — اتلغى من غير تنفيذ")
            elif not match:
                out.update(ok=False, msg="مفيش صفقة مفتوحة على العملة دي")
            else:
                pos = state["positions"][match]
                px = prices.get(match)
                if px is None:
                    try: px = float(ex.fetch_ticker(match)["last"])
                    except Exception: px = pos["entry"]
                r = bot.close_live_position(ex, match, pos, px)
                bot._require_verified_close(r)
                cs = bot._position_contract_size(pos)
                if cs is None:
                    raise RuntimeError("missing contract_size for live PnL")
                pnl = futures_net_pnl(pos["entry"], r["price"], r["qty"], cs, pos.get("side", "long"), fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
                state["history"].append({"symbol": match, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": r["price"], "qty": r["qty"], "pnl": pnl,
                    "pnl_pct": pnl / (pos["entry"] * r["qty"] * cs / max(1, int(pos.get("leverage", bot.CONFIG.get("leverage", 1))))) * 100, "reason": "قفل يدوي من الموقع", "time": datetime.now(timezone.utc).isoformat(),
                    "type": "live", "opened": pos.get("time"), "rank": pos.get("rank"), "by": req.get("by")})
                state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl); state["stats"]["wins" if pnl > 0 else "losses"] += 1
                state["positions"].pop(match, None); state["last_trade"][match] = datetime.now(timezone.utc).isoformat()
                state.get("recovery_required", {}).pop(match, None)
                bot.save_state(state)
                bot._release_position_risk(match, pos)
                out.update(ok=True, msg="اتقفلت", price=r["price"], qty=r["qty"], pnl=round(pnl, 4))
                bot.log(f"🖐️ قفل يدوي {match} @ {r['price']:.6g} PnL {pnl:+.2f} (طلب {req.get('by', '?')})")
        except Exception as e:
            out.update(ok=False, msg=f"القفل فشل: {e}")
            bot.log(f"⚠️ قفل يدوي {sym} فشل: {e}"); bot.notify(f"⚠️ القفل اليدوي لـ {sym} فشل: {e} — الوقف لسه على المنصة")
        try:
            res_dir.mkdir(exist_ok=True); bot._write_json_atomic(res_dir / f"{rid}.json", out)
        except Exception as e: bot.log(f"manual close result {rid}: {e}")
        try: f.unlink()
        except Exception: pass

PAIR_RE = r"[A-Z0-9]{1,20}/USDT:USDT\|[A-Z0-9]{1,20}/USDT:USDT"

def process_paper_closes(state, ex, key):
    """Admin close requests for a paper bot (site: live bots section): RAQM_PAPER_IPC/<key>/commands/close-*.json,
    written by the API after checking the position exists. Only closes, at the current price, recorded like any exit;
    requests older than 10 minutes are dropped. key = the bot's public file name (status, momentum, ratio, ...)."""
    d = os.getenv("RAQM_PAPER_IPC", "").strip()
    if not d or not bot.CONFIG.get("paper_trading"): return   # live: _paper_close would drop a real position unclosed
    cmd_dir, res_dir = Path(d) / key / "commands", Path(d) / key / "results"
    try: files = sorted(cmd_dir.glob("close-*.json"))
    except Exception: return
    try:
        for old in res_dir.glob("*.json"):
            if time.time() - old.stat().st_mtime > 86400: old.unlink()
    except Exception: pass
    for f in files:
        if f.is_symlink() or not f.is_file():
            try: f.unlink()
            except OSError: pass
            continue
        req = bot._read_request(f) or {}
        rid, sym = str(req.get("id", "")), str(req.get("symbol", ""))
        sym_ok = re.fullmatch(bot.PAIR_RE, sym) if key == "ratio" else re.fullmatch(r"[A-Z0-9]{1,20}/USDT(:USDT)?", sym)
        try: f.unlink()
        except OSError: pass
        if not re.fullmatch(r"[0-9a-f]{32}", rid) or not sym_ok:
            bot.log(f"⚠️ طلب قفل مرفوض ({f.name})"); continue
        out = {"id": rid, "symbol": sym, "done_at": datetime.now(timezone.utc).isoformat()}
        at = float(req.get("at_epoch") or 0); age = time.time() - at
        reason = "قفل يدوي (أدمن)"
        try:
            if at <= 0 or age < -60 or age > bot.MANUAL_CLOSE_MAX_AGE_S:
                out.update(ok=False, msg="الطلب قديم — اتلغى من غير تنفيذ")
            elif key == "ratio":
                if sym not in state.get("pairs", {}): out.update(ok=False, msg="الزوج ده مش مفتوح")
                else:
                    pnl = bot._ratio_close_pair(ex, state, sym, {}, reason, {}); bot.save_state(state)
                    out.update(ok=True, msg="اتقفل", pnl=round(pnl, 4))
            else:
                match = next((k for k in state["positions"] if k.split(":")[0] == sym.split(":")[0]), None)
                if not match: out.update(ok=False, msg="مفيش صفقة مفتوحة على العملة دي")
                else:
                    price = float(ex.fetch_ticker(match)["last"])
                    if key == "status":       # paper daily trend: same record as its own exit, then no re-buy until the trend resets
                        pos = state["positions"].pop(match); pnl = (price - pos["entry"]) * pos["qty"]
                        state["history"].append({"symbol": match, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": price, "qty": pos["qty"], "pnl": pnl,
                            "pnl_pct": pnl / (pos["entry"] * pos["qty"]) * 100, "reason": reason, "time": datetime.now(timezone.utc).isoformat(),
                            "type": "paper", "opened": pos.get("time"), "rank": pos.get("rank")})
                        st = state["stats"]; st["trades"] += 1; st["pnl"] += float(pnl); st["wins" if pnl > 0 else "losses"] += 1
                        state["last_trade"][match] = datetime.now(timezone.utc).isoformat()
                        state.setdefault("manual_hold", {})[match] = datetime.now(timezone.utc).isoformat()
                    elif key == "listing":
                        pnl = bot._listing_close(ex, state, match, price, reason)
                    else:
                        pnl = bot._paper_close(ex, state, match, price, reason)
                    bot.save_state(state)
                    out.update(ok=True, msg="اتقفلت", price=price, pnl=round(pnl, 4))
            if out.get("ok"):
                bot.log(f"🖐️ {key}: {reason} {sym} — {out.get('pnl'):+.4f}")
        except Exception as e:
            out.update(ok=False, msg=f"القفل فشل: {e}"); bot.log(f"⚠️ {key} قفل يدوي {sym}: {e}")
        try:
            res_dir.mkdir(exist_ok=True); bot._write_json_atomic(res_dir / f"{rid}.json", out)
        except Exception as e: bot.log(f"paper close result {rid}: {e}")

def _ipc_shared_with_another_bot(d):
    """True if live_status.json in the IPC folder was written lately by a live bot running another strategy."""
    try:
        cur = json.loads((d / "live_status.json").read_text(encoding="utf-8"))
        fresh = (datetime.now(timezone.utc) - datetime.fromisoformat(cur["updated"])).total_seconds() < 600
        return fresh and cur.get("strategy") not in (None, bot._current_strategy_name())
    except Exception:
        return False

def write_live_status(state, prices, analyses=None):
    """What the site's admin page shows for the real-orders bot (not public). One live bot per RAQM_IPC_DIR: a bot
    doesn't overwrite another strategy's fresh status."""
    d = bot._ipc_dir()
    if not d: return
    if bot._ipc_shared_with_another_bot(d):
        bot.log("⚠️ RAQM_IPC_DIR فيه بوت حقيقي تاني شغّال — حالة البوت ده مش هتتكتب (كل بوت محتاج فولدر لوحده)"); return
    pos = []
    for sym, p in state["positions"].items():
        px = prices.get(sym)
        exit_below = (((analyses or {}).get(sym) or {}).get("trend") or {}).get("exit_below")
        cs = bot._position_contract_size(p)
        funding = bot._funding_pnl(p)
        fee = bot._fee_rate(p)
        # fee and funding not verified yet (the usual case while a position is open): an estimate for the page only —
        # the entry's fee rate on both sides, no funding — marked as such; the recorded PnL still needs the evidence
        estimated = funding is None or fee is None
        if estimated:
            try: fee, funding = float(p.get("entry_fee_rate") or 0.0004), 0.0
            except (TypeError, ValueError): fee, funding = 0.0004, 0.0
        live_pnl = futures_net_pnl(p["entry"], px, p["qty"], cs, p.get("side", "long"), fee_rate=fee, funding_pnl=funding) if px and cs and funding is not None and fee is not None else None
        loss_at_sl = None
        if p.get("sl") and cs and funding is not None and fee is not None:
            loss_at_sl = futures_net_pnl(p["entry"], float(p["sl"]), p["qty"], cs, p.get("side", "long"), fee_rate=fee, funding_pnl=funding)
        pos.append({"symbol": sym.split(":")[0], "side": p.get("side", "long"), "pnl_estimated": estimated, "entry": p["entry"], "qty": p["qty"], "contract_size": cs, "sl": p.get("sl"), "price": px,
                    "exit_below": exit_below, "tp": p.get("tp"),
                    "loss_at_sl": round(loss_at_sl, 2) if loss_at_sl is not None else None,
                    "pnl": round(live_pnl, 4) if live_pnl is not None else None, "opened": p.get("time"),
                    "unprotected": bool(p.get("unprotected")), "sl_unverified": bool(p.get("sl_unverified"))})
    hist = [h for h in state.get("history", []) if h.get("type") == "live"][-30:][::-1]
    try:
        bot._write_json_atomic(d / "live_status.json", {"updated": datetime.now(timezone.utc).isoformat(), "env": bot.binance_env(),
            "strategy": bot._current_strategy_name(),
            "leverage": bot.CONFIG.get("leverage"), "margin": bot.CONFIG.get("trade_amount_usdt"), "positions": pos, "history": hist,
            "review": state.get("recovery_required") or {}, "entry_block": bot._ENTRY_BLOCK["reason"], "manual_hold": list(state.get("manual_hold", {})),
            "last_block": dict(bot._LAST_BLOCK) or None})
    except Exception as e: bot.log(f"live status: {e}")
    bot._write_closed(d, state)

_CLOSED_WRITTEN = {"n": None}   # how many closed trades closed.json holds: rewritten only when a trade closes

def _write_closed(d, state):
    """Every closed real-orders trade of this bot for the admin page's Demo-vs-baseline table (backend/app/demo_measure.py):
    live_status.json keeps only the last 30. Rewritten when the count changes, and on the bot's first cycle."""
    rows = [h for h in state.get("history", []) if h.get("type") == "live"]
    if bot._CLOSED_WRITTEN["n"] == len(rows): return
    try:
        bot._write_json_atomic(d / "closed.json", {"updated": datetime.now(timezone.utc).isoformat(), "env": bot.binance_env(),
            # entry/exit/qty/funding_pnl: the user's monthly statement (backend/app/user_statement.py, owner 2026-11-08)
            "closed": [{k: h.get(k) for k in ("symbol", "side", "opened", "time", "entry", "exit", "qty", "pnl", "pnl_pct",
                                              "funding_pnl", "reason", "by")} for h in rows]})
        bot._CLOSED_WRITTEN["n"] = len(rows)
    except Exception as e: bot.log(f"closed trades: {e}")

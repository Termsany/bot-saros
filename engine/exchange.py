"""the exchange: balance and transfers, keys, the ccxt client, the coin universe.
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


def _fetch_equity_usdt(ex):
    """Best-effort USDT account equity (free + used margin); None means unavailable —
    callers must fail closed on None, never substitute a guessed figure. A failed request is tried once more after 2
    seconds: Binance Demo drops one now and then, and each drop blocked that bot's entries for a whole cycle."""
    for attempt in (1, 2):
        try:
            bal = ex.fetch_balance(); break
        except Exception as e:
            if attempt == 2:
                bot.log(f"⚠️ رصيد الحساب مش متاح من Binance (مرتين): {type(e).__name__}: {e}"); return None
            time.sleep(2)
    try:
        usdt = bal.get("USDT") or {}
        total = usdt.get("total")
        if total is None:
            free = float(usdt.get("free") or (bal.get("free") or {}).get("USDT") or 0)
            used = float(usdt.get("used") or (bal.get("used") or {}).get("USDT") or 0)
            total = free + used
        total = float(total)
        return total if total > 0 else None
    except Exception:
        return None


_TRANSFERS = {"rows": None}   # the account's transfers, read by _equity_now just before the balance


def _transfers_recent(ex, days=3):
    """[(epoch ms, usdt)] of the futures wallet's transfers in and out (Binance income TRANSFER) of the last `days`,
    or None when they can't be read (the risk ledger then leaves its figures as they were). Read only."""
    if bot.CONFIG.get("paper_trading") or not hasattr(ex, "fapiPrivateGetIncome"):
        return None
    try:
        since = int((time.time() - days * 86400) * 1000)
        rows = ex.fapiPrivateGetIncome({"incomeType": "TRANSFER", "startTime": since, "limit": 1000}) or []
        return [(int(r["time"]), float(r["income"])) for r in rows if str(r.get("asset") or "USDT") == "USDT"]
    except Exception as e:
        bot.log(f"⚠️ التحويلات مش متاحة من Binance: {type(e).__name__}"); return None


def _equity_now(ex):
    """Equity and the instant it was observed, as one pair. The central risk gate refuses a figure with no
    timestamp (freshness is a real gate, not a formality), so every live entry/equity check must carry both.
    The transfers are read first (_TRANSFERS): a transfer already in the balance is then in the list too."""
    bot._TRANSFERS["rows"] = bot._transfers_recent(ex)
    return bot._fetch_equity_usdt(ex), datetime.now(timezone.utc).isoformat()

def _estimate_trade_risk_usdt(margin_usdt, leverage, entry_price, sl_price):
    """Worst-case loss to the stop for a new position, used by the pre-trade risk gate.
    Returns None (fail closed) if the stop price is unknown — an entry with no stop has
    unbounded risk and must never pass the gate."""
    try:
        if sl_price is None or entry_price is None or float(entry_price) <= 0:
            return None
        notional = float(margin_usdt) * max(1, int(leverage or 1))
        base_qty = notional / float(entry_price)
        return abs(float(entry_price) - float(sl_price)) * base_qty
    except (TypeError, ValueError):
        return None

KEYS_CREDENTIAL = "binance"   # a user's bot (docs/phase2-design.md): systemd LoadCredential=binance:/etc/raqm-users/<uid>/binance

def _binance_keys():
    """(api key, secret). A service given a credential directory (a user's bot) reads its keys from the credential
    only — BINANCE_API_KEY=... and BINANCE_SECRET=... lines — and never falls back to the environment, so it can't
    trade on keys it was not given. Without one (the owner's bots): the environment, as before."""
    cred = os.getenv("CREDENTIALS_DIRECTORY", "").strip()
    if not cred:
        return os.getenv("BINANCE_API_KEY", "").strip(), os.getenv("BINANCE_SECRET", "").strip()
    vals = {}
    try:
        for line in (Path(cred) / bot.KEYS_CREDENTIAL).read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() in ("BINANCE_API_KEY", "BINANCE_SECRET"): vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        return "", ""
    return vals.get("BINANCE_API_KEY", ""), vals.get("BINANCE_SECRET", "")

# An Ed25519 private key as one env line: base64 of its PKCS#8 DER (always this 16-character start, 64 characters).
# Binance's "self-generated" keys: the private key is made on the server and never shown to anyone, the site only
# gets the public key (2026-11-03: the Demo site stopped showing HMAC secrets).
ED25519_DER_B64_PREFIX = "MC4CAQAwBQYDK2Vw"

def _secret_for_ccxt(secret):
    """The secret as ccxt wants it: HMAC as is; an Ed25519 key as PEM without a trailing newline — ccxt signs with
    EdDSA only when the PEM is at most 120 characters (longer means RSA), and this one is exactly 120."""
    if secret.startswith(bot.ED25519_DER_B64_PREFIX) and len(secret) == 64:
        return f"-----BEGIN PRIVATE KEY-----\n{secret}\n-----END PRIVATE KEY-----"
    return secret

def get_exchange(auth=False):
    mtype = "future" if bot.CONFIG.get("market","future")=="future" else "spot"
    # ccxt: defaultType future = USDT-M perpetual
    kwargs = {"enableRateLimit": True, "options": {"defaultType": mtype}}
    if auth:
        ak, sc = bot._binance_keys()
        if not ak or not sc: return None, "ضع مفاتيح Binance في .env"
        kwargs["apiKey"]=ak; kwargs["secret"]=bot._secret_for_ccxt(sc)
        ex = ccxt.binanceusdm(kwargs) if mtype == "future" else ccxt.binance(kwargs)
        # BINANCE_ENV=demo: Binance Demo Trading (fake money, real exchange behaviour) — keys made in demo mode on binance.com
        env = bot.binance_env()
        if env == "demo": ex.enable_demo_trading(True)
        elif env == "testnet": ex.set_sandbox_mode(True)
        return ex, None
    return ccxt.bybit(kwargs), None   # public market data only (paper)

def binance_env():
    """live (real money) / demo (Binance Demo Trading) / testnet (old futures testnet)."""
    e = os.getenv("BINANCE_ENV", "live").strip().lower()
    return e if e in ("live", "demo", "testnet") else "live"

STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "USDE", "USD1", "PAXG", "XAUT"}  # stablecoins, gold
_universe = {"key": None, "symbols": []}

def volume_universe(ex, n):
    """Top n USDT perpetuals by average USDT volume over the last 30 closed daily candles, among coins with
    at least 150 daily candles (the trend needs 120 days) — research/universe_study.py. Refreshed once a day."""
    key = (datetime.now(timezone.utc).date().isoformat(), n)
    if bot._universe["key"] == key: return bot._universe["symbols"]
    ex.load_markets()
    tickers = ex.fetch_tickers(params={"category": "linear"} if ex.id == "bybit" else {})
    cands = []
    for sym, t in tickers.items():
        m = ex.markets.get(sym) or {}
        info = m.get("info") or {}
        crypto = info.get("symbolType", "") in ("", "innovation")   # Bybit also lists stocks, ETFs, commodities, forex as USDT perps
        if ex.id != "bybit":   # Binance: coins only (it also lists index / TradFi perpetuals); Bybit says contractType "LinearPerpetual"
            crypto = crypto and info.get("underlyingType", "COIN") == "COIN" and info.get("contractType", "PERPETUAL") == "PERPETUAL"
        if m.get("swap") and m.get("linear") and m.get("quote") == "USDT" and m.get("settle") == "USDT" and m.get("base") not in bot.STABLES                 and crypto and m.get("active", True) and not info.get("isPreListing"):
            cands.append((float(t.get("quoteVolume") or 0), sym))
    ranked = []
    for _, sym in sorted(cands, reverse=True)[:n * 3]:   # 24h volume narrows the list, the 30-day average ranks it
        try:
            k = ex.fetch_ohlcv(sym, "1d", limit=200)[:-1]
            if len(k) >= 150: ranked.append((sum(r[4] * r[5] for r in k[-30:]) / 30, sym))
        except Exception as e: bot.log(f"volume {sym}: {e}")
    syms = [s for _, s in sorted(ranked, reverse=True)[:n]]
    if syms: bot._universe.update(key=key, symbols=syms)
    bot.log(f"🔝 أعلى {n} عملة فوليوم (متوسط 30 يوم): {', '.join(s.split('/')[0] for s in syms)}")
    return syms or bot._universe["symbols"]

def cycle_symbols(ex, state):
    """(symbols to analyse, symbols allowed to open new trades). With universe_size, new trades only in the
    volume top list; open positions keep being managed after a coin drops out of it."""
    n = int(bot.CONFIG.get("universe_size") or 0)
    if not n: return list(bot.CONFIG["symbols"]), None
    allowed = set(bot.volume_universe(ex, n))
    return sorted(allowed | set(state["positions"])), allowed

def _resolve_live_symbol(ex, symbol):
    """CONFIG['symbols'] (trend_daily/wave_flats/ict's fixed list) is written in the bare 'BTC/USDT'
    form; Binance USDT-M futures' real ccxt market key is 'BTC/USDT:USDT'. ex.market()/create_order()
    require the exact key and raise 'does not have market symbol' on the bare form — only fetch_ohlcv
    tolerates it. The volume-ranked strategies (vol_breakout/rsi2_pullback/trend_breakout/momentum_ls/
    ratio_trend/listing_short) build their symbol lists FROM ex.fetch_tickers()/ex.markets already, so
    they're unaffected; this only matters for the fixed-list strategies' live path."""
    if symbol in ex.markets: return symbol
    quote = symbol.split("/")[-1] if "/" in symbol else ""
    resolved = f"{symbol}:{quote}"
    return resolved if resolved in ex.markets else symbol

def _resolve_live_symbols(ex, symbols, allowed):
    if not symbols: return symbols, allowed
    resolved = [bot._resolve_live_symbol(ex, s) for s in symbols]
    resolved_allowed = None if allowed is None else {bot._resolve_live_symbol(ex, s) for s in allowed}
    return resolved, resolved_allowed

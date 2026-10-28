"""Read-only connectivity probe for Binance Futures Demo Trading (the renamed Futures
Testnet). Loads credentials ONLY from backend/.env.testnet.local — never prints them,
never places an order. Prints only boolean/non-secret summaries.

Binance retired the old testnet.binancefuture.com API in 2025; the new REST base for
USDS-M futures demo trading is https://demo-fapi.binance.com. ccxt 4.5.90's built-in
sandbox map still points at the old (dead) domain, so we override the fapi* URLs here.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / "backend" / ".env.testnet.local"


def load_env_file(path: Path) -> dict:
    env = {}
    if not path.exists():
        print(f"ERROR: env file not found: {path}")
        sys.exit(1)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def main():
    env = load_env_file(ENV_PATH)
    required = ["BINANCE_ENV", "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        print(f"ERROR: missing keys in {ENV_PATH.name}: {missing}")
        sys.exit(1)
    if env["BINANCE_ENV"] != "testnet":
        print("ERROR: BINANCE_ENV must be 'testnet' for this probe")
        sys.exit(1)
    if env.get("ALLOW_LIVE_TRADING", "false").strip().lower() == "true":
        print("REFUSING: ALLOW_LIVE_TRADING must be false for a testnet probe")
        sys.exit(1)

    import ccxt

    ex = ccxt.binance({
        "apiKey": env["BINANCE_TESTNET_API_KEY"],
        "secret": env["BINANCE_TESTNET_SECRET"],
        # Restrict to USDS-M linear futures markets only. Without this, ccxt's
        # load_markets() also calls spot/margin endpoints (api.binance.com,
        # sapi/v1/margin/allPairs) on REAL mainnet regardless of defaultType —
        # a demo-only key correctly gets rejected there with "Invalid Api-Key ID".
        "options": {"defaultType": "future", "fetchMarkets": ["linear"]},
        "enableRateLimit": True,
    })
    # Binance's old testnet.binancefuture.com API domain is dead; the renamed
    # "Futures Demo Trading" REST base is demo-fapi.binance.com. Override ccxt's
    # sandbox map (unchanged as of 4.5.90) rather than waiting on an upstream fix.
    demo_base = "https://demo-fapi.binance.com"
    for key in ("fapiPublic", "fapiPublicV2", "fapiPublicV3", "fapiPrivate", "fapiPrivateV2", "fapiPrivateV3"):
        ex.urls["api"][key] = demo_base + ex.urls["test"][key].split("testnet.binancefuture.com", 1)[1]
    ex.urls["api"]["fapiPublic"] = f"{demo_base}/fapi/v1"
    ex.urls["api"]["fapiPublicV2"] = f"{demo_base}/fapi/v2"
    ex.urls["api"]["fapiPublicV3"] = f"{demo_base}/fapi/v3"
    ex.urls["api"]["fapiPrivate"] = f"{demo_base}/fapi/v1"
    ex.urls["api"]["fapiPrivateV2"] = f"{demo_base}/fapi/v2"
    ex.urls["api"]["fapiPrivateV3"] = f"{demo_base}/fapi/v3"
    # ccxt's load_markets() also calls fetchCurrencies(), which for binance hits the
    # SPOT sapi endpoint on real mainnet (api.binance.com) regardless of defaultType —
    # a real demo key doesn't exist there and that call fails with "Invalid Api-Key ID".
    # We only need futures markets here, so disable the spot-currencies side call.
    ex.has["fetchCurrencies"] = False

    print("Step 1: load_markets (public, no auth) ...")
    try:
        markets = ex.load_markets()
        print(f"  OK — {len(markets)} markets loaded from demo-fapi.binance.com")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    print("Step 2: fetch_balance (private, auth required) ...")
    try:
        bal = ex.fetch_balance()
        usdt = (bal.get("USDT") or {})
        total = usdt.get("total")
        print(f"  OK — auth works. USDT total balance present: {total is not None}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    print("Step 3: fetch_positions (private) ...")
    try:
        positions = ex.fetch_positions()
        open_count = sum(1 for p in positions if float(p.get("contracts") or 0) != 0)
        print(f"  OK — {len(positions)} position slots checked, {open_count} currently open")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\nALL READ-ONLY CHECKS PASSED. No order was placed by this script.")


if __name__ == "__main__":
    main()

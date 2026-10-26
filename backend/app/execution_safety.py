"""Small, side-effect-free helpers for futures execution safety."""


class AmbiguousFill(RuntimeError):
    """The exchange response cannot prove a positive executed quantity."""


def futures_net_pnl(entry_price, exit_price, contracts, contract_size, side, fee_rate=None, funding_pnl=None):
    """Net linear-futures PnL; verified fee and funding evidence are mandatory."""
    if fee_rate is None:
        raise ValueError("fee_rate evidence is required")
    if funding_pnl is None:
        raise ValueError("funding_pnl evidence is required")
    base_qty = float(contracts) * float(contract_size)
    direction = 1.0 if side == "long" else -1.0
    gross = (float(exit_price) - float(entry_price)) * base_qty * direction
    fees = (float(entry_price) * base_qty + float(exit_price) * base_qty) * float(fee_rate)
    return gross - fees + float(funding_pnl)




def linear_contracts_from_margin(margin_quote, leverage, price, contract_size, *, inverse=False):
    if inverse:
        raise ValueError("inverse contracts are unsupported; refusing ambiguous conversion")
    values = (margin_quote, leverage, price, contract_size)
    if any(float(v) <= 0 for v in values):
        raise ValueError("margin, leverage, price and contract_size must be positive")
    base_qty = float(margin_quote) * float(leverage) / float(price)
    return base_qty / float(contract_size)


def normalize_filled_contracts(order):
    """Return explicit filled contracts, never requested amount or order amount."""
    if not isinstance(order, dict):
        raise AmbiguousFill("malformed order response")
    filled = order.get("filled")
    try:
        value = float(filled)
    except (TypeError, ValueError):
        raise AmbiguousFill("filled quantity is missing")
    if value <= 0:
        raise AmbiguousFill("order did not prove a positive fill")
    return value


def _position_contracts(position):
    if not isinstance(position, dict):
        return None
    raw = position.get("contracts")
    if raw is None:
        raw = (position.get("info") or {}).get("size")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def authoritative_position_state(positions, symbol, *, position_idx=None, side=None):
    """Classify one exact position leg; incomplete snapshots are never flat."""
    if not isinstance(positions, list) or not positions:
        return "inconclusive"
    wanted = symbol.split(":")[0]
    matches = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        actual = position.get("symbol") or (position.get("info") or {}).get("symbol")
        if not isinstance(actual, str) or actual.split(":")[0] != wanted:
            continue
        info = position.get("info") or {}
        actual_idx = position.get("positionIdx", info.get("positionIdx"))
        actual_side = position.get("side", info.get("positionSide"))
        if position_idx is not None and str(actual_idx) != str(position_idx):
            continue
        if side is not None:
            normalized = str(actual_side).lower() if actual_side is not None else None
            wanted_side = str(side).lower()
            if normalized in ("long", "buy") and wanted_side == "long":
                pass
            elif normalized in ("short", "sell") and wanted_side == "short":
                pass
            elif actual_side is not None:
                continue
        matches.append(position)
    if len(matches) != 1:
        return "inconclusive"
    contracts = _position_contracts(matches[0])
    if contracts is None:
        return "inconclusive"
    return "flat" if contracts == 0 else "open"

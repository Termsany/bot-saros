import os, httpx
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

async def send_telegram(text: str, parse_mode: str = "Markdown", disable_preview: bool = True):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[telegram skip] {text[:140]}")
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    chat = os.getenv("TELEGRAM_CHAT_ID", CHAT_ID)
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                "chat_id": chat,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_preview,
            })
            if r.status_code != 200:
                print(f"telegram {r.status_code} {r.text[:300]}")
                return False
            return True
    except Exception as e:
        print(f"telegram err {e}")
        return False

async def test_telegram():
    return await send_telegram(
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "  \u2705 *Raqm · رقم \u2014 \u0645\u062a\u0635\u0644*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\u062a\u0644\u064a\u062c\u0631\u0627\u0645 \u0645\u0631\u0628\u0648\u0637 \u0628\u0646\u062c\u0627\u062d\\.\n"
        "\u0643\u0644 \u0635\u0641\u0642\u0629 \u0647\u062a\u0648\u0635\u0644\u0643 \u0641\u0648\u0631\u0627\u064b \u0647\u0646\u0627\\.\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
    )

def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def format_entry(symbol, side, price, sl, tp, leverage, score,
                 amount_usdt: float = 20, timeframe: str = "4h", strategy: str = "ICT"):
    is_long = side == "long"
    emoji = "\U0001f7e2" if is_long else "\U0001f534"
    direction = "LONG" if is_long else "SHORT"
    risk = abs(price - sl)
    reward = abs(tp - price) if tp else 0   # trend positions have no fixed target
    rr = reward / risk if risk else 0
    sl_tp_line = (f"\U0001f6e1\ufe0f *\u0648\u0642\u0641:* `{sl:,.2f}`  |  \U0001f3af *\u0647\u062f\u0641:* `{tp:,.2f}`  |  \u2696\ufe0f R:R `1:{rr:.1f}`\n" if tp else
                  f"\U0001f6e1\ufe0f *\u0648\u0642\u0641:* `{sl:,.2f}`  |  \U0001f3af \u062e\u0631\u0648\u062c \u0644\u0645\u0627 \u0627\u0644\u062a\u0631\u0646\u062f \u064a\u0642\u0641\n")
    return (
        f"{emoji} *{direction}  {symbol}*  `x{leverage}`\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4ca *\u0627\u0633\u062a\u0631\u0627\u062a\u064a\u062c\u064a\u0629:* `{strategy}`  |  \u23f1 `{timeframe}`  |  \U0001f9e0 \u0633\u0643\u0648\u0631 `{score:+.2f}`\n"
        f"\U0001f4b0 *\u062f\u062e\u0648\u0644:* `{price:,.2f}`  |  \U0001f4b5 \u0647\u0627\u0645\u0634 `${amount_usdt:.0f}`\n"
        + sl_tp_line +
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"_Raqm · رقم \u2014 {_now_utc()} _"
    )

def format_exit(symbol, side, entry, exit_price, qty, pnl, pnl_pct, reason,
                leverage: int = 5):
    is_win = pnl >= 0
    emoji = "\u2705" if is_win else "\u274c"
    result = "\u0631\u0628\u062d" if is_win else "\u062e\u0633\u0627\u0631\u0629"
    direction = "LONG" if side == "long" else "SHORT"
    reason_map = {"TP": "\U0001f3af \u0647\u062f\u0641", "SL": "\U0001f6e1\ufe0f \u0648\u0642\u0641",
                  "TP \u0647\u062f\u0641": "\U0001f3af \u0647\u062f\u0641",
                  "SL \u0648\u0642\u0641": "\U0001f6e1\ufe0f \u0648\u0642\u0641",
                  "\u0627\u0634\u0627\u0631\u0629 \u0639\u0643\u0633\u064a\u0629": "\U0001f504 \u0625\u0634\u0627\u0631\u0629 \u0639\u0643\u0633\u064a\u0629",
                  "\u0627\u0634\u0627\u0631\u0629 \u0639\u0643\u0633\u064a\u0629 \u0642\u0648\u064a\u0629": "\U0001f504 \u0625\u0634\u0627\u0631\u0629 \u0639\u0643\u0633\u064a\u0629 \u0642\u0648\u064a\u0629"}
    reason_label = reason_map.get(reason, reason)
    return (
        f"{emoji} *{result} \u2014 {direction} {symbol}*  `x{leverage}`\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4e5 \u062f\u062e\u0648\u0644 `{entry:,.2f}`  \u2192  \U0001f4e4 \u062e\u0631\u0648\u062c `{exit_price:,.2f}`\n"
        f"\U0001f4e6 \u0643\u0645\u064a\u0629 `{qty:.6f}`  |  \U0001f4b9 `{pnl:+.2f} USDT  ({pnl_pct:+.2f}%)`\n"
        f"\U0001f4cb \u0627\u0644\u0633\u0628\u0628: {reason_label}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"_Raqm · رقم \u2014 {_now_utc()} _"
    )

def format_optimizer_report(symbol, timeframe, top3, best_sl, best_tp,
                            pnl: float = 0, win_rate: float = 0):
    medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
    lines = "  ".join(f"{medals[i]} `{name}`" for i, name in enumerate(top3[:3]))
    pnl_str = f" | \U0001f4b9 `{pnl:+.2f} USDT` WR `{win_rate:.0f}%`" if pnl else ""
    return (
        f"\U0001f916 *Auto-Optimizer \u2014 {symbol}  {timeframe}*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f3c6 \u0627\u0644\u0623\u0628\u0637\u0627\u0644:\n"
        f"{lines}{pnl_str}\n"
        f"\u2699\ufe0f \u0627\u0644\u0623\u0645\u062b\u0644: SL `{best_sl*100:.1f}%`  TP `{best_tp*100:.1f}%`\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"_Raqm · رقم \u2014 {_now_utc()} _"
    )

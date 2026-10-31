"""Telegram card for a closed trade (owner, 2026-10-31): one image per trade — win, loss, stop or target — in the
site's colours (tailwind.config.js, Figma "Raqm / Color"), with the Arabic details in the photo's caption.

The image is English and numbers only: Pillow without libraqm can't join Arabic letters, Telegram's caption can.
Fonts ship in assets/fonts (DejaVu, free licence) so the card looks the same on every server. Nothing here may
raise into the trading cycle: bot.py renders and sends from its Telegram thread and falls back to the caption text.
"""
import io, json, math, uuid, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
W, H = 1200, 675

C = {"void": "#07080D", "surface": "#0F1118", "surface2": "#161A25", "line": "#232838", "ink": "#F2F3F7",
     "muted": "#8B91A7", "faint": "#5D6378", "corona": "#F5B841", "umbra": "#7B61FF", "profit": "#22D3A0",
     "loss": "#FF5470", "signal": "#4CC9F0"}

STRATEGIES = {  # id: (card, caption)
    "trend_daily": ("Daily Trend", "الترند اليومي"), "vol_breakout": ("Volatility Breakout", "بريك أوت التذبذب"),
    "rsi2_pullback": ("RSI-2 Pullback", "RSI-2"), "trend_breakout": ("Trend Breakout", "اختراق الترند"),
    "listing_short": ("New Listing Short", "شورت العملات الجديدة"), "momentum_ls": ("Momentum L/S", "مومنتم لونج/شورت"),
    "ratio_trend": ("Ratio Trend", "ترند النسبة"),
}

# outcome: (headline, colour, caption word, emoji)
OUTCOMES = {"target": ("TARGET HIT", "corona", "هدف", "🎯"), "profit": ("PROFIT", "profit", "ربح", "✅"),
            "stop": ("STOP LOSS", "loss", "وقف خسارة", "🛑"), "loss": ("LOSS", "loss", "خسارة", "🔻")}
EXITS = {"target": "Take profit", "stop": "Stop", "manual": "Manual", "rebalance": "Weekly rebalance",
         "emergency": "Emergency", "rule": "Strategy exit"}


def exit_kind(reason):
    """The close reason the bot wrote (Arabic, free text) as one of EXITS."""
    r = str(reason or "")
    if "هدف" in r or "TP" in r.split(): return "target"
    if "يدوي" in r: return "manual"
    if "تبديل" in r: return "rebalance"
    if "emergency" in r.lower(): return "emergency"
    if r.startswith("وقف") or "SL" in r.split(): return "stop"     # "الترند وقف" (trend turned off) is a rule exit
    return "rule"


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def build(h, *, strategy, env, leverage):
    """The card's facts from one state["history"] row. env: paper / demo / live."""
    pnl = _num(h.get("pnl")) or 0.0
    entry, exit_, qty = _num(h.get("entry")), _num(h.get("exit")), _num(h.get("qty"))
    lev = max(1, int(_num(h.get("leverage")) or leverage or 1))
    margin = entry * qty / lev if entry and qty else None
    pct = pnl / margin * 100 if margin else _num(h.get("pnl_pct"))
    kind = exit_kind(h.get("reason"))
    outcome = "target" if kind == "target" else "profit" if pnl > 0 else "stop" if kind == "stop" else "loss"
    pair = h.get("long") and h.get("short")
    if pair:
        symbol, side = f"{_base(h['long'])} / {_base(h['short'])}", "pair"
    else:
        symbol, side = _base(h.get("symbol")), str(h.get("side") or "long")
    opened, closed = _ts(h.get("opened")), _ts(h.get("time")) or datetime.now(timezone.utc)
    return {"symbol": symbol, "side": side, "entry": entry if not pair else None, "exit": exit_ if not pair else None,
            "pnl": pnl, "pct": pct, "lev": lev, "outcome": outcome, "kind": kind, "reason": str(h.get("reason") or ""),
            "funding": _num(h.get("funding")), "strategy": strategy, "env": env, "opened": opened, "closed": closed}


def _base(sym):
    return str(sym or "?").split(":")[0].replace("/USDT", "")


def _ts(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def price(x):
    if x is None: return "—"
    a = abs(x)
    if a >= 1000: return f"{x:,.2f}"
    if a >= 1: return f"{x:.4f}".rstrip("0").rstrip(".")
    if a == 0: return "0"
    return f"{x:.{min(10, 5 - int(math.floor(math.log10(a))))}f}".rstrip("0")


def money(v):
    return f"{'+' if v >= 0 else '−'}${abs(v):,.2f}"


def held(a, b):
    if not a or not b: return "—"
    m = max(0, int((b - a).total_seconds() // 60))
    d, h, mm = m // 1440, m % 1440 // 60, m % 60
    return f"{d}d {h}h" if d else f"{h}h {mm}m" if h else f"{mm}m"


# ── image ──

def _font(name, size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def _rgb(hexs, a=255):
    return tuple(int(hexs[i:i + 2], 16) for i in (1, 3, 5)) + (a,)


def _mix(top, under, t):
    """top over under at opacity t, as an opaque colour (ImageDraw writes alpha instead of blending it)."""
    a, b = _rgb(top), _rgb(under)
    return tuple(round(a[i] * t + b[i] * (1 - t)) for i in range(3)) + (255,)


def _fit(d, text, name, size, width):
    f = _font(name, size)
    while size > 14 and d.textlength(text, font=f) > width:
        size -= 1; f = _font(name, size)
    return f


def _pill(d, xy, text, font, fg, bg=None, outline=None, pad=(18, 9), anchor_right=False):
    x, y = xy
    w = d.textlength(text, font=font) + pad[0] * 2
    hgt = font.size + pad[1] * 2
    if anchor_right: x -= w
    d.rounded_rectangle((x, y, x + w, y + hgt), radius=hgt / 2, fill=bg, outline=outline, width=2)
    d.text((x + pad[0], y + hgt / 2), text, font=font, fill=fg, anchor="lm")
    return x, w


def render(card):
    """PNG bytes of the card."""
    from PIL import Image, ImageDraw, ImageFilter
    accent = C[OUTCOMES[card["outcome"]][1]]
    img = Image.new("RGBA", (W, H), _rgb(C["void"]))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 520, -320, W + 220, 300), fill=_rgb(accent, 70))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(120)))
    m = 36
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(body).rounded_rectangle((m, m, W - m, H - m), radius=28, fill=_rgb(C["surface"], 215), outline=_rgb(C["line"]), width=2)
    img = Image.alpha_composite(img, body)
    d = ImageDraw.Draw(img)

    sans, bold, mono = (lambda s: _font("DejaVuSans.ttf", s)), (lambda s: _font("DejaVuSans-Bold.ttf", s)), (lambda s: _font("DejaVuSansMono-Bold.ttf", s))
    d.rounded_rectangle((m + 14, m + 44, m + 20, H - m - 44), radius=3, fill=_rgb(accent))

    x0, y = 84, 78
    d.text((x0, y), "RAQM", font=bold(26), fill=_rgb(C["corona"]), anchor="lm")
    d.text((x0 + d.textlength("RAQM", font=bold(26)) + 16, y), STRATEGIES.get(card["strategy"], (card["strategy"],))[0].upper(),
           font=bold(20), fill=_rgb(C["muted"]), anchor="lm")
    env = card["env"]
    env_style = {"live": (C["void"], C["corona"], None), "demo": (C["signal"], None, C["signal"])}.get(env, (C["muted"], None, C["faint"]))
    _pill(d, (W - 84, y - 20), env.upper() if env != "live" else "LIVE · REAL MONEY", bold(18), _rgb(env_style[0]),
          _rgb(env_style[1]) if env_style[1] else None, _rgb(env_style[2]) if env_style[2] else None, anchor_right=True)

    y = 150
    d.text((x0, y), card["symbol"], font=bold(64 if len(card["symbol"]) < 14 else 46), fill=_rgb(C["ink"]), anchor="lt")
    sx = x0 + d.textlength(card["symbol"], font=bold(64 if len(card["symbol"]) < 14 else 46)) + 22
    side = card["side"]
    side_c = {"long": C["profit"], "short": C["loss"]}.get(side, C["umbra"])
    _pill(d, (sx, y + 12), f"{side.upper()} x{card['lev']}", bold(20), _rgb(side_c), _mix(side_c, C["surface"], 0.16), _mix(side_c, C["surface"], 0.55))
    head = OUTCOMES[card["outcome"]][0]
    _pill(d, (W - 84, y + 8), head, bold(24), _rgb(C["void"]), _rgb(accent), None, pad=(22, 12), anchor_right=True)

    y = 262
    d.text((x0 - 4, y), money(card["pnl"]), font=mono(118), fill=_rgb(accent), anchor="lt")
    pct = card["pct"]
    if pct is not None:
        d.text((x0, y + 148), f"{'+' if pct >= 0 else '−'}{abs(pct):.1f}% on margin", font=bold(30), fill=_rgb(C["ink"]), anchor="lt")

    y = 488
    d.line((x0, y, W - 84, y), fill=_rgb(C["line"]), width=2)
    if side == "pair":
        legs = card["symbol"].split(" / ")
        first = [("LONG LEG", legs[0], "DejaVuSansMono-Bold.ttf"), ("SHORT LEG", legs[-1], "DejaVuSansMono-Bold.ttf")]
    else:
        first = [("ENTRY", price(card["entry"]), "DejaVuSansMono-Bold.ttf"), ("EXIT", price(card["exit"]), "DejaVuSansMono-Bold.ttf")]
    cols = first + [("HELD", held(card["opened"], card["closed"]), "DejaVuSansMono-Bold.ttf"), ("EXIT TYPE", EXITS[card["kind"]], "DejaVuSans-Bold.ttf")]
    cw = (W - 84 - x0) / len(cols)
    for i, (k, v, face) in enumerate(cols):
        cx = x0 + i * cw
        d.text((cx, y + 26), k, font=bold(17), fill=_rgb(C["faint"]), anchor="lt")
        d.text((cx, y + 54), v, font=_fit(d, v, face, 30 if i < 3 else 26, cw - 14), fill=_rgb(C["ink"]), anchor="lt")

    foot = card["closed"].strftime("%d %b %Y · %H:%M UTC")
    d.text((x0, H - 62), foot, font=sans(18), fill=_rgb(C["faint"]), anchor="lm")
    if env != "live":
        d.text((W - 84, H - 62), "No real money", font=sans(18), fill=_rgb(C["faint"]), anchor="rm")
    out = io.BytesIO(); img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


def caption(card):
    """Arabic text under the photo — also the fallback message when the image can't be made or sent."""
    head, _, word, emoji = OUTCOMES[card["outcome"]]
    env = {"live": "حقيقي", "demo": "Demo"}.get(card["env"], "Paper")
    side = {"long": "لونج", "short": "شورت"}.get(card["side"], "زوج")
    lines = [f"{emoji} {word} · {STRATEGIES.get(card['strategy'], (None, card['strategy']))[1]} · {env}",
             f"{card['symbol']} {side} x{card['lev']}: {money(card['pnl'])}" + (f" ({card['pct']:+.1f}% من الهامش)" if card["pct"] is not None else "")]
    if card["entry"] is not None:
        lines.append(f"دخول {price(card['entry'])} ← خروج {price(card['exit'])} · مدة {held(card['opened'], card['closed'])}")
    if card["funding"]:
        lines.append(f"funding {card['funding']:+.2f}$")
    if card["reason"]:
        lines.append(f"السبب: {card['reason']}")
    return "\n".join(lines)[:1000]


def send_photo(token, chat, png, text, timeout=20):
    """Telegram sendPhoto (multipart). Raises on failure; a 429 waits its retry_after once and tries again."""
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", str(chat)), ("caption", text)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="trade.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
                 + png + f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = lambda: urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req(), timeout=timeout).read()
    except urllib.error.HTTPError as e:
        if e.code != 429: raise
        import time
        try: wait = int(json.loads(e.read()).get("parameters", {}).get("retry_after", 5))
        except Exception: wait = 5
        time.sleep(min(wait, 60) + 1)
        urllib.request.urlopen(req(), timeout=timeout).read()

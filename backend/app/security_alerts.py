"""A Telegram message to the owner for every sensitive change (security plan, item 4 — owner, 2026-11-07): what the
admin did (real money, limits, accounts, kill switch, users' access) and what a user did about their own real money.
Someone using a stolen session shows up on the owner's phone at once, not later in the audit log.

Never raises, never waits: the message goes out on the running event loop in the background (none running — a
script or a test — and nothing is sent). No key, secret or token is ever put in a message: only the action, who did
it, the result and the short details the audit log keeps.
"""
from __future__ import annotations
import asyncio, json

# admin_control.audit actions that alert (prefix match for the ones with a suffix)
ADMIN_ACTIONS = {
    "users_live_on": "🔴 فتح الفلوس الحقيقية للمستخدمين", "users_live_off": "قفل الفلوس الحقيقية للمستخدمين",
    "live_strategies": "غيّر بوتات الفلوس الحقيقية", "capital_plan": "غيّر خطة رأس المال", "risk_limits": "غيّر حدود المخاطرة",
    "kill_switch_": "Kill switch", "entry_pause": "وقّف الدخول", "entry_resume": "رجّع الدخول",
    "demo_bots_approve": "وافق على مستخدم", "demo_bots_remove": "شال موافقة مستخدم",
    "user_ban": "حظر مستخدم", "user_unban": "فك حظر مستخدم", "user_settings_update": "غيّر إعدادات مستخدم",
    "invite_create": "عمل دعوة", "gift_end": "أنهى هدية", "plan_prices": "غيّر أسعار الباقات",
}

_TASKS: set = set()   # strong references until each send finishes


def label(action: str) -> str | None:
    if action in ADMIN_ACTIONS:
        return ADMIN_ACTIONS[action]
    for k, v in ADMIN_ACTIONS.items():
        if k.endswith("_") and action.startswith(k):
            return f"{v} {action[len(k):]}"
    return None


def _send(text: str) -> bool:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    coro = None
    try:
        from app.telegram_bot import send_telegram
        coro = send_telegram(text[:900])
        task = loop.create_task(coro)
        _TASKS.add(task); task.add_done_callback(_TASKS.discard)
        return True
    except Exception as e:                                   # an alert must never break the action itself
        if coro is not None and hasattr(coro, "close"): coro.close()
        print(f"security alert not sent: {type(e).__name__}")
        return False


def _details(details) -> str:
    if not details:
        return ""
    try:
        s = json.dumps(details, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        s = str(details)
    return "\n" + (s if len(s) <= 300 else s[:297] + "…")


def admin_action(actor: str, action: str, result: str, details=None) -> bool:
    name = label(action)
    if not name:
        return False
    return _send(f"🔐 أدمن · {name}\n{actor} · {result}{_details(details)}")


def user_real_money(user: dict, what: str, details=None) -> bool:
    """A user's own real-money change: consent, a real-money bot on/off or its numbers, a key replaced."""
    who = str(user.get("email") or str(user.get("id") or "")[:8])
    return _send(f"💰 مستخدم · {what}\n{who}{_details(details)}")

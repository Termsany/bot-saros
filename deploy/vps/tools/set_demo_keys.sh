#!/bin/bash
# Put a new Binance DEMO key into /opt/raqm-live/.env.live, check it against Binance Demo (balance only) BEFORE writing,
# write both lines (other lines kept), restart the 6 Demo bots by name. Never touches .env.real or the real-money bot.
#   sudo bash /usr/local/lib/raqm/set_demo_keys.sh            # HMAC: asks for the key and the secret (not shown)
#   sudo bash /usr/local/lib/raqm/set_demo_keys.sh --ed25519  # makes an Ed25519 key here, shows only its public half,
#                                                             # asks for the API Key Binance gives for it
set -euo pipefail
F=/opt/raqm-live/.env.live
DEMO_BOTS="trend_daily vol_breakout rsi2_pullback trend_breakout listing_short ratio_trend"
[ "$(id -u)" = 0 ] || { echo "شغّله بـ sudo"; exit 1; }

if [ "${1:-}" = "--ed25519" ]; then
    W=$(mktemp -d); chmod 700 "$W"; trap 'rm -rf "$W"' EXIT
    openssl genpkey -algorithm ed25519 -out "$W/k.pem" 2>/dev/null
    S=$(openssl pkey -in "$W/k.pem" -outform DER | base64 -w0)
    echo
    echo "انسخ المفتاح العام ده كله (من BEGIN لحد END) والصقه في Binance Demo → API Management → Self-generated → Ed25519:"
    echo
    openssl pkey -in "$W/k.pem" -pubout
    echo
    echo "(المفتاح السري اتعمل هنا ومش هيظهر لحد — Binance مش محتاجه)"
    read -rsp "بعد ما Binance يعمل المفتاح، الصق الـ API Key اللي ظهر: " K; echo
    [[ "$S" =~ ^MC4CAQAwBQYDK2Vw[A-Za-z0-9+/]{48}$ ]] || { echo "❌ المفتاح اللي اتعمل هنا شكله غلط — ماتغيّرش حاجة"; exit 1; }
else
    read -rsp "Demo API Key: " K; echo
    read -rsp "Demo Secret Key: " S; echo
    S=$(printf %s "$S" | tr -d '[:space:]"'"'")
    [[ "$S" =~ ^[A-Za-z0-9]{64}$ ]] || { echo "❌ الـ Secret لازم 64 حرف/رقم — اتنسخ غلط (أو المفتاح مش HMAC: جرّب --ed25519)"; exit 1; }
fi
K=$(printf %s "$K" | tr -d '[:space:]"'"'")
[[ "$K" =~ ^[A-Za-z0-9]{64}$ ]] || { echo "❌ الـ API Key لازم 64 حرف/رقم — اتنسخ غلط"; exit 1; }
[ "$K" != "$S" ] || { echo "❌ الـ Key والـ Secret نفس الحاجة"; exit 1; }

echo "بيجرّب المفتاح على Binance Demo…"
cd /tmp
if ! sudo -u raqmlive env -i PATH=/usr/bin:/bin HOME=/tmp BINANCE_API_KEY="$K" BINANCE_SECRET="$S" BINANCE_ENV=demo \
     RAQM_RISK_DIR=/opt/raqm-risk-demo RAQM_IPC_DIR=/tmp /opt/raqm-live/venv/bin/python -I -c '
import sys; sys.path.insert(0, "/opt/raqm-live"); sys.argv = ["bot.py"]
import bot
ex, err = bot.get_exchange(auth=True)
if err: sys.exit(err)
try: b = ex.fetch_balance()
except Exception as e: sys.exit(f"❌ Binance رفض المفتاح: {str(e)[:160]}")
usdt = float(b["total"].get("USDT") or 0)
print(f"✅ المفتاح شغال — رصيد الـ Demo {usdt:.2f} USDT")
'; then echo "ماتغيّرش حاجة في $F"; exit 1; fi

T=$(mktemp "$F.XXXX")
grep -vE '^BINANCE_(API_KEY|SECRET)=' "$F" > "$T" || true
printf 'BINANCE_API_KEY=%s\nBINANCE_SECRET=%s\n' "$K" "$S" >> "$T"
chown raqmlive:raqmlive "$T"; chmod 600 "$T"; mv "$T" "$F"
unset K S
echo "اتحفظ في $F — restart لبوتات الـ Demo بالاسم:"
for s in $DEMO_BOTS; do systemctl restart "raqm-demo@$s" && echo "  raqm-demo@$s ✓"; done
echo "البوت الحقيقي: $(systemctl is-active raqm-live@momentum_ls) (ماتلمسش)"

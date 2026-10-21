# Paper bot on a VPS (bot.da3m.io)

The daily trend bot runs on its own server (Render's free plan sleeps and loses its files), in paper mode:
`bot.py --paper --strategy trend_daily --leverage 2 --universe 10` — the top 10 crypto USDT perpetuals on Bybit by
30-day average USDT volume (research/universe_study.py), long only, no exchange keys on the server.

| what | where |
|---|---|
| code + venv + state.json + trades.log | `/opt/raqm-bot` (user `raqm`) |
| Telegram token / chat id | `/opt/raqm-bot/.env` (mode 600, never committed) |
| service | `raqm-bot.service` → `/etc/systemd/system/` |
| public page | `page/index.html` + `status.json` (written by the bot) → `/var/www/bot.da3m.io` |
| nginx site | `nginx-bot.da3m.io.conf` → `/etc/nginx/sites-available/`, HTTPS by certbot |

Update the bot after a change:

```bash
scp bot.py strategies_*.py root@SERVER:/opt/raqm-bot/ && ssh root@SERVER 'chown raqm:raqm /opt/raqm-bot/*.py && systemctl restart raqm-bot'
```

Follow it: `journalctl -u raqm-bot -f`. Restarting keeps open trades (state.json) and never enters the same
signal twice.

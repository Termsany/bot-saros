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

## API (api.da3m.io) — replaces Render

FastAPI backend in `/opt/raqm-api` (user `raqmapi`): a git checkout of this repo + venv, uvicorn on 127.0.0.1:8100
behind nginx, secrets in `/opt/raqm-api/.env` (`api/env.example` lists them). Vercel's `NEXT_PUBLIC_API_URL` points here.

| file | installed as |
|---|---|
| `api/raqm-api.service` | `/etc/systemd/system/raqm-api.service` |
| `api/nginx-api.da3m.io.conf` | `/etc/nginx/sites-available/api.da3m.io` (+ certbot) |
| `api/update.sh` + `api/raqm-api-update.{service,timer}` | pulls `main` every 5 minutes, restarts the API when `backend/` or a root `.py` changed |

Logs: `journalctl -u raqm-api -f` · deploys: `journalctl -u raqm-api-update`.

## Second paper bot: short new listings

`raqm-listing.service` runs `bot.py --strategy listing_short --state state_listing.json`: short a new Binance USDT-M
perpetual 30 days after listing, hold 90 days, stop 40% above entry, at most 10 open, $20 × 2, paper only
(research/README.md "Short side"). Own state/log files next to the trend bot; the page reads `listing.json`.
Logs: `journalctl -u raqm-listing -f`.

## Third paper bot: weekly momentum long/short

`raqm-momentum.service` runs `bot.py --strategy momentum_ls --state state_momentum.json`: every 7 days (first cycle
after 00:00 UTC) rank the top 50 Binance crypto USDT perpetuals by 30-day volume on their 2-week return, long the
strongest 5 and short the weakest 5 for a week, stop 40%, $20 × 2, fees + real funding, paper only. Page data
`momentum.json`. Live prices on the page come from `wss://fstream.binance.com/market/ws` (Binance moved market
streams there; the old `/ws` path accepts subscriptions but sends nothing). Logs: `journalctl -u raqm-momentum -f`.

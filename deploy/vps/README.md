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

FastAPI backend in `/opt/raqm-api` (folder owned by root, group `raqmapi`; `app/`, `venv/` and `.env` belong to `raqmapi`): a git checkout of this repo + venv, uvicorn on 127.0.0.1:8100
behind nginx, secrets in `/opt/raqm-api/.env` (`api/env.example` lists them). Vercel's `NEXT_PUBLIC_API_URL` points here.

| file | installed as |
|---|---|
| `api/raqm-api.service` | `/etc/systemd/system/raqm-api.service` |
| `api/nginx-api.da3m.io.conf` | `/etc/nginx/sites-available/api.da3m.io` (+ certbot) |
| `api/update.sh` + `api/raqm-api-update.{service,timer}` | `/usr/local/sbin/raqm-api-update` (root-owned) + units, by `sh api/install-updater.sh` from a root-owned checkout: pulls `main` every 5 minutes, restarts the API when `backend/` or a root `.py` changed; frozen when `ALLOW_LIVE_TRADING=true` or a real-money bot unit is installed |

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

## Fourth paper bot: ratio trend — HIGH RISK experiment

`raqm-ratio.service` runs `bot.py --strategy ratio_trend --state state_ratio.json`: every pair among the top 7 Binance
crypto perpetuals by 30-day volume (membership refreshed weekly), once a day after the daily close: ratio above its
50-day average -> long the first / short the second, below -> the reverse; a pair closes when a coin leaves the list.
$20 × 2 per leg (21 pairs ≈ $840 margin), fees + real funding, no stop, paper only. In the fair backtest
(research/ratio_fairness.py) its drawdown reached 795 and it lowered the three bots' combined result — it runs only
to watch it, and the page marks it HIGH RISK. Page data `ratio.json`. Logs: `journalctl -u raqm-ratio -f`.

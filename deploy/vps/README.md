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
scp -r bot.py strategies_*.py trade_card.py assets root@SERVER:/opt/raqm-bot/ && ssh root@SERVER 'chown -R raqm:raqm /opt/raqm-bot/*.py /opt/raqm-bot/assets && systemctl restart raqm-bot'
```

Closed trades go to Telegram as an image card (`trade_card.py`, fonts in `assets/fonts`). The card needs Pillow in
the bot's venv, once: `sudo -u raqm /opt/raqm-bot/venv/bin/pip install --only-binary=:all: pillow==13.0.0`. Without
it the bot still runs and sends the card's text instead.

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

## Real-orders bots: one per strategy on the admin's account

`setup-live.sh <sha>` (as root, from the root-owned clone) installs the bots' code in `/opt/raqm-live`, the unit
template `raqm-demo@.service`, one IPC folder per strategy (`/opt/raqm-ipc/<strategy>`) and the Demo risk ledger
(`/opt/raqm-risk-demo`, play money only). Each strategy runs as its own service on the same Binance account:

    systemctl enable --now raqm-demo@trend_daily raqm-demo@momentum_ls ...     # Binance Demo (play money)

Options per strategy (size, leverage, universe): `/opt/raqm-live/strategies/<strategy>.env`, root-owned, one line
`RAQM_ARGS=--leverage 2 --amount 100 --poll 60`. Strategies on one account never share a coin: the first to take
it holds it until it closes (shared risk ledger), and each bot leaves the others' positions alone.

### Real money

1. The real account's keys, **without withdrawal permission**: `/opt/raqm-live/.env.real` (`BINANCE_API_KEY=`,
   `BINANCE_SECRET=`), owner `raqmlive`, chmod 600.
2. `/opt/raqm-live/allow-live.env`, owner root, chmod 600: `ALLOW_LIVE_TRADING=true` and
   `BINANCE_LIVE_ACCOUNT=<a name>`. Set `ALLOW_LIVE_TRADING=true` in `/opt/raqm-api/.env` too (the dashboard's yes/no
   needs it) and restart the API.
3. Install the real-money template — this also freezes the API's automatic updates (`api/update.sh`):
   `install -m 644 /root/raqm-src/deploy/vps/raqm-live@.service /etc/systemd/system/ && systemctl daemon-reload`
4. Stop the Demo bots (`systemctl disable --now 'raqm-demo@*'`) and start the real ones you want available:
   `systemctl enable --now raqm-live@trend_daily ...`
5. Dashboard → التداول الحقيقي: the account name of step 2, then yes/no per strategy. Only the strategies marked yes
   enter; one turned off stops entering and its open positions still exit on their own rules and stops. The kill
   switch (Risk) stops every strategy's entries at once.

The live bots are not restarted by the setup scripts (one stopped mid-order goes to review): restart them as a
deliberate step, `systemctl restart 'raqm-live@*'`.

# Restoring the bots' records from a backup

What the daily backup (`scripts/backup.py`, `raqm-backup.timer`, a `.tar.gz` in the watchdog's Telegram chat) holds,
and how it goes back. **The positions themselves are on Binance with their stops**; the backup is the bots' records:
state, execution journals, risk ledgers, the Demo yes/no, the watchdog state, the logs. No keys are in it: after a
server loss the key files are made again by the owner (`.env.real`, `.env.live` with `set_demo_keys.sh`).

| in the archive | goes back to | owner:group, mode |
|---|---|---|
| `state/` | `/opt/raqm-live/state/` | raqmlive:raqmlive, files 644 (`*.sqlite3` 644) |
| `risk-live/` | `/opt/raqm-risk/` | raqmlive:raqmrisk, files 660 |
| `risk-demo/` | `/opt/raqm-risk-demo/` | raqmlive:raqmrisk, files 660 |

## 0. Encrypted backups (security plan item 11, from 2026-11-08)

Once the owner's public key is at `/etc/raqm-backup/public.pem`, the chat gets `raqm-backup-YYYYMMDD.tar.gz.enc`
(caption 🔒): the server can lock a backup but never open it. Open it **on your own computer**, where the private key
is, before step 1 (it asks the private key's passphrase):

```bash
RAQM_BACKUP_PRIVATE=backup-private.pem python scripts/backup_crypto.py decrypt raqm-backup-YYYYMMDD.tar.gz.enc
```

Then copy the `.tar.gz` it writes to the server as below. The private key never goes to the server. Lose it (and its
copy) and the old backups can't be opened: keep it on your computer and on a USB stick. A new key pair: run
`python scripts/backup_crypto.py keygen <folder>` and replace the public key on the server; backups from then on use it.

## 1. Check the archive (any time, changes nothing)

Download the day's file from the Telegram chat, copy it to the server (`scp raqm-backup-YYYYMMDD.tar.gz root@…:/tmp/`):

```bash
sudo -u raqmlive /opt/raqm-live/venv/bin/python -I /opt/raqm-live/scripts/restore_check.py /tmp/raqm-backup-YYYYMMDD.tar.gz /tmp/restore-test --compare /opt/raqm-live/state
```

Every line ✅: the archive restores. `--compare` also says whether each bot's open positions in it are today's.

## 2. Put it back (a new server, or lost files)

1. `setup-live.sh <sha>` on the new server first (code, users, folders, units), keys by the owner.
2. Stop every Demo and real bot **by name**, and the API.
3. Copy the three folders from the checked archive (step 1's output folder) to the paths above, with the owners and
   modes in the table.
4. Start the real bot alone, by name; on its first cycle `reconcile_live` compares its records with Binance. Any
   difference becomes a review, not a trade: check it before anything else. Then the Demo bots, by name, and the API.
5. `live_preflight.py --strategy momentum_ls` must pass, and `rebalance_check.py` must be all ✅.

Records newer than the backup (trades after its time) come back from Binance through step 4's reconciliation; the
history lines of those trades are lost unless written down from Binance by hand.

# The owner's step after money left a real account (2026-11-11): set the risk ledger's high-water mark and today's
# start to the balance the bot last read, so the drawdown stops measuring money that was withdrawn, not lost.
# Run it as the ledger's owner, with the equity the dashboard shows (it must match the bot's last reading, at most
# 10 minutes old, within 0.5%), and your name for the audit:
#
#   main account:        sudo -u raqmlive /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/rebase_hwm.py /opt/raqm-risk 358.12 "Owner Name"
#   a sub-account:       sudo -u raqmlive ... rebase_hwm.py /opt/raqm-risk-accounts/<name> <equity> "Owner Name"
#   a user's account:    sudo -u ru<20 hex> /opt/raqm-users/code/venv/bin/python -I /usr/local/lib/raqm/rebase_hwm.py /var/lib/raqm-users/<uid>/risk <equity> "Owner Name"
#   --dry-run            shows what it would do, writes nothing
#
# It never touches the kill switch: reset it from the dashboard afterwards, once the drawdown it shows is right.
import sys
from pathlib import Path

# the code to read the ledger with: the real bots' copy, the users' copy (a user's account can't read /opt/raqm-live),
# or this checkout
for code in ("/opt/raqm-live", "/opt/raqm-users/code", str(Path(__file__).resolve().parent.parent.parent.parent)):
    try:
        if (Path(code) / "backend" / "app" / "risk_manager.py").is_file():
            sys.path.insert(0, code); break
    except OSError:
        continue
from backend.app import risk_manager as rm

args = sys.argv[1:]
dry = "--dry-run" in args
args = [a for a in args if a != "--dry-run"]
if len(args) != 3:
    sys.exit(__doc__ or "usage: rebase_hwm.py <ledger folder> <equity> \"Owner Name\" [--dry-run]")
folder, equity, operator = Path(args[0]), args[1], args[2]
ledger = folder / "risk_state.json"
if not folder.is_dir() or folder.is_symlink():
    sys.exit(f"{folder}: not a ledger folder")
state = rm.load_risk_state(ledger)
hwm, last, at, ks = state.get("equity_high_water_mark"), state.get("equity_last"), state.get("equity_observed_at"), state.get("kill_switch") or {}
basis = lambda h: rm.risk_basis(state["limits"], h)      # as the kill switch measures it (a capital plan caps the basis)
print(f"ledger:            {ledger}")
print(f"high-water mark:   {hwm}")
print(f"last equity read:  {last}  at {at}")
if hwm and last:
    print(f"drawdown now:      {(float(hwm) - float(last)) / basis(float(hwm)) * 100:.2f}%  (limit {state['limits']['max_drawdown_pct']}%)")
print(f"kill switch:       {'TRIPPED — ' + str(ks.get('reason')) if ks.get('tripped') else 'clear'}")
if dry:
    print("dry run: nothing written"); sys.exit(0)
try:
    old, new = rm.rebase_high_water_mark(ledger, equity_usdt=float(equity), operator=operator)
except ValueError as e:
    sys.exit(f"refused, nothing written: {e}")
print(f"✅ high-water mark {old} -> {new}; today's start {new}; drawdown now 0.00%")
print("   the kill switch is as it was: reset it from the dashboard when you're ready")

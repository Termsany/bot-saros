# Roadmap (from 2026-11-12, momentum daily)

The owner asked for a development plan to follow in stages (2026-11-12). It replaces the roadmap of 2026-11-03
(A–F, written for the weekly Monday basket; it is in git history, `bb8c70d`).

**The rule for every stage:** one change at a time, and every idea takes the same path:

1. A backtest: chosen on the data before 2024 and judged on 2024 onward. It is written up in `research/README.md`,
   whether it wins or loses.
2. A paper bot, as an A/B pair next to the version that runs now, on demo.da3m.io.
3. Real money at the smallest size, only when the owner says so.

The real bots are touched last. Each step ships as its own PR, merged after every check is green.

Owner = only the owner can do it (keys, Binance, money, signatures). Claude = code, research, server, checks.

The whole application, all tracks: [development-plan.md](development-plan.md).

## 0. Measurement: running now

| What runs (paper) | Since |
|---|---|
| `raqm-momentum`: weekly basket, opens Wednesday, holds 6 days | 2026-11-11 |
| `raqm-momentum-daily`: a new basket every day at 00:00 UTC, coins still in it stay open | 2026-11-11 |
| `raqm-momentum-daily-b7`: the same, a held coin stays while among the strongest/weakest 7 (research §37) | 2026-11-12 |

- The goal is to check that the live trading matches the backtest: rebalances, stops, fees, and funding. Profit is
  not judged here; two weeks are far too few for that.
- **Passes when** there are two weeks without an operating error, and each bot's switches and costs are within the
  backtest's range.

## 1. The main account goes live (owner's go)

| # | Step | Who |
|---|---|---|
| 1.1 | Add funds to about $500 (a $26 margin ×2 at a 40% stop needs equity ≥ $463) | Owner |
| 1.2 | Close INIT, which was opened by hand | Owner |
| 1.3 | `rebase_hwm.py /opt/raqm-risk <new equity> "<name>"` after the deposit | Owner |
| 1.4 | Reset the kill switch after 00:00 UTC | Owner |
| 1.5 | Rebind the readiness evidence to the live sha; Claude prepares it, the owner signs | Claude + owner |
| 1.6 | Read-only review of the first real basket: fills, stops on the exchange, and the coins kept | Claude |

Alongside:
- Close the second account (owner).
- Deploy the 2026-11-11 cleanup, which is merged but not deployed.

**Passes when** there are two real weeks and the gap between real and paper is small and explained (fees, slippage,
timing).

## 2. Improve the strategy (research → paper)

Each idea is its own study, in this order:

| # | Idea | Why |
|---|---|---|
| 2.1 | Buffer 7: decide from the A/B in stage 0 | The backtest shows the worst drawdown at $358 instead of $578, for 11% less profit |
| 2.2 | Exclude new coins (listed fewer than N days) | Likely the source of the largest stops |
| 2.3 | Size by volatility: a wilder coin gets a smaller leg | The same risk per leg instead of the same dollars |
| 2.4 | Blend lookbacks (2 weeks + 4 weeks) in the ranking | 2w and 4w were each the best on different periods |

- Ideas already closed are not reopened: the reversal basket (all 10 variants lost) and no shorts (§37).
- **Passes when** an idea wins in both periods, not one. Anything that fails is recorded and closed.

## 3. Execution quality and risk

- Measure the real slippage per leg against the paper price, kept by the bot and shown on the page.
- A liquidity filter for thin coins.
- Review the risk limits (the 40% stop, the daily loss limit, the aggregate) on real data.
- The rest of the security plan (items 10 and 12).

## 4. Scale

- Raise capital in steps, each after 4 clean weeks, never more than one step at a time, and never within a week
  of a loss larger than the basket's normal range.
- **Before any step up:** an independent review of the order path by a programmer other than the owner, its
  findings fixed, and the evidence's reviewers updated. None exists yet; the owner accepted that at this size.
- The four invited friends' accounts on the users' path (`provision_users.py`, evidence matched to the deployed sha).
- A second strategy not tied to momentum (RSI-2 from #167 is the first candidate), on its own account, so the
  drawdowns spread.

## Always on

- Each week: dependency and security updates through PRs; secret-scan stays green.
- Each month: rotate the bots' API keys (the owner creates them; Claude installs nothing secret).
- Any recovery, a stop missing on the exchange, or a watchdog alert on a real bot: the kill switch first, then the
  cause.

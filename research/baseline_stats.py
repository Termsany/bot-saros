"""
The Demo measurement baseline (owner, 2026-10-30): what each of the 7 live strategies did in the backtest, in units
that can be compared with the Demo after a few weeks — trades per month, win rate, average win / loss as % of a
trade's margin, profit factor, worst drawdown in trades' worth of margin, most open at once. Each strategy is
simulated with the settings the bot runs (bot.py VB / RSI2 / TB and the core bots of bots_stats.py), on every Binance
USDT-M perpetual since 2019 (delisted included), fees and real funding included.

  python research/baseline_stats.py        -> docs/demo-baseline.md and lib/demo-baseline.json
"""
import sys, json, pickle
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import pump_momentum_study as pm
import bots_stats as bs
import ratio_fairness as rf
import traders_study as ts
from universe_study import ranks

CACHE = Path(__file__).resolve().parent / ".cache"
MARGIN = ts.AMOUNT                      # every simulator trades $20 margin x2; results are given per $ of margin
OOS = pd.Timestamp("2024-01-01")
LABELS = {"trend_daily": "الترند اليومي", "listing_short": "شورت العملات الجديدة", "momentum_ls": "مومنتم (سلة)",
          "ratio_trend": "ترند النسبة (أزواج)", "vol_breakout": "بريك أوت التذبذب", "rsi2_pullback": "RSI-2",
          "trend_breakout": "اختراق الترند"}


def stats(trades):
    t = pd.DataFrame(trades)
    t["exit_d"] = pd.to_datetime(t.exit_ts, unit="ms"); t["entry_d"] = pd.to_datetime(t.entry_ts, unit="ms")
    out = {}
    for name, part in (("all", t), ("since_2024", t[t.exit_d >= OOS])):
        r = part.pnl / MARGIN * 100                                   # % of the trade's margin
        months = max(1.0, (part.exit_d.max() - part.exit_d.min()).days / 30.44) if len(part) else 1.0
        daily = part.groupby(part.exit_d.dt.floor("D")).pnl.sum().sort_index().cumsum()
        wins, losses = r[r > 0], r[r <= 0]
        out[name] = {"trades": int(len(part)), "per_month": round(len(part) / months, 1),
                     "win_rate": round(float((r > 0).mean() * 100), 1) if len(part) else None,
                     "avg_win_pct": round(float(wins.mean()), 1) if len(wins) else None,
                     "avg_loss_pct": round(float(losses.mean()), 1) if len(losses) else None,
                     "profit_factor": round(float(part.pnl[part.pnl > 0].sum() / -part.pnl[part.pnl <= 0].sum()), 2) if (part.pnl <= 0).any() else None,
                     "max_dd_margins": round(float((daily.cummax() - daily).max()) / MARGIN, 1) if len(daily) else None,
                     "net_margins": round(float(part.pnl.sum()) / MARGIN, 1)}
    ev = pd.concat([pd.Series(1, index=t.entry_d), pd.Series(-1, index=t.exit_d)]).sort_index().cumsum()
    out["max_open"] = int(ev.max())
    out["to"] = str(t.exit_d.max().date())
    return out


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    trades = bs.trades_at(ts.LEV, data, fund, rk10, ever10, pm.rank_table(data, 60), new)
    trades["ratio_trend"] = rf.dynamic_trades(data, fund, pm.rank_table(data, 120), 7, 50)[0]

    A = ts.coin_arrays(data, fund, pm.rank_table(data, 60))
    sys.path.insert(0, str(ROOT)); import bot
    ts.SLIP = bot.VB["slip"]
    trades["vol_breakout"] = ts.vb_trades(A, bot.VB["top"], bot.VB["k"], bot.VB["ma"])
    ts.SLIP = 0.0
    trades["rsi2_pullback"] = ts.rsi2_trades(A, bot.RSI2["top"], bot.RSI2["below"], True, "sma5")
    ts.SLIP = bot.TB["slip"]
    trades["trend_breakout"] = ts.vcp_trades(A, bot.TB["top"], bot.TB["L"], float("inf"), "40pct", bot.TB["exit_ma"])   # no contraction filter

    result = {k: stats(trades[k]) for k in LABELS}
    meta = {"generatedAt": str(pd.Timestamp.now().date()), "from": "2019-09-01", "margin_usdt": MARGIN, "leverage": ts.LEV,
            "fee_per_side": ts.FEE, "note": "pnl and drawdown are per $ of margin: multiply by the Demo margin"}
    (ROOT / "lib" / "demo-baseline.json").write_text(json.dumps({"meta": meta, "strategies": result}, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = ["| الاستراتيجية | صفقات/شهر (من 2024) | نسبة الكسب | متوسط الكسب | متوسط الخسارة | Profit factor | أسوأ تراجع | أقصى مفتوح |",
            "|---|---|---|---|---|---|---|---|"]
    for k, r in result.items():
        a, o = r["all"], r["since_2024"]
        rows.append(f"| {LABELS[k]} (`{k}`) | {a['per_month']} ({o['per_month']}) | {a['win_rate']}% ({o['win_rate']}%) | +{a['avg_win_pct']}% | {a['avg_loss_pct']}% "
                    f"| {a['profit_factor']} ({o['profit_factor']}) | {a['max_dd_margins']} مارجن | {r['max_open']} |")
    doc = f"""# خط الأساس لقياس الـ Demo

اللي عمله كل استراتيجية في الـ backtest، بنفس إعدادات البوت، على كل عقود Binance USDT-M من 2019 لحد {max(r['to'] for r in result.values())}
(العملات اللي اتشالت محسوبة)، بالرسوم والـ funding الحقيقي. بين القوسين: من أول 2024 بس (فترة ماكانتش في اختيار الإعدادات).

{chr(10).join(rows)}

**إزاي تقرا الجدول**
- متوسط الكسب والخسارة **نسبة من مارجن الصفقة**: بمارجن 100$، ‎+20% يعني ‎+20$.
- أسوأ تراجع **بعدد مرات المارجن**: 15 مارجن بمارجن 100$ = 1,500$ تراجع من أعلى نقطة.
- الأرقام دي لمارجن ثابت لكل صفقة ومن غير حد مشترك. على الـ Demo كل استراتيجية شغالة ليها نصيب متساوي من أماكن الحساب (الأماكن ÷ عدد الاستراتيجيات الشغالة): لو نصيبها أقل من «أقصى مفتوح» في الجدول، عدد صفقاتها وتراجعها هيبقوا أقل من الجدول.

**هنقارن إيه بعد كام أسبوع** (لكل استراتيجية، بعد 30 صفقة على الأقل)
1. عدد الصفقات في الشهر قريب من الجدول — بس للاستراتيجية اللي نصيبها مش أقل من «أقصى مفتوح». غير كده الأقل متوقع؛ لو صفر خالص: البوت مش بيشوف الإشارات أو حاجة بتمنعه (شوف «ليه مفيش صفقات» في الأدمن).
2. نسبة الكسب ومتوسط الكسب والخسارة قريبين — لو الخسارة أكبر بكتير: الدخول أو الخروج بسعر أسوأ من المتوقع.
3. الـ profit factor فوق 1 بعد الرسوم.
4. التراجع مش أسوأ من الجدول.

استراتيجية تبعد كتير عن الجدول بعد 30 صفقة تتقفل، مش تتعدّل. الأرقام دي backtest: مش ضمان، والسوق ممكن يتغير.

`python research/baseline_stats.py` بيعمل الملف ده من جديد.
"""
    (ROOT / "docs" / "demo-baseline.md").write_text(doc, encoding="utf-8")
    print(doc)


if __name__ == "__main__":
    main()

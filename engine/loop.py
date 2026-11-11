"""the main loop: market data client, run_once, run_loop, the local dashboard.
Moved from bot.py unchanged (2026-11-11): a bot-level name used in a function is read as bot.<name>, so the CLI's
settings, bot.py's state paths and the tests' patches on bot reach it. Import bot, not this module."""
import bot
import ccxt, pandas as pd, numpy as np, time, json, os, re, uuid, threading, http.server, socketserver, webbrowser
from datetime import datetime, timezone
from pathlib import Path
import strategies_advanced as adv
from backend.app.execution_safety import AmbiguousFill, authoritative_position_state, futures_net_pnl, linear_contracts_from_margin, normalize_filled_contracts
from backend.app import risk_manager as riskmgr
from backend.app.multi_leg_execution import MultiLegExecutionEngine
from backend.app import live_activation


MARKET_DATA_METHODS = ("fetch_ohlcv", "fetch_ticker", "fetch_tickers")
_strategy_ex = {}

def strategy_exchange():
    """The exchange the portfolio strategies run on. Paper: Binance's public market (the research data is Binance's).
    Live / demo: the keyed account for orders, positions and balance — candles and prices still come from Binance's
    real public market, as in run_once (Demo Trading's own candles are its play-money activity). Before this, live
    mode handed these strategies the keyless public client: no order, balance or position call could ever work."""
    if "public" not in bot._strategy_ex: bot._strategy_ex["public"] = ccxt.binanceusdm({"enableRateLimit": True})
    if bot.CONFIG["paper_trading"]: return bot._strategy_ex["public"]
    if "keyed" not in bot._strategy_ex:
        ex, err = bot.get_exchange(auth=True)
        if err:
            bot.log(f"⛔ LIVE من غير مفاتيح: {err} — البوت وقف"); bot.notify(f"⛔ البوت الحقيقي وقف: {err}")
            raise SystemExit(2)
        for name in bot.MARKET_DATA_METHODS: setattr(ex, name, getattr(bot._strategy_ex["public"], name))
        bot._strategy_ex["keyed"] = ex
    return bot._strategy_ex["keyed"]

def _write_basket_live_status(ex):
    """The basket strategies (listing, momentum, ratio) write the admin page's live status too, after every cycle
    whatever path it took — without it their bots showed as not running on the dashboard."""
    if bot.CONFIG["paper_trading"]: return
    try:
        state = bot.load_state(); prices = {}
        if state["positions"]:
            try:
                tick = ex.fetch_tickers(list(state["positions"]))
                prices = {s: float((tick.get(s) or {}).get("last")) for s in state["positions"] if (tick.get(s) or {}).get("last")}
            except Exception as e: bot.log(f"live status prices: {e}")
        bot.write_live_status(state, prices)
    except Exception as e: bot.log(f"live status: {e}")

def run_once():
    if bot.breakout_mode(): return bot.run_once_breakout(bot.strategy_exchange())
    if bot.rsi2_mode(): return bot.run_once_rsi2(bot.strategy_exchange())
    if bot.tbreak_mode(): return bot.run_once_tbreak(bot.strategy_exchange())
    for mode, run in ((bot.ratio_mode, bot.run_once_ratio), (bot.momentum_mode, bot.run_once_momentum), (bot.listing_mode, bot.run_once_listing)):
        if mode():
            ex = bot.strategy_exchange()
            try: return run(ex)
            finally: bot._write_basket_live_status(ex)
    if bot.trend_mode(): bot.CONFIG["timeframe"]="1d"
    state=bot.load_state()
    ex,err=bot.get_exchange(auth=not bot.CONFIG["paper_trading"])
    if err:
        # switching to paper here would "close" real positions only in state.json and leave them open on the exchange
        bot.log(f"⛔ LIVE من غير مفاتيح: {err} — البوت وقف"); bot.notify(f"⛔ البوت الحقيقي وقف: {err}")
        raise SystemExit(2)
    if bot.CONFIG["paper_trading"]: bot.process_paper_closes(state, ex, "status")
    prices={}; analyses={}
    # live: the coin list and the signals come from Binance's real public market (no keys) — Demo Trading's own
    # volumes and candles are its play-money activity — and only orders, positions and balance use the account
    data_ex = ex
    if not bot.CONFIG["paper_trading"]:
        global _live_data_ex
        if "_live_data_ex" not in globals(): _live_data_ex = ccxt.binanceusdm({"enableRateLimit": True})
        data_ex = _live_data_ex
        try: ex.load_markets()
        except Exception as e: bot.log(f"⚠️ markets: {e}")
    try: symbols, allowed = bot.cycle_symbols(data_ex, state)
    except Exception as e: bot.log(f"قائمة العملات: {e}"); symbols, allowed = sorted(set(bot._universe["symbols"]) | set(state["positions"])), set(bot._universe["symbols"])
    if not bot.CONFIG["paper_trading"] and ex.markets:
        symbols, allowed = bot._resolve_live_symbols(ex, symbols, allowed)
    for sym in symbols:
        try:
            df=bot.fetch_ohlcv(sym, bot.CONFIG["timeframe"], limit=bot.candles_needed(), ex=data_ex)
            a=bot.analyze(sym, df); a["in_universe"]=allowed is None or sym in allowed; analyses[sym]=a; prices[sym]=a["price"]
            if sym in bot._universe["symbols"]: a["rank"]=bot._universe["symbols"].index(sym)+1   # 1 = most volume
            bd=" | ".join(f"{k} {v[0]:+.2f}" for k,v in a["breakdown"].items())
            # اختصر SHIB/PEPE لعرض أوضح
            bot.log(f"{sym:10s} @ {a['price']:.6g} سكور {a['total']:+.3f} {a['decision']:8s} | {bd} | SL {a['sl']:.4g} TP {a['tp']:.4g}" if a.get('tp') else f"{sym:10s} @ {a['price']:.6g} {a['decision']:8s} | {bd} | وقف حماية {a['sl']:.4g}")
        except Exception as e: bot.log(f"{sym} فشل: {e}")
    if not bot.CONFIG["paper_trading"]:
        bot.reconcile_live(state, ex)
        bot.process_manual_closes(state, ex, prices)
    if prices: bot.check_sl_tp(state, prices, ex)
    for sym,a in analyses.items():
        try: bot.try_enter(sym,a,state,ex)
        except Exception as e: bot.log(f"دخول {sym}: {e}")
    bot.write_public_status(state, analyses, allowed if allowed is not None else symbols)
    if not bot.CONFIG["paper_trading"]: bot.write_live_status(state, prices, analyses)
    if state["positions"]: bot.log(f"📊 مفتوحة: {list(state['positions'].keys())} | PnL {state['stats']['pnl']:+.4f} | {state['stats']['wins']}W/{state['stats']['losses']}L")
    else: bot.log(f"📊 لا صفقات مفتوحة | PnL {state['stats']['pnl']:+.4f} | {state['stats']['wins']}W/{state['stats']['losses']}L")
    # حدث ملف الداشبورد
    try:
        dash_path=Path(bot.__file__).parent / "dashboard-data.json"
        dash_path.write_text(json.dumps({"analyses":analyses,"state":state,"time":datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def run_loop():
    mode="Paper وهمي" if bot.CONFIG["paper_trading"] else "LIVE حقيقي"
    bot.CONFIG["started_at"]=datetime.now(timezone.utc).isoformat()
    if bot.breakout_mode():
        V=bot.VB
        bot.log(f"=== بريك أوت التذبذب (Larry Williams): أعلى {V['top']} فوليوم فوق متوسط {V['ma']} يوم، دخول عند الافتتاح + {V['k']} × مدى امبارح، خروج افتتاح بكرة — {mode} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} ===")
        bot.notify(f"▶️ بوت بريك أوت التذبذب اشتغل ({mode})\nأعلى {V['top']} عملة فوليوم · دخول عند اختراق الافتتاح + {V['k']} × مدى امبارح · خروج افتتاح اليوم التالي")
    elif bot.tbreak_mode():
        T=bot.TB
        bot.log(f"=== اختراق الترند (Minervini/Darvas من غير الانكماش): أعلى {T['top']} فوليوم في ترند صاعد، دخول على كسر أعلى {T['L']} يوم، خروج تحت متوسط {T['exit_ma']} يوم — {mode} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} ===")
        bot.notify(f"▶️ بوت اختراق الترند اشتغل ({mode}) — تجربة\nأعلى {T['top']} عملة فوليوم في ترند صاعد · دخول على كسر أعلى {T['L']} يوم · خروج تحت متوسط {T['exit_ma']} يوم")
    elif bot.rsi2_mode():
        R=bot.RSI2
        bot.log(f"=== RSI-2 (Larry Connors): أعلى {R['top']} فوليوم فوق متوسط {R['trend_ma']} يوم، دخول لما RSI-2 تحت {R['below']}، خروج فوق متوسط {R['exit_ma']} أيام (أقصى {R['max_days']}) — {mode} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} ===")
        bot.notify(f"▶️ بوت RSI-2 اشتغل ({mode})\nأعلى {R['top']} عملة فوليوم في ترند صاعد · شراء الهبوط لما RSI-2 تحت {R['below']} · خروج فوق متوسط {R['exit_ma']} أيام")
    elif bot.ratio_mode():
        R=bot.RATIO
        bot.log(f"=== ⚠️ HIGH RISK — ratio trend: كل الأزواج بين أعلى {R['top']} فوليوم، فوق متوسط {R['sma']} يوم = لونج الأولى/شورت التانية — {mode} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} لكل رجل ===")
        bot.notify(f"▶️ ⚠️ HIGH RISK — بوت ratio trend اشتغل ({mode})\nكل الأزواج بين أعلى {R['top']} عملة فوليوم · تجربة لمتابعة الأداء بس")
    elif bot.momentum_mode():
        M=bot.MOM
        if M.get("score") == "retail":
            bot.log(f"=== عكس الأغلبية: لونج أقل {M['n']} وشورت أعلى {M['n']} في نسبة لونج/شورت الحسابات من أعلى {M['top']} فوليوم — {mode} — تبديل كل أربع 00:00 UTC، وقف {M['stop']:.0%} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} ===")
            bot.notify(f"▶️ بوت عكس الأغلبية اشتغل ({mode})\nكل أربع: لونج أقل {M['n']} وشورت أعلى {M['n']} في نسبة لونج/شورت من أعلى {M['top']} عملة فوليوم")
        else:
            # the schedule as MOM says it (Wednesday-6 since 2026-11-11, or every day for momentum_daily)
            days = ["الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت", "الحد"]
            if M.get("weekday") is False:
                when = f"سلة جديدة كل {M['every_days']} يوم 00:00 UTC" if M["every_days"] > 1 else "سلة جديدة كل يوم 00:00 UTC"
            else:
                when = f"يفتح كل {days[M['weekday']]} 00:00 UTC"
                if M.get("hold_days", 7) < M["every_days"]: when += f" ويقفل بعد {M['hold_days']} أيام"
            bot.log(f"=== مومنتم: لونج أقوى {M['n']} وشورت أضعف {M['n']} من أعلى {M['top']} فوليوم (عائد {M['weeks']} أسبوع) — {mode} — {when}، وقف {M['stop']:.0%} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} ===")
            bot.notify(f"▶️ بوت المومنتم اشتغل ({mode})\n{when}: لونج أقوى {M['n']} وشورت أضعف {M['n']} من أعلى {M['top']} عملة فوليوم")
    elif bot.listing_mode():
        L=bot.LISTING
        bot.log(f"=== شورت العملات الجديدة — {mode} — دخول بعد {L['skip_days']} يوم، خروج بعد {L['hold_days']} يوم، وقف {L['stop']:.0%}، أقصى {L['max_open']} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} ===")
        bot.notify(f"▶️ بوت شورت العملات الجديدة اشتغل ({mode})\nدخول بعد {L['skip_days']} يوم من الإدراج · خروج بعد {L['hold_days']} يوم · وقف {L['stop']:.0%} · أقصى {L['max_open']} صفقات")
    elif bot.trend_mode():
        coins=f"أعلى {bot.CONFIG['universe_size']} عملة فوليوم" if bot.CONFIG.get("universe_size") else f"{len(bot.CONFIG['symbols'])} عملة"
        bot.log(f"=== ترند يومي — لونج بس — {mode} — {coins} | هامش {bot.CONFIG['trade_amount_usdt']} USDT x{bot.CONFIG.get('leverage',2)} | كل {bot.CONFIG['poll_seconds']}s ===")
        bot.notify(f"▶️ بوت رقم اشتغل — ترند يومي ({mode})\n{coins} · هامش ${bot.CONFIG['trade_amount_usdt']:.0f} x{bot.CONFIG.get('leverage',2)}")
    else:
        bot.log(f"=== بوت 20 زوج FUTURES لونج/شورت — {mode} ===")
        bot.log(f"الازواج {len(bot.CONFIG['symbols'])} فريم {bot.CONFIG['timeframe']} كل {bot.CONFIG['poll_seconds']}s | حجم {bot.CONFIG['trade_amount_usdt']} USDT | SL {bot.CONFIG['stop_loss_pct']*100:.0f}% TP {bot.CONFIG['take_profit_pct']*100:.0f}%")
    n=0
    while True:
        n+=1; bot.log(f"\n——— دورة #{n} ———")
        try: bot.run_once()
        except Exception as e: bot.log(f"خطأ دورة: {e}")
        time.sleep(bot.CONFIG["poll_seconds"])

# ---- Dashboard HTTP Server ----
class DashHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.end_headers()
            try: data=Path(bot.__file__).parent.joinpath("state.json").read_text(encoding="utf-8")
            except: data=json.dumps(bot.load_state(), ensure_ascii=False)
            self.wfile.write(data.encode("utf-8")); return
        if self.path.startswith("/api/dashboard"):
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.end_headers()
            try: data=Path(bot.__file__).parent.joinpath("dashboard-data.json").read_text(encoding="utf-8")
            except: data=json.dumps({"analyses":{},"state":bot.load_state()}, ensure_ascii=False)
            self.wfile.write(data.encode("utf-8")); return
        if self.path.startswith("/api/klines"):
            # /api/klines?symbol=BTC/USDT&interval=1h&limit=200  -> proxy to Binance
            from urllib.parse import urlparse, parse_qs
            import urllib.request
            qs=parse_qs(urlparse(self.path).query)
            sym=(qs.get("symbol",["BTC/USDT"])[0]).replace("/","")
            interval=qs.get("interval",["1h"])[0]; limit=qs.get("limit",["200"])[0]
            if not (re.fullmatch(r"[A-Z0-9]{2,20}", sym) and re.fullmatch(r"\d{1,2}[mhdw]", interval) and re.fullmatch(r"\d{1,4}", limit)):
                self.send_response(400); self.end_headers(); return
            url=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
            try:
                with urllib.request.urlopen(url, timeout=10) as r: body=r.read()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                self.wfile.write(body); return
            except Exception as e:
                self.send_response(502); self.end_headers(); self.wfile.write(json.dumps({"error":str(e)}).encode()); return
        self.send_response(404); self.end_headers()   # no file serving: the bot folder holds .env and the key vault
    def end_headers(self):
        super().end_headers()

def start_dashboard_server(port=None):
    port=port or bot.CONFIG["dashboard_port"]
    root=str(Path(bot.__file__).parent)
    os.chdir(root)
    handler=lambda *a, **kw: bot.DashHandler(*a, directory=root, **kw)
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:   # this machine only
        bot.log(f"🌐 الداشبورد http://localhost:{port}/  (index.html)")
        try: webbrowser.open(f"http://localhost:{port}/index.html")
        except: pass
        httpd.serve_forever()

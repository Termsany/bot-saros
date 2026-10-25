from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
DB_PATH = _ROOT / "raqm.db"
if not DB_PATH.exists() and (_ROOT / "saros.db").exists():
    (_ROOT / "saros.db").rename(DB_PATH)
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    side = Column(String)
    entry = Column(Float)
    exit = Column(Float, nullable=True)
    qty = Column(Float)
    pnl = Column(Float, nullable=True)
    reason = Column(String, nullable=True)
    entry_ts = Column(String)
    exit_ts = Column(String, nullable=True)
    status = Column(String, default="open")
    sl = Column(Float)
    tp = Column(Float)
    leverage = Column(Integer, default=5)
    created_at = Column(String)

class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True, nullable=True)
    symbol = Column(String)
    timeframe = Column(String)
    from_date = Column(String, nullable=True)
    to_date = Column(String, nullable=True)
    strategies = Column(Text)
    stats = Column(Text)
    created_at = Column(String)
    chart_file = Column(String, nullable=True, index=True)
    run_name = Column(String, nullable=True, index=True)

class UserSetting(Base):
    __tablename__ = "user_settings"
    user_id = Column(String, primary_key=True)
    capital = Column(Float)
    strategy = Column(String)
    started_at = Column(String)
    updated_at = Column(String)

class UserClose(Base):
    """A trade the user closed by hand in their personal paper portfolio (it only changes their own record)."""
    __tablename__ = "user_closes"
    user_id = Column(String, primary_key=True)
    trade_key = Column(String, primary_key=True)   # "<label>@<opened>" as the site builds it (BTC@2026-..., SOL / ETH@...)
    bot_pnl = Column(Float)                         # the bot's own PnL on that trade at the moment of the close
    exit_price = Column(Float, nullable=True)       # single-coin trades only
    closed_at = Column(String)

class BotInstance(Base):
    __tablename__ = "bot_instances"
    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String, unique=True, index=True)
    strategy = Column(String)
    symbols = Column(Text)
    timeframe = Column(String)
    paper = Column(Integer, default=1)
    leverage = Column(Integer, default=5)
    status = Column(String, default="starting")
    heartbeat_at = Column(String)
    created_at = Column(String)
    updated_at = Column(String)

class ProtectiveOrder(Base):
    __tablename__ = "protective_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey("trades.id", ondelete="SET NULL"), index=True, nullable=True)
    symbol = Column(String, index=True)
    client_order_id = Column(String, index=True)
    exchange_order_id = Column(String, nullable=True)
    side = Column(String)
    qty = Column(Float)
    price = Column(Float)
    status = Column(String, default="open")
    created_at = Column(String)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for tbl, col, ddl in [
            ("backtest_runs", "user_id", "ALTER TABLE backtest_runs ADD COLUMN user_id VARCHAR"),
            ("backtest_runs", "chart_file", "ALTER TABLE backtest_runs ADD COLUMN chart_file VARCHAR"),
            ("backtest_runs", "run_name", "ALTER TABLE backtest_runs ADD COLUMN run_name VARCHAR"),
        ]:
            cols = [r[1] for r in (await conn.exec_driver_sql(f"PRAGMA table_info({tbl})")).fetchall()]
            if col not in cols:
                await conn.exec_driver_sql(ddl)
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_backtest_runs_chart_file ON backtest_runs (chart_file)",
            "CREATE INDEX IF NOT EXISTS ix_backtest_runs_run_name ON backtest_runs (run_name)",
        ]:
            try:
                await conn.exec_driver_sql(idx_sql)
            except Exception:
                pass
        try:
            tbls = [r[0] for r in (await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='protective_orders'")).fetchall()]
            if "protective_orders" in tbls:
                fk_list = (await conn.exec_driver_sql("PRAGMA foreign_key_list(protective_orders)")).fetchall()
                has_fk = any(f[2] == "trades" for f in fk_list)
                if not has_fk:
                    await conn.exec_driver_sql("ALTER TABLE protective_orders RENAME TO protective_orders_old")
                    await conn.run_sync(lambda sync_conn: Base.metadata.tables["protective_orders"].create(bind=sync_conn, checkfirst=True))
                    old_cols = [r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(protective_orders_old)")).fetchall()]
                    copy_cols = [c for c in ["id","trade_id","symbol","client_order_id","exchange_order_id","side","qty","price","status","created_at"] if c in old_cols]
                    if copy_cols:
                        csv = ", ".join(copy_cols)
                        await conn.exec_driver_sql(f"INSERT INTO protective_orders ({csv}) SELECT {csv} FROM protective_orders_old")
                    await conn.exec_driver_sql("DROP TABLE protective_orders_old")
        except Exception as e:
            print(f"protective_orders FK migration warn: {e}")

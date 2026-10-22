
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
DB_PATH = _ROOT / "raqm.db"
# renamed from saros.db — keep existing data
if not DB_PATH.exists() and (_ROOT / "saros.db").exists():
    (_ROOT / "saros.db").rename(DB_PATH)
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    side = Column(String)  # long/short
    entry = Column(Float)
    exit = Column(Float, nullable=True)
    qty = Column(Float)
    pnl = Column(Float, nullable=True)
    reason = Column(String, nullable=True)
    entry_ts = Column(String)
    exit_ts = Column(String, nullable=True)
    status = Column(String, default="open")  # open/closed
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
    strategies = Column(Text)  # json
    stats = Column(Text)  # json
    created_at = Column(String)

class UserSetting(Base):
    """Per-user setup for the personal paper portfolio: capital and the bot it follows (dashboard)."""
    __tablename__ = "user_settings"
    user_id = Column(String, primary_key=True)
    capital = Column(Float)
    strategy = Column(String)
    started_at = Column(String)   # reset whenever capital or strategy changes — the portfolio counts from here
    updated_at = Column(String)

class BotInstance(Base):
    """Persistent bot supervisor: survives restarts, prevents duplicate instances (P1-06)."""
    __tablename__ = "bot_instances"
    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String, unique=True, index=True)
    strategy = Column(String)
    symbols = Column(Text)  # json list
    timeframe = Column(String)
    paper = Column(Integer, default=1)
    leverage = Column(Integer, default=5)
    status = Column(String, default="starting")  # starting/running/stopping/stopped/error
    heartbeat_at = Column(String)
    created_at = Column(String)
    updated_at = Column(String)

class ProtectiveOrder(Base):
    """Ownership of exchange SL/TP orders (P0-04 persistence)."""
    __tablename__ = "protective_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, index=True)
    symbol = Column(String, index=True)
    client_order_id = Column(String, index=True)
    exchange_order_id = Column(String)
    side = Column(String)  # sl/tp
    qty = Column(Float)
    price = Column(Float)
    status = Column(String, default="open")  # open/cancelled/filled/error
    created_at = Column(String)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all doesn't add columns to an existing table — migrate older database files
        cols = [r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(backtest_runs)")).fetchall()]
        if "user_id" not in cols:
            await conn.exec_driver_sql("ALTER TABLE backtest_runs ADD COLUMN user_id VARCHAR")

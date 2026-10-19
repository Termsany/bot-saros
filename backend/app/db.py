
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "saros.db"
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
    symbol = Column(String)
    timeframe = Column(String)
    from_date = Column(String, nullable=True)
    to_date = Column(String, nullable=True)
    strategies = Column(Text)  # json
    stats = Column(Text)  # json
    created_at = Column(String)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

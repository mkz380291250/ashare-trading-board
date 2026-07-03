from datetime import date
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DailyQuote
from app.backtest.qlib_data import export_market_csvs_full

EXPECTED_COLS = ["date", "open", "high", "low", "close", "volume", "factor",
                 "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
                 "pe", "pb", "amount"]


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _quote(code, d, close, **kw):
    base = dict(code=code, trade_date=d, open=close, high=close, low=close,
                close=close, vol=1000.0, adj_factor=2.0, amount=5000.0,
                turnover_rate=1.5, volume_ratio=0.9, circ_mv=8.8e5,
                total_mv=9.9e5, pe=25.0, pb=3.0)
    base.update(kw)
    return DailyQuote(**base)


def test_exports_all_columns_unadjusted(tmp_path):
    s = _sess()
    s.add(_quote("600519.SH", date(2026, 6, 1), 100.0))
    s.commit()
    n = export_market_csvs_full(s, ["600519.SH"], date(2026, 6, 1),
                                date(2026, 6, 2), str(tmp_path))
    assert n == 1
    df = pd.read_csv(tmp_path / "SH600519.csv")
    assert list(df.columns) == EXPECTED_COLS
    assert df.loc[0, "factor"] == 2.0          # factor 单独一列
    assert df.loc[0, "turnover_rate"] == 1.5   # 原值,不复权
    assert df.loc[0, "pe"] == 25.0
    assert df.loc[0, "amount"] == 5000.0


def test_null_optionals_become_empty(tmp_path):
    s = _sess()
    s.add(_quote("000001.SZ", date(2026, 6, 1), 10.0,
                 pe=None, pb=None, turnover_rate=None, circ_mv=None,
                 total_mv=None, volume_ratio=None, amount=None))
    s.commit()
    export_market_csvs_full(s, ["000001.SZ"], date(2026, 6, 1),
                            date(2026, 6, 2), str(tmp_path))
    df = pd.read_csv(tmp_path / "SZ000001.csv")
    assert pd.isna(df.loc[0, "pe"]) and pd.isna(df.loc[0, "amount"])
    assert df.loc[0, "close"] == 10.0


def test_no_rows_skipped(tmp_path):
    s = _sess()
    n = export_market_csvs_full(s, ["600000.SH"], date(2026, 6, 1),
                                date(2026, 6, 2), str(tmp_path))
    assert n == 0
    assert not (tmp_path / "SH600000.csv").exists()

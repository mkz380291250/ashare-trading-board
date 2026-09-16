from datetime import date
from app.data.source import DailyBar
from app.backtest.qlib_data import export_bars_csv


def _bars():
    return [DailyBar("600519.SH", date(2026, 6, 1), 100, 105, 99, 104, 1000, 1.0),
            DailyBar("600519.SH", date(2026, 6, 2), 104, 108, 103, 107, 1200, 1.0)]


def test_export_bars_csv_uses_qlib_symbol_filename(tmp_path):
    path = export_bars_csv(_bars(), str(tmp_path))
    assert path.name == "SH600519.csv"
    text = path.read_text()
    assert "date,open,high,low,close,volume,factor" in text
    assert "104" in text


def test_export_bars_csv_empty_returns_none(tmp_path):
    assert export_bars_csv([], str(tmp_path)) is None


def test_export_full_merges_extra_columns(tmp_path):
    import pandas as pd
    from app.db.database import make_engine, make_session_factory, Base
    from app.db.models import DailyQuote
    from app.backtest.qlib_data import export_market_csvs_full
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = make_session_factory(eng)()
    for d, c in [(date(2025, 1, 2), 10.0), (date(2025, 1, 3), 11.0)]:
        s.add(DailyQuote(code="300750.SZ", trade_date=d, open=c, high=c, low=c, close=c,
                         vol=100.0, amount=1.0, adj_factor=1.0))
    s.commit()

    def extra(code, dates):
        assert code == "300750.SZ"
        return pd.DataFrame({"np_ttm": [1.0, 2.0], "mf_net": [None, 3.0]}, index=dates)

    n = export_market_csvs_full(s, ["300750.SZ"], date(2025, 1, 1), date(2025, 1, 31),
                                str(tmp_path), extra_fn=extra)
    assert n == 1
    df = pd.read_csv(tmp_path / "SZ300750.csv")
    assert list(df.columns)[:3] == ["date", "open", "high"]
    assert "np_ttm" in df.columns and "mf_net" in df.columns
    assert df["np_ttm"].tolist() == [1.0, 2.0]
    assert pd.isna(df["mf_net"].iloc[0]) and df["mf_net"].iloc[1] == 3.0


def test_export_bulk_matches_per_code_export(tmp_path):
    import pandas as pd
    from app.db.database import make_engine, make_session_factory, Base
    from app.db.models import DailyQuote
    from app.backtest.qlib_data import export_market_csvs_full, export_market_csvs_bulk
    db = tmp_path / "t.db"
    eng = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(eng)
    s = make_session_factory(eng)()
    for code in ["300750.SZ", "000001.SZ"]:
        for i, d in enumerate([date(2024, 12, 31), date(2025, 1, 2), date(2025, 1, 3)]):
            c = 10.0 + i
            s.add(DailyQuote(code=code, trade_date=d, open=c, high=c, low=c, close=c,
                             vol=100.0, amount=1.0, adj_factor=1.0, pe=None, pb=2.0))
    s.commit()

    def extra(code, dates):
        return pd.DataFrame({"np_ttm": [float(len(dates))] * len(dates)}, index=dates)

    a, b = tmp_path / "a", tmp_path / "b"
    n1 = export_market_csvs_full(s, ["300750.SZ", "000001.SZ"], date(2025, 1, 1),
                                 date(2025, 1, 31), str(a), extra_fn=extra)
    n2 = export_market_csvs_bulk(str(db), date(2025, 1, 1), date(2025, 1, 31), str(b),
                                 extra_fn=extra)
    assert n1 == n2 == 2
    for sym in ["SZ300750", "SZ000001"]:
        x = pd.read_csv(a / f"{sym}.csv")
        y = pd.read_csv(b / f"{sym}.csv")
        assert list(x.columns) == list(y.columns)
        assert len(x) == len(y) == 2                       # 2024-12-31 被 start 过滤
        pd.testing.assert_frame_equal(x, y, check_dtype=False)

from pathlib import Path
from sqlalchemy import select
from app.data.qlib_store import bars_to_dataframe
from app.backtest.symbols import to_qlib_symbol

_QLIB_INITED = False


def export_bars_csv(bars, out_dir: str):
    """把一只票的 bars 写成 qlib 符号命名的 CSV(date/o/h/l/c/volume/factor)。
    空 bars -> None。"""
    if not bars:
        return None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = bars_to_dataframe(bars)
    path = out / f"{to_qlib_symbol(bars[0].code)}.csv"
    df.to_csv(path, index=False)
    return path


def export_market_csvs(store, codes, start, end, out_dir: str) -> int:
    """逐 code 从 QuoteStore 取 bars 写 CSV。返回成功写出的只数。"""
    n = 0
    for code in codes:
        bars = store.get_bars(code, start, end)
        if export_bars_csv(bars, out_dir) is not None:
            n += 1
    return n


_FULL_COLS = ["date", "open", "high", "low", "close", "volume", "factor",
              "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
              "pe", "pb", "amount"]


def export_market_csvs_full(session, codes, start, end, out_dir: str) -> int:
    """全字段导出:直接查 DailyQuote(含换手/估值/市值/成交额,不复权),
    每只票一个 qlib 符号命名的 CSV。返回成功写出的只数。"""
    import pandas as pd
    from app.db.models import DailyQuote
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for code in codes:
        rows = session.scalars(
            select(DailyQuote).where(
                DailyQuote.code == code,
                DailyQuote.trade_date >= start,
                DailyQuote.trade_date <= end,
            ).order_by(DailyQuote.trade_date)).all()
        if not rows:
            continue
        df = pd.DataFrame([{
            "date": r.trade_date, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close, "volume": r.vol,
            "factor": r.adj_factor, "turnover_rate": r.turnover_rate,
            "volume_ratio": r.volume_ratio, "circ_mv": r.circ_mv,
            "total_mv": r.total_mv, "pe": r.pe, "pb": r.pb,
            "amount": r.amount,
        } for r in rows], columns=_FULL_COLS)
        df.to_csv(out / f"{to_qlib_symbol(code)}.csv", index=False)
        n += 1
    return n


def export_csi300_csv(pro, start, end, out_dir: str):
    """tushare index_daily(000300.SH) -> CSV(符号 SH000300, factor=1.0)。"""
    import pandas as pd
    df = pro.index_daily(ts_code="000300.SH",
                         start_date=start.strftime("%Y%m%d"),
                         end_date=end.strftime("%Y%m%d"))
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_date")
    out_df = pd.DataFrame({
        "date": pd.to_datetime(df["trade_date"]),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["vol"], "factor": 1.0})
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / "SH000300.csv"
    out_df.to_csv(path, index=False)
    return path


def build_bin(csv_dir: str, qlib_dir: str) -> None:
    """调 vendored DumpDataAll 把 CSV 目录转成 qlib bin 库。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from vendor.dump_bin import DumpDataAll
    DumpDataAll(data_path=csv_dir, qlib_dir=qlib_dir, freq="day",
                date_field_name="date").dump()


def init_qlib(qlib_dir: str) -> None:
    """qlib.init(provider_uri, region=cn)。幂等。"""
    global _QLIB_INITED
    if _QLIB_INITED:
        return
    if not Path(qlib_dir).exists():
        raise FileNotFoundError(
            f"qlib data not found at {qlib_dir}; run scripts/build_qlib_data.py first")
    import qlib
    qlib.init(provider_uri=qlib_dir, region="cn")
    _QLIB_INITED = True

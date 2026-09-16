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


def export_market_csvs_full(session, codes, start, end, out_dir: str,
                            extra_fn=None) -> int:
    """全字段导出:直接查 DailyQuote(含换手/估值/市值/成交额,不复权),
    每只票一个 qlib 符号命名的 CSV。extra_fn(code, dates) 可返回 index=dates 的
    附加列(如 PIT 财务字段),按行拼接后一并写出(dump_bin 自动成字段)。
    返回成功写出的只数。"""
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
        if extra_fn is not None:
            dates = pd.DatetimeIndex(pd.to_datetime(df["date"]))
            extra = extra_fn(code, dates)
            if extra is not None and len(extra):
                df = pd.concat([df, extra.reset_index(drop=True)], axis=1)
        df.to_csv(out / f"{to_qlib_symbol(code)}.csv", index=False)
        n += 1
    return n


def export_csi300_csv(src, start, end, out_dir: str):
    """baostock 指数日线(sh.000300) -> CSV(符号 SH000300, factor=1.0)。
    src: BaostockSource(或任何有 index_daily(bs_code, start, end) 的对象)。"""
    import pandas as pd
    try:
        df = src.index_daily("sh.000300", start, end)
    except Exception as exc:                    # noqa: BLE001 — baostock 卡死/掉线 → 腾讯兜底
        print(f"CSI300_BAOSTOCK_FAIL {exc!r}; fallback tencent", flush=True)
        df = None
    if df is None or getattr(df, "empty", True):
        from app.data import tencent_daily as tx
        rows = tx.klines("000300.SH", start, end)
        if not rows:
            return None
        df = pd.DataFrame({"date": pd.to_datetime([r[0] for r in rows]),
                           "open": [float(r[1]) for r in rows], "high": [float(r[3]) for r in rows],
                           "low": [float(r[4]) for r in rows], "close": [float(r[2]) for r in rows],
                           "volume": [float(r[5]) for r in rows]})
    out_df = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["volume"], "factor": 1.0})
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


def available_fields(qlib_dir: str) -> list[str]:
    """qlib 库中任一票的字段名列表(features/<sym>/<field>.day.bin)。空库 → []。"""
    feat = Path(qlib_dir) / "features"
    if not feat.exists():
        return []
    for d in sorted(feat.iterdir()):
        if d.is_dir():
            return sorted(f.name.split(".")[0] for f in d.iterdir() if f.name.endswith(".day.bin"))
    return []

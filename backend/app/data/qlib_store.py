from pathlib import Path
import pandas as pd
from app.data.source import DailyBar

COLUMNS = ["date", "open", "high", "low", "close", "volume", "factor"]


def bars_to_dataframe(bars: list[DailyBar]) -> pd.DataFrame:
    rows = [{
        "date": b.trade_date, "open": b.open, "high": b.high, "low": b.low,
        "close": b.close, "volume": b.volume, "factor": b.adj_factor,
    } for b in bars]
    return pd.DataFrame(rows, columns=COLUMNS)


def write_instrument_csv(bars: list[DailyBar], out_dir: str) -> Path:
    """Write one CSV per instrument for later `qlib dump_bin`."""
    assert bars, "no bars to write"
    df = bars_to_dataframe(bars)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{bars[0].code}.csv"
    df.to_csv(path, index=False)
    return path

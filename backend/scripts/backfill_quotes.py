"""全市场日线历史回填(baostock + 东财北交所)。已入库的日期跳过;
逐只拉 [start, end] 全窗口,库内已有该股的只补其最后一行之后的日期。"""
import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.baostock_source import BaostockSource


def _d(x: str) -> date:
    return date(int(x[:4]), int(x[4:6]), int(x[6:8]))


def trading_days(start: str, end: str) -> list[date]:
    src = BaostockSource()
    try:
        return src.trading_days(_d(start), _d(end))
    finally:
        src.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="20210101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    args = p.parse_args()

    engine = make_engine()
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    from scripts.daily_update_quotes import update
    update(session, _d(args.start), _d(args.end))


if __name__ == "__main__":
    main()

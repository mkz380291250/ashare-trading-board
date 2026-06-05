"""拉 tushare stock_basic 全市场 code->name 落库(幂等)。用法:python scripts/sync_stock_names.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import StockName


def sync_names(session, rows) -> int:
    rows = list(rows)
    for code, name in rows:
        existing = session.get(StockName, code)
        if existing:
            existing.name = name
        else:
            session.add(StockName(code=code, name=name))
    session.commit()
    return len(rows)


def fetch_rows(token: str):
    import tushare as ts
    pro = ts.pro_api(token)
    df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    return [(r.ts_code, r.name) for r in df.itertuples(index=False)]


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    rows = fetch_rows(s.tushare_token)
    n = sync_names(session, rows)
    print(f"SYNC_NAMES_DONE n={n}", flush=True)


if __name__ == "__main__":
    main()

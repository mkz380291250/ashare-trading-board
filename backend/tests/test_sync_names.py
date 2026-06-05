from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName
from scripts.sync_stock_names import sync_names


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_sync_names_upserts_idempotently():
    s = _sess()
    sync_names(s, [("600519.SH", "贵州茅台"), ("300285.SZ", "国瓷材料")])
    assert s.get(StockName, "600519.SH").name == "贵州茅台"
    sync_names(s, [("600519.SH", "茅台"), ("000001.SZ", "平安银行")])
    assert s.get(StockName, "600519.SH").name == "茅台"
    assert s.get(StockName, "000001.SZ").name == "平安银行"
    assert s.query(StockName).count() == 3

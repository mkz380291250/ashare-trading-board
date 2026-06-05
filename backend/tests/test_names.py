from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import StockName
from app.data.names import NameLookup


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_lookup_map_and_get():
    s = _sess()
    s.add_all([StockName(code="600519.SH", name="贵州茅台"),
               StockName(code="300285.SZ", name="国瓷材料")])
    s.commit()
    nl = NameLookup(s)
    assert nl.get("600519.SH") == "贵州茅台"
    assert nl.get("000001.SZ") == ""
    assert nl.map(["600519.SH", "300285.SZ", "x"]) == {
        "600519.SH": "贵州茅台", "300285.SZ": "国瓷材料"}
    assert nl.map([]) == {}

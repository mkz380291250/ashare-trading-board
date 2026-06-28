from datetime import date
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, EquitySnapshot
from app.trading.broker import PaperBroker
from app.data.prices import DictPriceProvider


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=1000.0)); s.commit()
    return s


def test_mark_to_market_idempotent_same_day():
    s = _sess()
    b = PaperBroker(s)
    b.mark_to_market(1, DictPriceProvider({}), date(2026, 6, 28))
    b.mark_to_market(1, DictPriceProvider({}), date(2026, 6, 28))
    n = s.scalar(select(func.count()).select_from(EquitySnapshot).where(
        EquitySnapshot.account_id == 1, EquitySnapshot.as_of == date(2026, 6, 28)))
    assert n == 1                                  # 同日只留一条

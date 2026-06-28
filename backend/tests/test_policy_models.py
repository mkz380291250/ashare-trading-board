from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import PolicyAction


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_policy_action_roundtrip():
    s = _sess()
    s.add(PolicyAction(kind="REMINE", as_of=date(2026, 6, 28),
                       trigger='{"rolling_rank_ic": 0.011}', detail="IC衰减→重挖,旧产物归档 archive/...",
                       status="AUTO", weixin_sent=False, created_at=date(2026, 6, 28)))
    s.commit()
    row = s.scalar(select(PolicyAction))
    assert row.kind == "REMINE" and row.status == "AUTO" and row.weixin_sent is False

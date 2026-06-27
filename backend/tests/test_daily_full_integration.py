# backend/tests/test_daily_full_integration.py
from pathlib import Path
import pytest
from app.config import get_settings

pytestmark = pytest.mark.integration


def _has_qlib_and_frozen() -> bool:
    s = get_settings()
    from scripts.freeze_factors import frozen_path
    return Path(s.qlib_data_dir, "calendars").exists() and frozen_path(s).exists()


@pytest.mark.skipif(not _has_qlib_and_frozen(), reason="需 qlib 数据 + frozen 产物")
def test_step_select_writes_discovery_picks():
    import scripts.daily_full as df
    from app.db.database import make_engine, make_session_factory
    from sqlalchemy import select, func
    from app.db.models import DiscoveryPick
    df.step_select()
    session = make_session_factory(make_engine())()
    n = session.scalar(select(func.count()).select_from(DiscoveryPick))
    assert n and n > 100        # 全市场全量写入

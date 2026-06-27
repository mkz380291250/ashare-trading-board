# backend/tests/test_qlib_discovery_integration.py
from datetime import date
from pathlib import Path
import pytest
from app.config import get_settings
from app.factors.frozen import load_frozen


pytestmark = pytest.mark.integration


def _has_qlib_data() -> bool:
    s = get_settings()
    return Path(s.qlib_data_dir, "calendars").exists()


@pytest.mark.skipif(not _has_qlib_data(), reason="需要本地 data/qlib_cn")
def test_load_features_returns_panel_for_frozen_factors():
    from app.backtest.qlib_data import init_qlib
    from app.discovery.qlib_provider import load_features
    from scripts.freeze_factors import frozen_path
    s = get_settings()
    init_qlib(s.qlib_data_dir)
    from qlib.data import D
    frozen = load_frozen(frozen_path(s))
    insts = D.list_instruments(D.instruments(frozen.universe), as_list=True)[:50]
    as_of = D.calendar()[-1].date()
    panel = load_features(insts, frozen.factors, as_of, lookback=40)
    assert list(panel.columns) == frozen.factors
    assert panel.index.names == ["datetime", "instrument"]
    assert len(panel) > 0

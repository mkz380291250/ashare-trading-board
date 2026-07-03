from app.config import Settings


def test_phase2_defaults():
    s = Settings()
    assert s.target_positions == 15
    assert s.quality_pctl == 0.30
    assert s.min_confidence == 0.6
    assert s.max_debate == 8


def test_discovery_universe_default_cyb():
    # 生产选股宇宙单一来源(2026-07-03 切创业板);挖掘/冻结默认跟随,防 run_remine 静默切回全市场
    assert Settings().discovery_universe == "cyb"

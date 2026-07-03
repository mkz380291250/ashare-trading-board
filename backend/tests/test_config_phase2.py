from app.config import Settings


def test_phase2_defaults():
    s = Settings()
    assert s.target_positions == 15
    assert s.quality_pctl == 0.30
    assert s.min_confidence == 0.6
    assert s.max_debate == 8

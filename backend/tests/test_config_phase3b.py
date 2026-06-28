from app.config import Settings


def test_phase3b_defaults():
    s = Settings()
    assert s.policy_auto_remine is True
    assert s.ic_decay_window == 20 and s.ic_decay_consecutive == 5
    assert s.ic_decay_threshold == 0.02
    assert s.dd_stop == 0.20 and s.hitrate_stop == 0.40
    assert s.weak_pctl == 0.50 and s.weak_consecutive == 3

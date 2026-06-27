from app.decision.selection import select_debate_candidates


def _ranking(n):
    # 降序排名:c0 最高 ... c{n-1} 最低
    return [(f"c{i}", float(n - i)) for i in range(n)]


def test_fills_slots_from_top_excluding_held():
    r = _ranking(100)
    out = select_debate_candidates(r, held=set(), target=3, quality_pctl=0.30, max_debate=32)
    assert out == ["c0", "c1", "c2"]          # 空仓→填满3个空位,取最强3只


def test_holdings_always_debated_and_consume_target():
    r = _ranking(100)
    out = select_debate_candidates(r, held={"c50"}, target=3, quality_pctl=0.30, max_debate=32)
    # 持仓 c50 必辩;空位=3-1=2,买入候选取 c0,c1
    assert out[0] == "c50"
    assert set(out) == {"c50", "c0", "c1"}


def test_quality_floor_stops_buys():
    r = _ranking(10)                          # 前30% = 前3名(index 0,1,2)
    out = select_debate_candidates(r, held=set(), target=8, quality_pctl=0.30, max_debate=32)
    assert out == ["c0", "c1", "c2"]          # 想填8个,但只有前3只过质量门


def test_skip_excludes_already_decided():
    r = _ranking(100)
    out = select_debate_candidates(r, held={"c50"}, target=3, quality_pctl=0.30,
                                   max_debate=32, skip={"c50", "c0"})
    # c50 被 skip 不辩;c0 被 skip 跳过;空位=3-1=2 → c1,c2
    assert "c50" not in out and "c0" not in out
    assert out == ["c1", "c2"]


def test_max_debate_caps_total():
    r = _ranking(100)
    out = select_debate_candidates(r, held=set(), target=50, quality_pctl=1.0, max_debate=5)
    assert len(out) == 5


def test_held_not_in_ranking_still_debated():
    r = _ranking(10)
    out = select_debate_candidates(r, held={"DELISTED.SH"}, target=1, quality_pctl=0.30,
                                   max_debate=32)
    assert "DELISTED.SH" in out               # 持仓不在排名里也要辩(可能要卖)

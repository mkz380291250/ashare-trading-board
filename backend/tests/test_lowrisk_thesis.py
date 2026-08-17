def test_lowrisk_thesis_text_and_none():
    import scripts.daily_full as df
    assert df._lowrisk_thesis([10.0]) is None            # 数据不足
    txt = df._lowrisk_thesis([10.0, 10.1, 9.9, 10.0, 10.05, 10.02])
    assert txt is not None
    assert "低风险" in txt or "低波动" in txt
    assert "超跌反弹" not in txt


def test_agents_prompts_switched_to_lowrisk():
    from app.decision.agents import ROLES
    blob = "".join(ROLES.values())
    assert "超跌反弹" not in blob                          # 旧口径清干净
    assert "低波动" in blob or "低风险" in blob            # 新口径已注入

from app.decision.brief import StockBrief, build_brief


def test_build_brief_assembles_prompt():
    brief = build_brief(
        code="600519.SH",
        recent_closes=[1000.0, 1010.0, 1050.0],
        factors={"mom_5d": 0.05, "turnover": 2.0, "vol_ratio": 1.8, "breakout": 0.99},
        fundamentals={"np_yoy": 25.0, "rev_yoy": 12.0, "pe": 30.0, "pb": 9.0},
        holding={"shares": 100, "cost": 980.0},
    )
    assert isinstance(brief, StockBrief)
    p = brief.to_prompt()
    assert "600519.SH" in p
    assert "mom_5d" in p and "0.05" in p
    assert "np_yoy" in p and "25" in p
    assert "持仓" in p and "100" in p


def test_brief_no_holding():
    brief = build_brief("X", [1.0], {}, {}, holding=None)
    assert "无持仓" in brief.to_prompt()


def test_brief_renders_research_section():
    b = build_brief("X", [10.0, 11.0], {}, {},
                    holding=None,
                    research={"sentiment": 0.6, "rating_consensus": "买入",
                              "summary": "机构看多"})
    p = b.to_prompt()
    assert "研报" in p and "机构看多" in p and "0.6" in p


def test_brief_research_absent_says_no_data():
    b = build_brief("X", [10.0], {}, {}, holding=None)
    assert "无研报数据" in b.to_prompt()


def test_brief_renders_financials_section():
    b = build_brief("X", [10.0], {}, {}, holding=None,
                    financials={"营收_亿": 5.0, "ROE": 2.59, "现金流净利比": 2.99})
    p = b.to_prompt()
    assert "财报数据" in p and "营收_亿" in p and "现金流净利比" in p


def test_brief_financials_absent_says_no():
    assert "财报数据: 无" in build_brief("X", [10.0], {}, {}, holding=None).to_prompt()


def test_brief_renders_strategy_thesis_when_present():
    b = build_brief("X", [10.0, 9.0, 8.0], {}, {}, holding=None,
                    strategy="短周期反转:超跌反弹候选,评估反弹胜算")
    p = b.to_prompt()
    assert "选股逻辑" in p and "短周期反转" in p and "反弹胜算" in p


def test_brief_strategy_absent_omits_line():
    p = build_brief("X", [10.0], {}, {}, holding=None).to_prompt()
    assert "选股逻辑" not in p


def test_brief_renders_volume_series():
    b = build_brief("X", [10.0, 9.5, 9.0], {}, {}, holding=None,
                    recent_volumes=[10000.0, 8000.0, 3000.0])
    p = b.to_prompt()
    assert "近期成交量序列" in p and "3000" in p


def test_brief_volumes_absent_says_missing():
    p = build_brief("X", [10.0], {}, {}, holding=None).to_prompt()
    assert "近期成交量序列: 无" in p

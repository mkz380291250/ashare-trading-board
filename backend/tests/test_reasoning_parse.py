from app.decision.reasoning_parse import parse_reasoning

SAMPLE = (
    "### 量价分析师\n动量强,放量突破。\n```json {\"stance\":\"bull\",\"confidence\":0.7} ```\n\n"
    "### 空头研究员\n高位接盘风险。\n```json {\"stance\":\"bear\",\"confidence\":0.6} ```\n\n"
    "### 风控经理\n空仓观望,不接刀。\n```json {\"action\":\"HOLD\",\"confidence\":0.62,\"shares\":0} ```"
)


def test_splits_each_role_in_order():
    vps = parse_reasoning(SAMPLE)
    assert [v.role for v in vps] == ["量价分析师", "空头研究员", "风控经理"]


def test_extracts_stance_and_strips_json_fence():
    v = parse_reasoning(SAMPLE)[0]
    assert v.stance == "bull"
    assert v.confidence == 0.7
    assert v.stage == "analyst"
    assert "json" not in v.text and v.text == "动量强,放量突破。"


def test_verdict_role_has_action_and_stage():
    v = parse_reasoning(SAMPLE)[2]
    assert v.action == "HOLD"
    assert v.stage == "verdict"
    assert v.stance is None


def test_missing_or_broken_json_is_tolerated():
    txt = "### 交易员\n没有结尾json的发言\n\n### 多头研究员\n坏的\n```json {不是json} ```"
    vps = parse_reasoning(txt)
    assert vps[0].action is None and vps[0].text == "没有结尾json的发言"
    assert vps[0].stage == "trader"
    assert vps[1].stance is None
    assert vps[1].stage == "debate"


def test_multi_round_debate_keeps_duplicates_in_order():
    txt = ("### 多头研究员\n第一轮多\n```json {\"stance\":\"bull\",\"confidence\":0.5} ```\n\n"
           "### 空头研究员\n第一轮空\n```json {\"stance\":\"bear\",\"confidence\":0.5} ```\n\n"
           "### 多头研究员\n第二轮多\n```json {\"stance\":\"bull\",\"confidence\":0.6} ```")
    roles = [v.role for v in parse_reasoning(txt)]
    assert roles == ["多头研究员", "空头研究员", "多头研究员"]


def test_empty_returns_empty_list():
    assert parse_reasoning("") == []
    assert parse_reasoning("   ") == []


def test_unknown_role_maps_to_other():
    assert parse_reasoning("### 某个新角色\n内容")[0].stage == "other"

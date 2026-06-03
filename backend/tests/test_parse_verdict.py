from app.decision.llm import parse_verdict


def test_extracts_last_fenced_json():
    text = ('分析... ```json\n{"action": "SELL", "confidence": 0.3}\n```\n'
            '结论 ```json\n{"action": "BUY", "confidence": 0.8, "shares": 50}\n```')
    v = parse_verdict(text)
    assert v == {"action": "BUY", "confidence": 0.8, "shares": 50}


def test_bare_json_object():
    assert parse_verdict('blah {"stance": "bull", "confidence": 0.6} end') == \
        {"stance": "bull", "confidence": 0.6}


def test_missing_or_invalid_returns_empty():
    assert parse_verdict("no json here") == {}
    assert parse_verdict("broken {not json}") == {}

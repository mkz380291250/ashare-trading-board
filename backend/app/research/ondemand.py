"""辩论时按需取研报:缓存够新就用缓存,否则当场抓取(tushare 评级 + 东财新闻)
→ LLM 摘要 → 落库并返回。抓取失败回退旧缓存,再不行返回 None。
保证辩论的「新闻研报分析师」尽量有数据,不出现凭空缺失。"""
from datetime import date


def _to_dict(note) -> dict:
    return {"sentiment": note.sentiment,
            "rating_consensus": note.rating_consensus,
            "summary": note.summary}


def research_note_for(code, as_of: date, source, analyzer, store,
                      max_age_days: int = 3) -> dict | None:
    cached = store.latest(code)
    if cached is not None and 0 <= (as_of - cached.as_of).days <= max_age_days:
        return _to_dict(cached)
    try:
        items = source.fetch(code, as_of)
        note = analyzer.analyze(code, items)
        src = getattr(items[0], "source", "live") if items else "none"
        store.upsert(code, as_of, note, src)
        return _to_dict(note)
    except Exception:
        return _to_dict(cached) if cached is not None else None

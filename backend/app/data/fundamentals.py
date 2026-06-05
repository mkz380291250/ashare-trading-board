"""组装决策 brief 的「基本面」dict:行情面(pe/pb/市值/换手,来自 daily_quotes)
+ 成长面(净利/营收同比,来自 tushare fina_indicator 经 EarningsSource)。
取不到的部分缺省略,绝不抛错。"""
from sqlalchemy import select
from app.db.models import DailyQuote


def build_fundamentals(session, code, as_of, earnings=None) -> dict:
    out: dict = {}
    dq = session.scalars(
        select(DailyQuote)
        .where(DailyQuote.code == code, DailyQuote.trade_date <= as_of)
        .order_by(DailyQuote.trade_date.desc())
        .limit(1)
    ).first()
    if dq is not None:
        if dq.pe is not None:
            out["pe"] = round(dq.pe, 2)
        if dq.pb is not None:
            out["pb"] = round(dq.pb, 2)
        if dq.total_mv is not None:
            out["total_mv_亿"] = round(dq.total_mv / 10000, 1)  # 万 -> 亿
        if dq.turnover_rate is not None:
            out["turnover"] = round(dq.turnover_rate, 2)
    if earnings is not None:
        try:
            e = earnings.latest(code)
            if e is not None:
                out["np_yoy"] = round(e.np_yoy, 2)
                out["rev_yoy"] = round(e.rev_yoy, 2)
        except Exception:
            pass  # 增速取不到不影响行情面
    return out

"""创业板指迟滞趋势闸(2026-09-24 自研策略落地,研究见 docs/reports/regime_strategy_2026-09-24.md)。

规则:指数收盘 < MA(ma)×(1−band) → 闸关(清仓持现金,不买);收盘 > MA×(1+band) → 闸开
(当晚按因子分买回);介于其间沿用上一状态。无历史状态时按 收盘>MA 初始化。
状态持久化在 PolicyAction(kind GATE_ON / GATE_OFF,只在切换时记一条)。"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.db.models import PolicyAction

KIND_ON, KIND_OFF = "GATE_ON", "GATE_OFF"


@dataclass(frozen=True)
class GateEval:
    on: bool
    prev_on: bool | None
    close: float
    ma: float
    ratio: float          # close/ma − 1
    as_of: date
    stale: bool = False   # 指数数据未覆盖 as_of,沿用上一状态

    @property
    def changed(self) -> bool:
        return self.prev_on is not None and self.on != self.prev_on

    def summary(self) -> str:
        st = "开" if self.on else "关"
        chg = ("→切换" if self.changed else "")
        return (f"闸{st}{chg} 收盘 {self.close:.2f} MA {self.ma:.2f} 偏离 {self.ratio:+.2%}"
                + (" (指数数据滞后,沿用)" if self.stale else ""))


def evaluate(closes: pd.Series, as_of: date, *, ma: int, band: float,
             prev_on: bool | None) -> GateEval:
    """closes: 日期索引的指数收盘(升序,含 as_of 或更早)。"""
    closes = closes.dropna().sort_index()
    upto = closes[closes.index <= pd.Timestamp(as_of)]
    if len(upto) < ma:
        raise ValueError(f"trend gate: 指数数据不足 {ma} 天")
    last_dt = upto.index[-1].date()
    stale = last_dt < as_of
    close = float(upto.iloc[-1])
    ma_v = float(upto.iloc[-ma:].mean())
    ratio = close / ma_v - 1.0
    if stale and prev_on is not None:
        on = prev_on
    elif prev_on is None:
        on = close > ma_v
    elif prev_on and ratio < -band:
        on = False
    elif (not prev_on) and ratio > band:
        on = True
    else:
        on = prev_on
    return GateEval(on=on, prev_on=prev_on, close=close, ma=ma_v, ratio=ratio,
                    as_of=as_of, stale=stale)


def load_prev_state(session, before: date | None = None) -> bool | None:
    """最近一次 GATE_ON/GATE_OFF 记录 → 状态;无记录 → None。before 给了只看更早的。"""
    q = select(PolicyAction).where(PolicyAction.kind.in_([KIND_ON, KIND_OFF]))
    if before is not None:
        q = q.where(PolicyAction.as_of < before)
    row = session.scalars(q.order_by(PolicyAction.as_of.desc(), PolicyAction.id.desc())).first()
    if row is None:
        return None
    return row.kind == KIND_ON


def liquidate_all(session, broker, positions, price_of, as_of, account_id=1) -> list[str]:
    """闸关:按最新收盘卖出全部持仓。返回卖出代码;无价/失败的跳过(留到下一晚)。"""
    sold = []
    for p in positions:
        if p.shares <= 0:
            continue
        px = price_of(p.code)
        if not px or px <= 0:
            print(f"GATE_SELL_SKIP {p.code}: 无价格", flush=True)
            continue
        try:
            broker.sell(account_id, p.code, px, p.shares, as_of)
            sold.append(p.code)
        except Exception as exc:                    # noqa: BLE001
            print(f"GATE_SELL_SKIP {p.code}: {exc!r}", flush=True)
    session.commit()
    return sold

"""当日纯文本摘要(供 weixin 日报)。不用 markdown 表格,短句陈述。"""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Account, Position, Trade, EquitySnapshot


def build_daily_summary(session: Session, as_of: date, account_id: int = 1) -> str:
    trades = session.scalars(select(Trade).where(
        Trade.account_id == account_id, Trade.traded_at == as_of)).all()
    buys = [t for t in trades if t.side == "BUY"]
    sells = [t for t in trades if t.side == "SELL"]
    positions = session.scalars(select(Position).where(
        Position.account_id == account_id)).all()
    acc = session.get(Account, account_id)
    snaps = session.scalars(select(EquitySnapshot).where(
        EquitySnapshot.account_id == account_id).order_by(EquitySnapshot.as_of)).all()

    lines = [f"📊 {as_of} 交易日报"]
    if buys:
        lines.append("买入:" + " ".join(f"{t.code}×{t.shares}" for t in buys))
    if sells:
        lines.append("卖出:" + " ".join(f"{t.code}×{t.shares}" for t in sells))
    if not buys and not sells:
        lines.append("今日无成交")
    lines.append(f"持仓 {len(positions)} 只")
    if snaps:
        cur = snaps[-1]
        peak = max(x.total for x in snaps)
        dd = (cur.total / peak - 1.0) if peak else 0.0
        lines.append(f"现金 {acc.cash:.0f} / 市值 {cur.market_value:.0f} / "
                     f"总权益 {cur.total:.0f}")
        lines.append(f"回撤 {dd*100:.1f}%")
    else:
        lines.append(f"现金 {acc.cash:.0f} / 权益快照 N/A / 回撤 N/A")
    return "\n".join(lines)

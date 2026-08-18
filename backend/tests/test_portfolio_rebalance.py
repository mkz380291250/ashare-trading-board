from datetime import date
from app.portfolio.rebalance import (
    is_rebalance_day, plan_rebalance, equal_weight_shares)


def test_is_rebalance_day():
    assert is_rebalance_day(date(2026, 8, 17), 0) is True    # 周一
    assert is_rebalance_day(date(2026, 8, 18), 0) is False   # 周二
    assert is_rebalance_day(date(2026, 8, 18), 1) is True    # 配周二


def _ranked(n):
    return [(f"3000{i:02d}.SZ", i + 1) for i in range(n)]     # rank 从 1


def test_plan_empty_holdings_buys_topk_plus_buffer_candidates():
    sells, buys = plan_rebalance(_ranked(30), set(), topk=15, buffer=5)
    assert sells == []
    # 空位=15,候选给 slots+buffer=20 个,按 rank 升序
    assert buys == [f"3000{i:02d}.SZ" for i in range(20)]


def test_plan_all_held_in_topk_no_action():
    held = {f"3000{i:02d}.SZ" for i in range(15)}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert sells == []
    assert buys == []                                        # 无空位


def test_plan_holding_dropped_out_of_buffer_is_sold_and_refilled():
    # 持仓 300021(rank 22 > 15+5)应卖;空出 1 位,买 rank 最高的未持仓
    held = {f"3000{i:02d}.SZ" for i in range(14)} | {"300021.SZ"}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert sells == ["300021.SZ"]
    assert buys[0] == "300014.SZ"                            # rank15,第一个未持仓
    assert len(buys) == 1 + 5                                # slots=1 +buffer


def test_plan_holding_within_buffer_not_sold():
    held = {"300017.SZ"}                                     # rank 18,在 15+5 内
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert "300017.SZ" not in sells


def test_plan_delisted_holding_sold():
    held = {"999999.SZ"}                                     # 不在 ranked
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5)
    assert sells == ["999999.SZ"]


def test_equal_weight_shares():
    # 100万/15/10元=6666.7 -> 整百 6600
    assert equal_weight_shares(1_000_000, 15, 10.0) == 6600
    assert equal_weight_shares(1_000_000, 15, 999999.0) == 0  # 买不起1手
    assert equal_weight_shares(1_000_000, 15, 0.0) == 0       # 价非法
    assert equal_weight_shares(0.0, 15, 10.0) == 0

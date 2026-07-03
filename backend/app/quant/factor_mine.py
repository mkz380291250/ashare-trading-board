"""因子挖掘与有效性验证。

构造一批公式因子(qlib 表达式),用 D.features 计算,逐因子算样本内/样本外
RankIC,两窗同号且都达标才判「稳健有效」(防 40 选优的多重检验过拟合)。
"""

# 公式因子库:name -> qlib 表达式。覆盖动量/反转/波动/量能/量价相关/价位/
# 日内/趋势/流动性/分布/极值 等家族 × 多窗口。标注 ★ 的是 Alpha158 没有或
# 口径不同的「新构造」(挖掘重点)。
FACTOR_LIBRARY: dict[str, str] = {
    # 动量
    "mom5":  "$close/Ref($close,5)-1",
    "mom10": "$close/Ref($close,10)-1",
    "mom20": "$close/Ref($close,20)-1",
    "mom60": "$close/Ref($close,60)-1",
    # 短期反转(1-close/Ref 等价于 -(动量),避免一元负号)
    "rev1": "1-$close/Ref($close,1)",
    "rev3": "1-$close/Ref($close,3)",
    "rev5": "1-$close/Ref($close,5)",
    # 波动
    "vol10": "Std($close/Ref($close,1)-1,10)",
    "vol20": "Std($close/Ref($close,1)-1,20)",
    "vol60": "Std($close/Ref($close,1)-1,60)",
    # ★ 波动调整动量(信息比式)
    "sharpe20": "Mean($close/Ref($close,1)-1,20)/(Std($close/Ref($close,1)-1,20)+1e-12)",
    "sharpe60": "Mean($close/Ref($close,1)-1,60)/(Std($close/Ref($close,1)-1,60)+1e-12)",
    # 量能
    "vmom": "Mean($volume,5)/(Mean($volume,20)+1)",
    "turn_chg": "$volume/(Mean($volume,20)+1)",
    "vstd20": "Std($volume,20)/(Mean($volume,20)+1)",
    # 量价相关
    "corr_pv10": "Corr($close,Log($volume+1),10)",
    "corr_pv20": "Corr($close,Log($volume+1),20)",
    # ★ 收益-量相关
    "corr_rv10": "Corr($close/Ref($close,1)-1,Log($volume+1),10)",
    # 价位(区间位置)
    "pos20": "($close-Min($low,20))/(Max($high,20)-Min($low,20)+1e-12)",
    "pos60": "($close-Min($low,60))/(Max($high,60)-Min($low,60)+1e-12)",
    # ★ 日内
    "intra_ret": "($close-$open)/($open+1e-12)",
    "intra_range": "($high-$low)/($close+1e-12)",
    "intra_pos": "($close-$low)/($high-$low+1e-12)",
    "gap": "($open-Ref($close,1))/(Ref($close,1)+1e-12)",
    "mean_intra20": "Mean(($close-$open)/($open+1e-12),20)",
    # 趋势
    "slope20": "Slope($close,20)/(Mean($close,20)+1e-12)",
    "rsqr20": "Rsquare($close,20)",
    # ★ 距均线
    "ma_dist20": "$close/(Mean($close,20)+1e-12)-1",
    "ma_dist60": "$close/(Mean($close,60)+1e-12)-1",
    # ★ 流动性(Amihud 非流动性)
    "amihud20": "Mean(Abs($close/Ref($close,1)-1)/($volume*$close+1),20)",
    # 分布
    "skew20": "Skew($close/Ref($close,1)-1,20)",
    "kurt20": "Kurt($close/Ref($close,1)-1,20)",
    # ★ 极值(彩票/MAX 效应)
    "maxret20": "Max($close/Ref($close,1)-1,20)",
    "minret20": "Min($close/Ref($close,1)-1,20)",
    # ★ 量加权波动
    "wvma20": "Std(Abs($close/Ref($close,1)-1)*$volume,20)/(Mean(Abs($close/Ref($close,1)-1)*$volume,20)+1e-12)",
    # ★ 类 RSI(上涨动能占比)
    "up_ratio14": "Mean(Greater($close-Ref($close,1),0)*($close-Ref($close,1)),14)/(Mean(Abs($close-Ref($close,1)),14)+1e-12)",
    # ★★ 风格因子(2026-07-03,依赖全字段 qlib 数据:turnover_rate/pe/pb/circ_mv/amount/volume_ratio)
    # 市值
    "ln_mv": "Log($circ_mv+1)",
    "mv_chg20": "$circ_mv/(Ref($circ_mv,20)+1e-12)-1",
    # 估值(EP=1/PE:PE负→EP负天然有序;null→NaN 由 dropna 跳过)
    "ep": "1/($pe+1e-12)",
    "bp": "1/($pb+1e-12)",
    # 换手
    "turn5": "Mean($turnover_rate,5)",
    "turn20": "Mean($turnover_rate,20)",
    "turn_chg5_20": "Mean($turnover_rate,5)/(Mean($turnover_rate,20)+1e-12)",
    "turn_std20": "Std($turnover_rate,20)/(Mean($turnover_rate,20)+1e-12)",
    # 流动性(真实成交额版 Amihud)
    "amihud_amt20": "Mean(Abs($close/Ref($close,1)-1)/($amount+1),20)",
    "amt5_20": "Mean($amount,5)/(Mean($amount,20)+1)",
    # 量比
    "vr5": "Mean($volume_ratio,5)",
    "vr_chg": "$volume_ratio/(Mean($volume_ratio,20)+1e-12)",
}

STYLE_FACTORS = frozenset({
    "ln_mv", "mv_chg20", "ep", "bp", "turn5", "turn20", "turn_chg5_20",
    "turn_std20", "amihud_amt20", "amt5_20", "vr5", "vr_chg"})

# 标签:T+1 买、T+1+h 卖的 h 日远期收益
def label_expr(horizon: int = 5) -> str:
    return f"Ref($close,-{horizon + 1})/Ref($close,-1)-1"


def to_datetime_instrument(df):
    """D.features 返回 (instrument, datetime);换成 factor_report 要的
    (datetime, instrument) 并排序。"""
    return df.reorder_levels(["datetime", "instrument"]).sort_index()


def rank_by_abs_ir(results: list[dict], key: str = "rank_ic_ir_oos") -> list[dict]:
    """按某 IR 字段的绝对值降序(反向因子也算强)。"""
    return sorted(results, key=lambda r: -abs(r.get(key) or 0.0))


def is_robust(r: dict, *, ic_min: float = 0.02, ir_min: float = 0.3) -> bool:
    """稳健有效判定:样本内/外 RankIC 同号,且样本外 |RankIC|、|IR| 双双达标。"""
    ic_is = r.get("rank_ic_is") or 0.0
    ic_oos = r.get("rank_ic_oos") or 0.0
    ir_oos = r.get("rank_ic_ir_oos") or 0.0
    same_sign = (ic_is > 0 and ic_oos > 0) or (ic_is < 0 and ic_oos < 0)
    return same_sign and abs(ic_oos) >= ic_min and abs(ir_oos) >= ir_min

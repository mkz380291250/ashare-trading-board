"""ML 因子流水线:Alpha158 因子 -> 自定义周期标签 -> LightGBM 拟合/预测。

qlib 负责:Alpha158 因子计算、数据集切分、回测(见 app/backtest)。
模型用 lightgbm 原生 API,便于按因子子集重训、对比选最优组合。
"""
from datetime import date

# 默认 LightGBM 参数(回归 mse;小而稳,适合截面预测)
DEFAULT_LGB_PARAMS = {
    "objective": "mse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": 8,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 1.0,
    "lambda_l2": 1.0,
    "verbosity": -1,
}


def cs_zscore(data):
    """按日截面标准化(z-score)。data 为 MultiIndex(datetime,instrument) 的
    Series 或 DataFrame。零方差/缺失日置 0。trees 对单因子单调变换不敏感,但截面
    标准化让同日跨股票可比、跨期一致,且把标签变成相对排序目标(提升 RankIC)。"""
    import numpy as np
    g = data.groupby(level="datetime")
    z = (data - g.transform("mean")) / g.transform("std")
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def label_expr(horizon: int):
    """未来 horizon 日收益标签:T+1 买入、T+1+horizon 卖出。
    返回 (exprs, names),供覆写 Alpha158.get_label_config。"""
    return [f"Ref($close, -{horizon + 1})/Ref($close, -1) - 1"], ["LABEL0"]


def make_segments(train, valid, test) -> dict:
    """校验 train<valid<test 不重叠且有序,返回 qlib segments dict。
    每段为 (start, end)。"""
    segs = [("train", train), ("valid", valid), ("test", test)]
    for (n1, (_s1, e1)), (n2, (s2, _e2)) in zip(segs, segs[1:]):
        if not (e1 < s2):
            raise ValueError(
                f"segment {n1} end {e1} must precede {n2} start {s2}")
    return {n: list(v) for n, v in segs}


def make_handler(instruments: str, start: date, end: date,
                 fit_start: date, fit_end: date, horizon: int):
    """Alpha158 handler,标签周期改为 horizon 日。需先 init_qlib()。"""
    from qlib.contrib.data.handler import Alpha158
    exprs, names = label_expr(horizon)

    class _Alpha158H(Alpha158):
        def get_label_config(self):
            return exprs, names

    return _Alpha158H(instruments=instruments, start_time=start, end_time=end,
                      fit_start_time=fit_start, fit_end_time=fit_end)


def make_dataset(handler, segments: dict):
    """DatasetH 包装 handler + 时间切分。"""
    from qlib.data.dataset import DatasetH
    return DatasetH(handler, segments=segments)


def prepare_xy(dataset, segment: str):
    """取某段的 (特征 DataFrame, 标签 Series)。标签列展平为 Series。"""
    feat = dataset.prepare(segment, col_set="feature")
    label = dataset.prepare(segment, col_set="label")
    y = label.iloc[:, 0]
    y.name = "label"
    return feat, y


def train_lgb(x_train, y_train, x_valid, y_valid, *, feats=None,
              params=None, num_boost_round=1000, early_stopping=50):
    """在(可选)因子子集上训练 lightgbm。丢弃标签为 NaN 的样本。返回 booster。"""
    import lightgbm as lgb
    cols = feats if feats is not None else list(x_train.columns)
    tr = _dropna_y(x_train[cols], y_train)
    va = _dropna_y(x_valid[cols], y_valid)
    dtrain = lgb.Dataset(tr[0], label=tr[1])
    dvalid = lgb.Dataset(va[0], label=va[1], reference=dtrain)
    return lgb.train(
        params or DEFAULT_LGB_PARAMS, dtrain,
        num_boost_round=num_boost_round, valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(early_stopping, verbose=False),
                   lgb.log_evaluation(0)])


def predict_scores(booster, x, feats=None):
    """用 booster 在 x 上预测,返回 'score' 列的 DataFrame(保留 MultiIndex)。"""
    import pandas as pd
    cols = feats if feats is not None else list(booster.feature_name())
    pred = booster.predict(x[cols])
    return pd.DataFrame({"score": pred}, index=x.index)


def feature_importance(booster) -> dict:
    """因子重要性(gain)字典 {因子名: 重要性}。"""
    names = booster.feature_name()
    gains = booster.feature_importance(importance_type="gain")
    return {n: float(g) for n, g in zip(names, gains)}


def _dropna_y(x, y):
    mask = y.notna()
    return x[mask], y[mask]

import pandas as pd


def build_forward_returns(dates, codes, adj_close_fn) -> pd.Series:
    """次日复权收益:adj_close(d+1)/adj_close(d)-1,按 (datetime, instrument)。
    dates 升序;最后一天无次日,跳过。缺价(None)跳过该 (d,code)。"""
    dates = sorted(dates)
    out = {}
    for i in range(len(dates) - 1):
        d, nxt = dates[i], dates[i + 1]
        for c in codes:
            p0 = adj_close_fn(d, c)
            p1 = adj_close_fn(nxt, c)
            if p0 and p1 and p0 != 0:
                out[(pd.Timestamp(d), c)] = p1 / p0 - 1.0
    idx = pd.MultiIndex.from_tuples(list(out) or [],
                                    names=["datetime", "instrument"])
    return pd.Series(list(out.values()), index=idx, dtype="float64")


def factor_report(score_frame: pd.DataFrame, fwd_returns: pd.Series,
                  layers: int = 5) -> dict:
    """按日截面算 IC(Pearson)/RankIC(Spearman) 及其 IR,并分 N 层均收益。"""
    s = score_frame["score"]
    joined = pd.DataFrame({"score": s, "ret": fwd_returns}).dropna()
    ics, rics = [], []
    for _, g in joined.groupby(level="datetime"):
        if len(g) < 2 or g["score"].nunique() < 2 or g["ret"].nunique() < 2:
            continue
        ics.append(g["score"].corr(g["ret"]))
        rics.append(g["score"].corr(g["ret"], method="spearman"))
    layer_means = _layer_returns(joined, layers)
    n = len(ics)
    ic = pd.Series(ics)
    ric = pd.Series(rics)
    return {
        "days": n,
        "ic_mean": float(ic.mean()) if n else 0.0,
        "ic_ir": float(ic.mean() / ic.std()) if n > 1 and ic.std() else 0.0,
        "rank_ic_mean": float(ric.mean()) if n else 0.0,
        "rank_ic_ir": float(ric.mean() / ric.std()) if n > 1 and ric.std() else 0.0,
        "layer_returns": layer_means,
    }


def _layer_returns(joined: pd.DataFrame, layers: int) -> list:
    """每日按 score 分 layers 层(0=最低分),返回各层跨日平均前向收益。"""
    buckets = {i: [] for i in range(layers)}
    for _, g in joined.groupby(level="datetime"):
        if len(g) < layers:
            continue
        ranks = g["score"].rank(method="first")
        lab = ((ranks - 1) / len(g) * layers).astype(int).clip(0, layers - 1)
        for lyr, sub in g["ret"].groupby(lab):
            buckets[int(lyr)].append(sub.mean())
    return [float(pd.Series(v).mean()) if v else 0.0
            for i, v in sorted(buckets.items())]

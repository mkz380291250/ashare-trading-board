"""Point-in-time(PIT)附加字段:从 tushare_extra.db 的季频四表/分红/资金流
生成每只票「每交易日一行」的研究字段,供 qlib 研究库导出 merge。

对齐规则:交易日 d 可用的财报 = ann_date<=d 中 ann_date 最新的一份(同 ann_date
取 end_date 最新);向前填充;公告前 NaN。序列派生(单季/TTM/SUE)按每个报告期
「首次公告」的数值算(后续重述不回填,保守 PIT)。任何表缺失 → 对应列全 NaN,不抛错。
单位:金额 元;比率 %;资金流 万元。"""
import sqlite3

import numpy as np
import pandas as pd

Q_ENDS = ("0331", "0630", "0930", "1231")

QUARTERLY_COLS = ["np_ttm", "rev_ttm", "ocf_ttm", "sue", "q_roe", "gm",
                  "q_sales_yoy", "q_profit_yoy", "profit_acc", "accrual",
                  "debt_to_assets", "total_assets"]
PIT_COLS = QUARTERLY_COLS + ["ann_age", "dps_ttm", "mf_lg_net", "mf_sm_net", "mf_net"]


def _first_per_end(df: pd.DataFrame) -> pd.DataFrame:
    """同 end_date 多份(重述)只留 ann_date 最早的一份,按 end_date 升序。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(df.columns) if df is not None else [])
    d = df.dropna(subset=["end_date"]).copy()
    d["end_date"] = d["end_date"].astype(str)
    d["ann_date"] = d["ann_date"].fillna(d["end_date"]).astype(str)
    d = d.sort_values(["end_date", "ann_date"]).drop_duplicates("end_date", keep="first")
    return d.reset_index(drop=True)


def _next_q(end: str) -> str:
    yr, md = int(end[:4]), end[4:]
    k = Q_ENDS.index(md)
    return f"{yr}{Q_ENDS[k + 1]}" if k < 3 else f"{yr + 1}{Q_ENDS[0]}"


def _single_quarter(ytd: pd.Series, end_dates: pd.Series) -> pd.Series:
    """ytd 累计 → 单季:Q1 = 自身;其余 = 本期 − 上一期(上一期须是同年前一季,否则 NaN)。"""
    out = []
    prev_end, prev_val = None, np.nan
    for e, v in zip(end_dates, ytd):
        md = e[4:]
        if md not in Q_ENDS:
            out.append(np.nan)
        elif md == "0331":
            out.append(v)
        else:
            want = e[:4] + Q_ENDS[Q_ENDS.index(md) - 1]
            out.append(v - prev_val if prev_end == want else np.nan)
        prev_end, prev_val = e, v
    return pd.Series(out, index=ytd.index, dtype="float64")


def _ttm(single: pd.Series, end_dates: pd.Series) -> pd.Series:
    """最近 4 个连续单季之和;不连续/不足/含 NaN → NaN。"""
    ends = list(end_dates)
    vals = single.to_numpy(dtype="float64")
    out = np.full(len(vals), np.nan)
    for i in range(3, len(vals)):
        window = vals[i - 3:i + 1]
        if np.isnan(window).any():
            continue
        if all(ends[j][4:] in Q_ENDS and _next_q(ends[j]) == ends[j + 1] for j in range(i - 3, i)):
            out[i] = window.sum()
    return pd.Series(out, index=single.index, dtype="float64")


def _sue(single: pd.Series, end_dates: pd.Series) -> pd.Series:
    """(q_t − q_{t−4}) / std(此前 8 个 yoy 差,不含当期)。同季匹配按 end_date 字符串。"""
    by_end = dict(zip(end_dates, single))
    diffs = []
    for e, v in zip(end_dates, single):
        prev = by_end.get(f"{int(e[:4]) - 1}{e[4:]}", np.nan)
        diffs.append(v - prev)
    d = pd.Series(diffs, index=single.index, dtype="float64")
    hist_std = d.shift(1).rolling(8, min_periods=8).std()
    return d / hist_std.replace(0.0, np.nan)


def _yoy_pct(single: pd.Series, end_dates: pd.Series) -> pd.Series:
    """单季同比 %:(q_t − q_{t−4}) / |q_{t−4}| × 100;去年同季缺失或为 0 → NaN。"""
    by_end = dict(zip(end_dates, single))
    out = []
    for e, v in zip(end_dates, single):
        prev = by_end.get(f"{int(e[:4]) - 1}{e[4:]}", np.nan)
        out.append((v - prev) / abs(prev) * 100.0 if pd.notna(prev) and prev != 0 else np.nan)
    return pd.Series(out, index=single.index, dtype="float64")


def _ann(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["end_date", "ann_date"])
    d = df[["end_date", "ann_date"]].dropna().copy()
    d["end_date"] = d["end_date"].astype(str)
    d["ann_date"] = d["ann_date"].astype(str)
    return d


def quarterly_derive(inc, cf, bs, fi) -> pd.DataFrame:
    """四表 → 季频派生表(每报告期一行,按 ann_date 升序)。
    inc: ann_date,end_date,revenue,n_income_attr_p;cf: ...,n_cashflow_act;
    bs: ...,total_assets;fi: ...,q_roe,grossprofit_margin,q_sales_yoy,debt_to_assets。
    q_profit_yoy(单季净利同比)由 inc 单季序列自算。
    ann_date = 该报告期各表最早公告日。"""
    base = _first_per_end(inc) if inc is not None and not inc.empty else pd.DataFrame(
        columns=["ann_date", "end_date", "revenue", "n_income_attr_p"])
    out = pd.DataFrame({"end_date": base["end_date"].astype(str)})

    def _merge(df, cols):
        nonlocal out
        if df is None or df.empty:
            for c in cols:
                out[c] = np.nan
            return
        d = _first_per_end(df)[["end_date"] + cols]
        out = out.merge(d, on="end_date", how="outer")
        out = out.sort_values("end_date").reset_index(drop=True)

    out = out.merge(base[["end_date", "revenue", "n_income_attr_p"]] if len(base) else
                    pd.DataFrame(columns=["end_date", "revenue", "n_income_attr_p"]),
                    on="end_date", how="outer")
    _merge(cf, ["n_cashflow_act"])
    _merge(bs, ["total_assets"])
    _merge(fi, ["q_roe", "grossprofit_margin", "q_sales_yoy", "debt_to_assets"])
    out = out.sort_values("end_date").reset_index(drop=True)
    for c in ["revenue", "n_income_attr_p", "n_cashflow_act", "total_assets", "q_roe",
              "grossprofit_margin", "q_sales_yoy", "debt_to_assets"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    ends = out["end_date"]
    np_q = _single_quarter(out["n_income_attr_p"], ends)
    rev_q = _single_quarter(out["revenue"], ends)
    ocf_q = _single_quarter(out["n_cashflow_act"], ends)
    out["np_ttm"] = _ttm(np_q, ends)
    out["rev_ttm"] = _ttm(rev_q, ends)
    out["ocf_ttm"] = _ttm(ocf_q, ends)
    out["sue"] = _sue(np_q, ends)
    out["q_profit_yoy"] = _yoy_pct(np_q, ends)          # 单季净利同比(%),tushare 无此列,自算
    out = out.rename(columns={"grossprofit_margin": "gm"})
    out["profit_acc"] = out["q_profit_yoy"].diff()
    out["accrual"] = (out["n_income_attr_p"] - out["n_cashflow_act"]) / \
        out["total_assets"].replace(0.0, np.nan)

    ann = pd.concat([_ann(inc), _ann(cf), _ann(bs), _ann(fi)])
    ann = ann.groupby("end_date")["ann_date"].min() if len(ann) else pd.Series(dtype=str)
    out["ann_date"] = out["end_date"].map(ann).fillna(out["end_date"])
    out = out.sort_values(["ann_date", "end_date"]).reset_index(drop=True)
    return out[["ann_date", "end_date"] + QUARTERLY_COLS]


def align_pit(quarterly: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """季频表 → 日频 PIT 面板(index=dates)。同 ann_date 多份取 end_date 最新;
    ann_age = 距最近公告的交易日数(公告日或其后首个交易日=0),公告前 NaN。"""
    cols = [c for c in quarterly.columns if c not in ("ann_date", "end_date")]
    dates = pd.DatetimeIndex(dates)
    if quarterly.empty:
        out = pd.DataFrame(np.nan, index=dates, columns=cols)
        out["ann_age"] = np.nan
        return out
    q = quarterly.copy()
    q["ann_date"] = pd.to_datetime(q["ann_date"].astype(str), format="%Y%m%d", errors="coerce")
    q = q.dropna(subset=["ann_date"]).sort_values(["ann_date", "end_date"])
    q = q.drop_duplicates("ann_date", keep="last").set_index("ann_date")
    out = q[cols].reindex(q.index.union(dates)).ffill().reindex(dates)
    ann_dates = q.index
    ages = np.full(len(dates), np.nan)
    if len(ann_dates):
        pos = ann_dates.searchsorted(dates, side="right") - 1      # 最近公告序号(-1=尚无)
        last_ann = ann_dates[np.clip(pos, 0, len(ann_dates) - 1)]
        first_td = dates.searchsorted(last_ann, side="left")      # 公告生效的交易日序号
        ages = (np.arange(len(dates)) - first_td).astype("float64")
        ages[pos < 0] = np.nan
    out["ann_age"] = ages
    return out


def dps_ttm(div: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """过去 365 天(含当日)内 ex_date<=d 的已实施税前每股现金分红之和。"""
    dates = pd.DatetimeIndex(dates)
    if div is None or div.empty:
        return pd.Series(0.0, index=dates)
    d = div[div["div_proc"] == "实施"].dropna(subset=["ex_date"]).copy()
    d["ex_date"] = pd.to_datetime(d["ex_date"].astype(str), format="%Y%m%d", errors="coerce")
    d = d.dropna(subset=["ex_date"])
    d["cash_div_tax"] = pd.to_numeric(d["cash_div_tax"], errors="coerce").fillna(0.0)
    if d.empty:
        return pd.Series(0.0, index=dates)
    ev = d.groupby("ex_date")["cash_div_tax"].sum().sort_index()
    ex = ev.index.to_numpy()
    cum = np.concatenate([[0.0], ev.to_numpy().cumsum()])
    hi = np.searchsorted(ex, dates.to_numpy(), side="right")
    lo = np.searchsorted(ex, (dates - pd.Timedelta(days=365)).to_numpy(), side="right")
    return pd.Series(cum[hi] - cum[lo], index=dates)


def moneyflow_daily(mf: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    cols = ["mf_lg_net", "mf_sm_net", "mf_net"]
    dates = pd.DatetimeIndex(dates)
    if mf is None or mf.empty:
        return pd.DataFrame(np.nan, index=dates, columns=cols)
    m = mf.copy()
    m["trade_date"] = pd.to_datetime(m["trade_date"].astype(str), format="%Y%m%d")
    m = m.drop_duplicates("trade_date").set_index("trade_date")
    for c in ["buy_sm_amount", "sell_sm_amount", "buy_lg_amount", "sell_lg_amount",
              "buy_elg_amount", "sell_elg_amount", "net_mf_amount"]:
        m[c] = pd.to_numeric(m[c], errors="coerce")
    out = pd.DataFrame(index=dates)
    out["mf_lg_net"] = (m["buy_lg_amount"] + m["buy_elg_amount"]
                        - m["sell_lg_amount"] - m["sell_elg_amount"]).reindex(dates)
    out["mf_sm_net"] = (m["buy_sm_amount"] - m["sell_sm_amount"]).reindex(dates)
    out["mf_net"] = m["net_mf_amount"].reindex(dates)
    return out


class PitFields:
    """按票读 tushare_extra.db 并产出 PIT 日频附加列。"""

    def __init__(self, db_path: str, moneyflow: bool = True):
        """moneyflow=False 跳过 1400 万行的资金流表(夜链用:研究专用字段,且冷读极慢)。"""
        self.con = sqlite3.connect(db_path)
        self.con.execute("PRAGMA query_only=1")
        self.moneyflow = moneyflow
        self.missing = 0

    def _q(self, sql, code):
        try:
            return pd.read_sql_query(sql, self.con, params=(code,))
        except Exception as e:      # 缺表 → 空;缺列等编程错误必须暴露
            if "no such table" in str(e):
                return pd.DataFrame()
            raise

    def for_code(self, code: str, dates: pd.DatetimeIndex) -> pd.DataFrame:
        inc = self._q("select ann_date,end_date,revenue,n_income_attr_p "
                      "from ts_income where ts_code=?", code)
        cf = self._q("select ann_date,end_date,n_cashflow_act from ts_cashflow where ts_code=?", code)
        bs = self._q("select ann_date,end_date,total_assets from ts_balancesheet where ts_code=?", code)
        fi = self._q("select ann_date,end_date,q_roe,grossprofit_margin,q_sales_yoy,"
                     "debt_to_assets from ts_fina_indicator where ts_code=?", code)
        div = self._q("select div_proc,ex_date,cash_div_tax from ts_dividend where ts_code=?", code)
        mf = self._q("select trade_date,buy_sm_amount,sell_sm_amount,buy_lg_amount,sell_lg_amount,"
                     "buy_elg_amount,sell_elg_amount,net_mf_amount from ts_moneyflow where ts_code=?",
                     code) if self.moneyflow else pd.DataFrame()
        if inc.empty and fi.empty:
            self.missing += 1
        dates = pd.DatetimeIndex(dates)
        q = quarterly_derive(inc, cf, bs, fi)
        out = align_pit(q, dates)
        out["dps_ttm"] = dps_ttm(div, dates)
        out = out.join(moneyflow_daily(mf, dates))
        for c in PIT_COLS:
            if c not in out.columns:
                out[c] = np.nan
        return out[PIT_COLS].astype("float64")

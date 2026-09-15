"""对照 BaostockSource 与 TushareSource 的日线:价格/成交量/复权价是否一致。
用法: .venv/bin/python scripts/compare_baostock_tushare.py [codes...]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable
from datetime import date
import pandas as pd
from app.config import Settings
from app.data.tushare_source import TushareSource
from app.data.baostock_source import BaostockSource

DEFAULT = ["600519.SH", "000001.SZ", "300750.SZ", "688981.SH", "002594.SZ", "301269.SZ"]


def to_df(bars):
    df = pd.DataFrame([b.__dict__ for b in bars]).set_index("trade_date")
    return df


def main():
    codes = sys.argv[1:] or DEFAULT
    start, end = date(2025, 1, 1), date(2026, 9, 12)
    ts = TushareSource(token=Settings().tushare_token)
    bs = BaostockSource()
    for code in codes:
        a = to_df(ts.get_daily_bars(code, start, end))
        b = to_df(bs.get_daily_bars(code, start, end))
        common = a.index.intersection(b.index)
        only_a, only_b = a.index.difference(b.index), b.index.difference(a.index)
        a, b = a.loc[common], b.loc[common]
        px = ["open", "high", "low", "close"]
        px_diff = (a[px] - b[px]).abs().max().max()
        vol_rel = ((a["volume"] - b["volume"]).abs() / a["volume"]).max()
        # 复权:因子绝对值不同,比后复权价归一到最后一天
        a_hfq = a["close"] * a["adj_factor"]; b_hfq = b["close"] * b["adj_factor"]
        a_hfq, b_hfq = a_hfq / a_hfq.iloc[-1], b_hfq / b_hfq.iloc[-1]
        hfq_rel = ((a_hfq - b_hfq).abs() / a_hfq).max()
        n_div = (a["adj_factor"].diff().abs() > 1e-9).sum()
        print(f"{code}: 共同交易日={len(common)} 仅tushare={len(only_a)} 仅baostock={len(only_b)} "
              f"| 价格最大绝对差={px_diff:.4f} 成交量最大相对差={vol_rel:.2e} "
              f"| 归一化后复权价最大相对差={hfq_rel:.2e} (窗口内除权次数={n_div})")
        if len(only_a) or len(only_b):
            print(f"   仅tushare: {list(only_a)[:5]}  仅baostock: {list(only_b)[:5]}")
        if px_diff > 0.011 or vol_rel > 0.01 or hfq_rel > 1e-3:
            bad = a.index[(a[px] - b[px]).abs().max(axis=1) > 0.011][:3]
            print("   ⚠️ 差异样本:")
            for d in bad:
                print("     ", d, a.loc[d, px + ["volume"]].tolist(), b.loc[d, px + ["volume"]].tolist())
            fbad = (a_hfq - b_hfq).abs().sort_values().index[-3:]
            for d in fbad:
                print("      hfq", d, f"ts={a_hfq[d]:.5f} bs={b_hfq[d]:.5f} "
                      f"ts_f={a.loc[d,'adj_factor']} bs_f={b.loc[d,'adj_factor']}")
    bs.close()


if __name__ == "__main__":
    main()

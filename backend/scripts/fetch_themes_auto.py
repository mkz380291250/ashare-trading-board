"""Autonomous: get full theme membership (try EastMoney repeatedly, fall back to
tushare concept once its hourly quota resets), write /tmp/theme_members.json, then
run the backtest. Whichever source recovers first wins. Run detached."""
import sys
import json
import time
import sqlite3
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.screener.themes import EastMoneyThemeSource, datacenter_board_members

DB = str(Path(__file__).resolve().parents[1] / "ashare.db")
OUT = "/tmp/theme_members.json"
PY = str(Path(__file__).resolve().parents[1] / ".venv/bin/python")
BACKTEST = str(Path(__file__).resolve().parent / "backtest_screener.py")

KEYWORDS = {
    "英伟达链": ["CPO", "光模块", "英伟达", "铜缆", "液冷", "光通信"],
    "半导体": ["半导体"],
    "芯片": ["芯片", "存储", "Chiplet"],
    "算力": ["算力", "数据中心", "东数西算", "IDC"],
    "电力": ["电力", "特高压", "电网", "绿色电力", "虚拟电厂"],
}
# Exact EastMoney concept board names (datacenter API; push2 is blocked here).
THEME_BOARDS = {
    "英伟达链": ["英伟达概念", "CPO概念", "铜缆高速连接"],
    "半导体": ["半导体", "半导体概念", "第三代半导体"],
    "芯片": ["存储芯片", "汽车芯片", "Chiplet概念"],
    "算力": ["数据中心", "东数西算"],
    "电力": ["电力", "特高压", "绿色电力", "虚拟电厂"],
}
DEADLINE_MIN = 55


def valid_codes():
    return {r[0] for r in sqlite3.connect(DB, timeout=60).execute(
        "select distinct code from daily_quotes")}


def try_eastmoney(valid):
    src = EastMoneyThemeSource(
        THEME_BOARDS, fetch_board=datacenter_board_members, valid=valid
    )
    out = {theme: src.members(theme) for theme in src.themes()}
    return out if sum(len(v) for v in out.values()) > 0 else None


def try_tushare(valid):
    import tushare as ts
    pro = ts.pro_api(get_settings().tushare_token)
    idx = pro.ths_index()                       # raises if quota not reset
    concepts = idx[idx["type"] == "N"].copy()
    concepts["count"] = concepts["count"].fillna(0)
    out = {}
    for theme, kws in KEYWORDS.items():
        matched = concepts[concepts["name"].str.contains("|".join(kws), na=False)]
        matched = matched.sort_values("count", ascending=False).head(3)
        codes = set()
        for _, row in matched.iterrows():
            for _try in range(3):
                try:
                    mem = pro.ths_member(ts_code=row["ts_code"])
                    codes.update(str(x) for x in mem["con_code"].tolist())
                    break
                except Exception:
                    time.sleep(61)              # ths_member = 1/min
        out[theme] = sorted(c for c in codes if c in valid)
    return out if sum(len(v) for v in out.values()) > 0 else None


def main():
    valid = valid_codes()
    deadline = time.time() + DEADLINE_MIN * 60
    members = None
    attempt = 0
    while time.time() < deadline and members is None:
        attempt += 1
        try:
            members = try_eastmoney(valid)
            if members:
                print(f"SOURCE=eastmoney attempt={attempt}", flush=True)
                break
        except Exception as e:
            print(f"[{attempt}] eastmoney fail: {e!r}", flush=True)
        try:
            members = try_tushare(valid)
            if members:
                print(f"SOURCE=tushare attempt={attempt}", flush=True)
                break
        except Exception as e:
            print(f"[{attempt}] tushare fail: {e!r}", flush=True)
        time.sleep(60)

    if not members:
        print("MEMBERS_FAILED", flush=True)
        return
    Path(OUT).write_text(json.dumps(members, ensure_ascii=False))
    print(f"WROTE {OUT} sizes={ {k: len(v) for k, v in members.items()} }", flush=True)

    print("=== RUNNING BACKTEST ===", flush=True)
    r = subprocess.run([PY, BACKTEST], capture_output=True, text=True, cwd=str(Path(BACKTEST).parents[1]))
    print(r.stdout[-4000:], flush=True)
    print("PIPELINE_DONE", flush=True)


if __name__ == "__main__":
    main()

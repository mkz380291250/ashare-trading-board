"""每日编排:全市场行情 -> qlib 重建 -> 跟踪表指标刷新。
可命令行运行(python scripts/daily_full.py),也被 APScheduler 调用 run_all()。"""
import subprocess
import sys
import traceback
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.screener.tracklist import Tracker

PY = sys.executable


def step_quotes() -> None:
    subprocess.run([PY, str(ROOT / "scripts" / "daily_update_quotes.py")],
                   cwd=ROOT, check=True)


def step_qlib() -> None:
    s = get_settings()
    subprocess.run([PY, str(ROOT / "scripts" / "build_qlib_data.py"),
                    "--qlib-dir", s.qlib_data_dir], cwd=ROOT, check=True)


def step_tracklist() -> None:
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    tr = Tracker(session)
    for e in tr.list():
        bars = store.get_bars(e.code, e.added_on, date.today())
        if bars:
            tr.update_metrics(e.code, e.added_on, bars)


def run_all() -> bool:
    ok = True
    for step in (step_quotes, step_qlib, step_tracklist):
        try:
            step()
        except Exception:                       # noqa: BLE001 — 单步失败不阻断
            ok = False
            traceback.print_exc()
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)

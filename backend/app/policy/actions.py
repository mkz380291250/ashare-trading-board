"""策略动作执行器。run_remine 走 subprocess 跑挖掘+冻结(冻结归档旧产物=回滚句柄)。"""
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]      # backend/
_PY = sys.executable


def run_remine(*, root: Path | None = None) -> int:
    root = root or _ROOT
    mining = subprocess.run([_PY, str(root / "scripts" / "run_factor_mining.py")], cwd=root)
    if mining.returncode != 0:
        return mining.returncode
    freeze = subprocess.run([_PY, str(root / "scripts" / "freeze_factors.py")], cwd=root)
    return freeze.returncode

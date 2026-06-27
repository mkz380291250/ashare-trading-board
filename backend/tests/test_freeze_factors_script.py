from pathlib import Path
from scripts.freeze_factors import frozen_path


class _S:
    qlib_data_dir = "/data/proj/data/qlib_cn"


def test_frozen_path_under_factors_dir():
    p = frozen_path(_S())
    assert p == Path("/data/proj/data/factors/frozen_composite.json")

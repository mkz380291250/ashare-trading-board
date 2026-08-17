from pathlib import Path
from scripts.freeze_factors import frozen_path


class _S:
    qlib_data_dir = "/data/proj/data/qlib_cn"


def test_frozen_path_under_factors_dir():
    p = frozen_path(_S())
    assert p == Path("/data/proj/data/factors/frozen_composite.json")


def test_freeze_horizon_default_none_and_cli_present():
    import inspect
    from scripts.freeze_factors import freeze, build_parser
    # freeze 的 horizon 默认必须是 None(好回落到 settings),不能写死 5
    assert inspect.signature(freeze).parameters["horizon"].default is None
    # CLI 暴露 --horizon,默认 None
    ns = build_parser().parse_args([])
    assert ns.horizon is None
    assert build_parser().parse_args(["--horizon", "20"]).horizon == 20

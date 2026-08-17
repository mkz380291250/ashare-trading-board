def test_horizon_arg_defaults_to_none():
    # 默认 None,好让 main 回落到 settings.discovery_horizon(防写死 h5)
    from scripts.run_factor_mining import build_parser
    assert build_parser().parse_args([]).horizon is None
    assert build_parser().parse_args(["--horizon", "10"]).horizon == 10

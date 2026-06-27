from scripts.run_discovery import build_parser


def test_source_defaults_to_qlib():
    args = build_parser().parse_args([])
    assert args.source == "qlib"


def test_source_can_select_momentum():
    args = build_parser().parse_args(["--source", "momentum"])
    assert args.source == "momentum"

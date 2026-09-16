import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_data_health import Report, check_frozen_fields


def _qlib(tmp_path, fields):
    q = tmp_path / "qlib_cn"
    d = q / "features" / "sz300750"
    d.mkdir(parents=True)
    for f in fields:
        (d / f"{f}.day.bin").write_bytes(b"")
    return q


def _frozen(tmp_path, factors):
    p = tmp_path / "frozen.json"
    p.write_text(json.dumps({"as_of": "2026-09-16", "factors": factors,
                             "signs": {f: 1.0 for f in factors}, "weights": {f: 1.0 for f in factors},
                             "universe": "cyb", "horizon": 20, "source_report": "x",
                             "metrics_at_freeze": {}}))
    return p


def test_frozen_fields_fail_when_pit_field_missing(tmp_path):
    q = _qlib(tmp_path, ["close", "total_mv"])
    rep = Report()
    check_frozen_fields(rep, str(q), _frozen(tmp_path, ["sp_ttm", "turn5"]))   # 需要 rev_ttm/turnover_rate
    assert rep.failed
    assert "rev_ttm" in rep.items[0]["msg"] and "turnover_rate" in rep.items[0]["msg"]


def test_frozen_fields_pass_when_all_present(tmp_path):
    q = _qlib(tmp_path, ["close", "total_mv", "rev_ttm", "turnover_rate"])
    rep = Report()
    check_frozen_fields(rep, str(q), _frozen(tmp_path, ["sp_ttm", "turn5"]))
    assert not rep.failed and rep.items[0]["level"] == "PASS"


def test_frozen_fields_warn_when_no_frozen(tmp_path):
    q = _qlib(tmp_path, ["close"])
    rep = Report()
    check_frozen_fields(rep, str(q), tmp_path / "nope.json")
    assert not rep.failed and rep.items[0]["level"] == "WARN"

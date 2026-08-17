"""The `--csv` path: screening a user's own panel from the command line."""
import csv
import json

import numpy as np
import pytest

from pit_release_gate.simulate import main, read_csv_columns
from test_frame import planted_panel


def write_panel(path, **kw):
    p = planted_panel(**kw)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(list(p))
        for row in zip(*p.values()):
            w.writerow(row)
    return path


def test_reads_a_csv_into_typed_columns(tmp_path):
    f = write_panel(tmp_path / "p.csv", n_periods=7, n=20)
    cols = read_csv_columns(f)
    assert set(cols) == {"period", "entity", "arrival", "value", "size"}
    assert cols["value"].dtype == float
    assert len(cols["value"]) == 7 * 20


def test_blank_and_na_cells_become_nan(tmp_path):
    f = tmp_path / "gappy.csv"
    f.write_text("period,arrival,value,size\n1,0.1,,1.0\n1,0.2,NA,2.0\n",
                 encoding="utf-8")
    cols = read_csv_columns(f)
    assert np.isnan(cols["value"]).all()


def test_cli_screens_a_planted_leak(tmp_path, capsys):
    f = write_panel(tmp_path / "leak.csv", leak=2.0)
    main(["--csv", str(f), "--value", "value"])
    out = capsys.readouterr().out
    assert "susceptible" in out
    assert "signal-cycles screened" in out


def test_cli_exports_a_valid_record(tmp_path, capsys):
    f = write_panel(tmp_path / "leak.csv", leak=2.0)
    out_json = tmp_path / "results.json"
    main(["--csv", str(f), "--value", "value", "--export", str(out_json)])
    record = json.loads(out_json.read_text(encoding="utf-8"))
    assert record["schema"] == "pit-screen-results"
    assert record["signals"][0]["verdict"] == "susceptible"
    assert "no network call" in capsys.readouterr().out


def test_cli_screens_several_signals_and_honours_settings(tmp_path, capsys):
    p = planted_panel(leak=2.0, n=200)
    p["quiet"] = p["size"] * 0.3 + np.random.default_rng(5).normal(size=len(p["size"]))
    f = tmp_path / "two.csv"
    with open(f, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(list(p))
        for row in zip(*p.values()):
            w.writerow(row)
    main(["--csv", str(f), "--value", "value", "--value", "quiet",
          "--trailing-k", "4", "--threshold", "0.15"])
    out = capsys.readouterr().out
    assert "trailing_k=4" in out and "threshold=0.15" in out
    assert "1 benign, 1 susceptible" in out


def test_cli_rejects_incoherent_flags(tmp_path):
    f = write_panel(tmp_path / "p.csv")
    with pytest.raises(SystemExit):
        main(["--csv", str(f)])                      # --csv without --value
    with pytest.raises(SystemExit):
        main(["--value", "value"])                   # --value without --csv


def test_demo_path_is_untouched_by_the_csv_flags(capsys):
    """The default invocation must still be the known-ground-truth demo."""
    main(["--train", "2", "--eval", "4"])
    out = capsys.readouterr().out
    assert "Strong-leak" in out and "gated" in out

"""Tests for the ``pit-screen-results`` record and the ``--export`` path.

One property matters more than the schema details and is asserted from
several directions here: **this package never talks to the network.** The
urlopen entry point and the socket constructor are monkeypatched to raise,
and every path must still succeed; a structural test then walks every module
in the package and fails if any of them so much as imports a transport.

There is deliberately no submission path on this branch. The ``--submit``
half of this work is parked on the ``submit-cli`` branch until a receiving
endpoint exists -- a command pointing at an endpoint that is not there must
not ship.
"""
import getpass
import json
import os
import re
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

import pit_release_gate
from pit_release_gate import results as results_mod
from pit_release_gate.results import (
    SCHEMA,
    SCHEMA_VERSION,
    TOOL,
    VERDICTS,
    build_results,
    screen_config,
    summarize_signal,
    validate_results,
    write_results,
)
from pit_release_gate.simulate import main


# ---------------------------------------------------------------------------
# no test in this file may reach the real network
# ---------------------------------------------------------------------------
def _exploding(*a, **k):
    raise AssertionError("network call attempted")


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to open a socket or a URL blows up the test."""
    monkeypatch.setattr(urllib.request, "urlopen", _exploding)
    monkeypatch.setattr(socket, "socket", _exploding)
    return None


def _tiny_record(**kw):
    """A small valid record built through the public API (no demo run)."""
    sig = summarize_signal("alpha", rhos=[0.01, -0.02, 0.30],
                           phi_reqs=[0.35, 0.35, 0.35], rho_threshold=0.10)
    cfg = screen_config(rho_threshold=0.10, phi_min=0.35, kappa=1.0,
                        trailing_k=4, min_entities=6)
    return build_results([sig], cfg, **kw)


# ---------------------------------------------------------------------------
# 1. the record: summary statistics, totals consistent by construction
# ---------------------------------------------------------------------------
def test_signal_summary_reports_only_summary_statistics():
    sig = summarize_signal("alpha", rhos=[0.01, -0.02, 0.30],
                           phi_reqs=[0.35, 0.35, 0.35], rho_threshold=0.10)
    assert set(sig) == {"name", "periods_screened", "periods_flagged", "mean_rho",
                        "max_abs_rho", "mean_phi_req", "verdict"}
    assert sig["periods_screened"] == 3
    assert sig["periods_flagged"] == 1          # only |0.30| exceeds 0.10
    assert sig["max_abs_rho"] == pytest.approx(0.30)
    assert sig["mean_rho"] == pytest.approx((0.01 - 0.02 + 0.30) / 3)
    assert sig["mean_phi_req"] == pytest.approx(0.35)
    assert sig["verdict"] in VERDICTS
    assert sig["periods_flagged"] <= sig["periods_screened"]


def test_verdict_follows_the_threshold_and_can_be_overridden():
    benign = summarize_signal("a", [0.01, 0.0], [0.35, 0.35], rho_threshold=0.10)
    leaky = summarize_signal("b", [-0.9, -0.8], [1.0, 1.0], rho_threshold=0.10)
    assert benign["verdict"] == "benign"
    assert leaky["verdict"] == "susceptible"
    # the screen's own frozen verdict wins when the caller supplies it
    forced = summarize_signal("c", [0.01, 0.0], [0.35, 0.35],
                              rho_threshold=0.10, susceptible=True)
    assert forced["verdict"] == "susceptible"


def test_build_results_totals_are_consistent_by_construction():
    sigs = [
        summarize_signal("a", [0.01, 0.0, 0.0], [0.35] * 3, rho_threshold=0.10),
        summarize_signal("b", [-0.9, -0.8], [1.0, 1.0], rho_threshold=0.10),
    ]
    rec = build_results(sigs, screen_config(0.10, 0.35, 1.0, 4, 6))
    assert rec["schema"] == SCHEMA == "pit-screen-results"
    assert rec["schema_version"] == SCHEMA_VERSION == "1.0"
    assert rec["tool"] == TOOL == "pit-release-gate"
    assert rec["tool_version"] == pit_release_gate.__version__
    assert rec["config"] == {"rho_threshold": 0.10, "phi_min": 0.35, "kappa": 1.0,
                             "trailing_k": 4, "min_entities": 6}
    assert rec["totals"] == {"signal_cycles": 5, "signals_benign": 1,
                             "signals_susceptible": 1}
    assert validate_results(rec) == []


def test_record_carries_no_timestamp_unless_the_caller_passes_a_date():
    a = _tiny_record()
    b = _tiny_record()
    assert a == b                       # reproducible: nothing time-varying inside
    assert json.dumps(a) == json.dumps(b)
    assert "date" not in a
    assert not [k for k in a if "time" in k.lower() or "date" in k.lower()]
    dated = _tiny_record(date="2026-08-16")
    assert dated["date"] == "2026-08-16"


# ---------------------------------------------------------------------------
# 2. the validator
# ---------------------------------------------------------------------------
def test_validate_accepts_a_built_record():
    assert validate_results(_tiny_record()) == []


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r.pop("schema_version"), "schema_version"),
    (lambda r: r.update(schema_version="9.9"), "9.9"),
    (lambda r: r.pop("tool_version"), "tool_version"),
    (lambda r: r.pop("config"), "config"),
    (lambda r: r["config"].pop("kappa"), "kappa"),
    (lambda r: r["signals"][0].pop("mean_rho"), "mean_rho"),
    (lambda r: r["signals"][0].update(verdict="probably fine"), "verdict"),
    (lambda r: r["signals"][0].update(periods_flagged=99), "periods_flagged"),
    (lambda r: r["totals"].update(signal_cycles=999), "signal_cycles"),
    (lambda r: r.update(signals="not a list"), "signals"),
])
def test_validate_reports_each_kind_of_problem(mutate, needle):
    rec = _tiny_record()
    mutate(rec)
    problems = validate_results(rec)
    assert problems, "validator missed a broken record"
    assert any(needle in p for p in problems), problems


def test_validate_rejects_non_mapping():
    assert validate_results([1, 2, 3])
    assert validate_results(None)


# ---------------------------------------------------------------------------
# 3. --export is fully offline
# ---------------------------------------------------------------------------
def test_export_writes_a_valid_results_json(tmp_path, capsys):
    path = tmp_path / "results.json"
    main(["--train", "3", "--eval", "4", "--export", str(path)])
    capsys.readouterr()

    rec = json.loads(path.read_text(encoding="utf-8"))
    assert validate_results(rec) == []
    assert rec["schema"] == "pit-screen-results"
    assert rec["schema_version"] == "1.0"
    assert rec["tool"] == "pit-release-gate"
    assert rec["tool_version"] == pit_release_gate.__version__
    assert rec["config"]["trailing_k"] == 3

    names = [s["name"] for s in rec["signals"]]
    assert names == ["clean", "composition", "mild_leak", "strong_leak"]
    by_name = {s["name"]: s for s in rec["signals"]}
    assert by_name["clean"]["verdict"] == "benign"
    assert by_name["mild_leak"]["verdict"] == "susceptible"
    assert by_name["strong_leak"]["verdict"] == "susceptible"
    # the susceptible signals are graded to a higher required completeness
    assert by_name["strong_leak"]["mean_phi_req"] > by_name["clean"]["mean_phi_req"]

    for s in rec["signals"]:
        assert s["periods_screened"] == 4
        assert s["periods_flagged"] <= s["periods_screened"]
    assert rec["totals"]["signal_cycles"] == 16
    assert rec["totals"]["signals_benign"] + rec["totals"]["signals_susceptible"] == 4


def test_export_performs_no_network_io(tmp_path, capsys, no_network):
    """The red line: --export must not touch the network at all."""
    path = tmp_path / "offline.json"
    main(["--train", "2", "--eval", "2", "--export", str(path)])
    capsys.readouterr()
    assert validate_results(json.loads(path.read_text(encoding="utf-8"))) == []


def test_results_module_has_no_network_machinery():
    # the module that builds and writes the record cannot import a transport
    assert not hasattr(results_mod, "urllib")
    assert not hasattr(results_mod, "socket")
    src = Path(results_mod.__file__).read_text(encoding="utf-8")
    assert "urllib" not in src
    assert "atexit" not in src


def _imported_modules(path: Path) -> set:
    src = path.read_text(encoding="utf-8")
    return {m.lstrip(".").split(".")[0]
            for m in re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M)}


def test_no_module_in_the_package_can_reach_the_network():
    """Structural guard on the no-telemetry red line.

    Not "no module reports by default" -- *no module can*. Nothing in the
    package may import a transport, register an exit hook, or spawn a worker
    that could report in the background. This is asserted over every module,
    so adding a phone-home later fails the suite rather than shipping.
    """
    pkg = Path(pit_release_gate.__file__).parent
    modules = sorted(pkg.glob("*.py"))
    assert len(modules) >= 8
    for py in modules:
        imported = _imported_modules(py)
        assert "atexit" not in imported, f"{py.name} registers an exit hook"
        assert not imported & {"threading", "multiprocessing", "concurrent",
                               "asyncio", "subprocess"}, f"{py.name} spawns work"
        assert not imported & {"urllib", "socket", "http", "ssl", "requests",
                               "smtplib", "ftplib"}, f"{py.name} imports a transport"


def test_the_package_ships_no_submission_path():
    """The --submit half stays parked until a receiving endpoint exists."""
    pkg = Path(pit_release_gate.__file__).parent
    assert not (pkg / "submit.py").exists()
    assert not hasattr(pit_release_gate, "submit_results")
    help_text = Path(pkg / "simulate.py").read_text(encoding="utf-8")
    for flag in ("'--submit'", "'--contact'", "'--dry-run'"):
        assert flag not in help_text, f"{flag} is still wired into the CLI"


def test_the_export_path_never_reads_a_clock():
    """No timestamps generated inside the library: a date must be passed in."""
    pkg = Path(pit_release_gate.__file__).parent
    for name in ("results.py", "simulate.py"):
        imported = _imported_modules(pkg / name)
        assert not imported & {"time", "datetime", "calendar"}, f"{name} reads a clock"


def test_export_is_byte_identical_across_runs(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    main(["--train", "2", "--eval", "2", "--export", str(a)])
    main(["--train", "2", "--eval", "2", "--export", str(b)])
    capsys.readouterr()
    assert a.read_bytes() == b.read_bytes()


def test_exported_payload_carries_no_identifying_details(tmp_path, capsys):
    path = tmp_path / "results.json"
    main(["--train", "2", "--eval", "2", "--export", str(path)])
    capsys.readouterr()
    text = path.read_text(encoding="utf-8")
    for secret in (getpass.getuser(), socket.gethostname(), os.getcwd(),
                   str(Path.home()), sys.executable, str(path)):
        if secret and len(secret) > 3:
            assert secret not in text, f"payload leaks {secret!r}"
    for banned in ("path", "user", "host", "cwd", "platform", "python"):
        assert banned not in text.lower()


# ---------------------------------------------------------------------------
# 4. the submission flags are not wired in on this branch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("argv", [
    ["--submit", "https://example.invalid/submit"],
    ["--contact", "a@b.org"],
    ["--dry-run"],
])
def test_cli_does_not_accept_submission_flags(argv, capsys, no_network):
    """argparse must reject them outright -- they are not shipped."""
    with pytest.raises(SystemExit) as exc:
        main(["--train", "2", "--eval", "2", *argv])
    assert exc.value.code != 0
    assert "unrecognized arguments" in capsys.readouterr().err


def test_plain_cli_run_writes_no_file_and_opens_no_socket(tmp_path, capsys, no_network):
    main(["--train", "2", "--eval", "2"])
    out = capsys.readouterr().out
    assert "gated" in out
    assert list(tmp_path.iterdir()) == []

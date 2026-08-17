"""Tests for the ``pit-screen-results`` export and the opt-in submission.

Two properties matter more than the schema details and are asserted
explicitly here:

* ``--export`` is *offline*. The urlopen entry point (and the socket
  constructor under it) are monkeypatched to raise, and the export must
  still succeed -- the package must never phone home.
* ``--submit`` is *opt-in and inspectable*. It refuses an invalid payload,
  prints the exact bytes it is about to send, sends nothing under
  ``--dry-run``, and fails loudly with a non-zero exit on a network error.

No test in this file may touch the real network: the transport is always a
fake installed over ``urllib.request.urlopen``.
"""
import getpass
import json
import os
import re
import socket
import sys
import urllib.error
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
from pit_release_gate.submit import CITATION_DOIS, SubmissionError, submit_results

BADGE_URL = "https://example.invalid/badge/abcdef.svg"


# ---------------------------------------------------------------------------
# fake transport (no test ever reaches the real network)
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Records the Request objects handed to it and replies with JSON."""

    def __init__(self, reply=None):
        self.requests = []
        self.reply = {"score": 87, "badge_url": BADGE_URL} if reply is None else reply

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return _FakeResponse(json.dumps(self.reply).encode("utf-8"))


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


def test_only_the_submit_module_can_reach_the_network():
    """Structural guard on the no-telemetry red line.

    Nothing in the package may register an exit hook or spawn a worker that
    could report in the background, and only the module reached by an explicit
    --submit may import a transport at all.
    """
    pkg = Path(pit_release_gate.__file__).parent
    modules = sorted(pkg.glob("*.py"))
    assert len(modules) >= 8
    for py in modules:
        imported = _imported_modules(py)
        assert "atexit" not in imported, f"{py.name} registers an exit hook"
        assert not imported & {"threading", "multiprocessing", "concurrent",
                               "asyncio", "subprocess"}, f"{py.name} spawns work"
        if py.name != "submit.py":
            assert not imported & {"urllib", "socket", "http", "ssl", "requests",
                                   "smtplib", "ftplib"}, f"{py.name} imports a transport"
    # ... and the one that does is reached only through --submit
    assert "urllib" in _imported_modules(pkg / "submit.py")


def test_the_export_path_never_reads_a_clock():
    """No timestamps generated inside the library: a date must be passed in."""
    pkg = Path(pit_release_gate.__file__).parent
    for name in ("results.py", "submit.py", "simulate.py"):
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
# 4. --submit: opt-in, inspectable, loud on failure
# ---------------------------------------------------------------------------
def test_submit_refuses_an_invalid_payload(monkeypatch, capsys):
    monkeypatch.setattr(urllib.request, "urlopen", _exploding)  # must not be reached
    rec = _tiny_record()
    rec["totals"]["signal_cycles"] = 999
    with pytest.raises(SubmissionError) as exc:
        submit_results(rec, "https://example.invalid/submit")
    assert "signal_cycles" in str(exc.value)
    assert "refus" in str(exc.value).lower()


def test_submit_posts_the_exact_payload_it_printed(monkeypatch, capsys):
    opener = _FakeOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    rec = _tiny_record()
    reply = submit_results(rec, "https://example.invalid/submit")

    assert len(opener.requests) == 1
    req = opener.requests[0]
    assert req.full_url == "https://example.invalid/submit"
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    sent = req.data.decode("utf-8")
    assert json.loads(sent) == rec

    out = capsys.readouterr().out
    assert sent in out, "the exact payload must be printed before sending"
    assert "87" in out and BADGE_URL in out
    assert "If you use this in research, cite:" in out
    for doi in CITATION_DOIS:
        assert doi in out
    assert reply["badge_url"] == BADGE_URL


def test_submit_omits_contact_unless_it_is_given(monkeypatch, capsys):
    opener = _FakeOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    submit_results(_tiny_record(), "https://example.invalid/submit")
    assert "contact" not in json.loads(opener.requests[0].data.decode("utf-8"))
    assert "contact" not in capsys.readouterr().out

    submit_results(_tiny_record(), "https://example.invalid/submit",
                   contact="someone@example.org")
    body = json.loads(opener.requests[1].data.decode("utf-8"))
    assert body["contact"] == "someone@example.org"
    assert "someone@example.org" in capsys.readouterr().out


def test_submit_dry_run_prints_the_payload_and_sends_nothing(capsys, no_network):
    rec = _tiny_record()
    assert submit_results(rec, "https://example.invalid/submit", dry_run=True) is None
    out = capsys.readouterr().out
    assert json.dumps(rec, indent=2, ensure_ascii=False) in out
    assert "dry-run" in out.lower()
    assert "nothing was sent" in out.lower()


def test_submit_network_failure_raises(monkeypatch, capsys):
    def boom(req, timeout=None):
        raise urllib.error.URLError("name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(SubmissionError) as exc:
        submit_results(_tiny_record(), "https://example.invalid/submit")
    assert "failed" in str(exc.value).lower()
    assert "name or service not known" in str(exc.value)


def test_cli_submit_failure_exits_non_zero(tmp_path, monkeypatch, capsys):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError("https://example.invalid/submit", 503,
                                     "Service Unavailable", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        main(["--train", "2", "--eval", "2", "--submit", "https://example.invalid/submit"])
    assert exc.value.code not in (0, None)
    assert "failed" in str(exc.value.code).lower()


def test_cli_submit_sends_the_exported_record(tmp_path, monkeypatch, capsys):
    opener = _FakeOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    path = tmp_path / "results.json"
    main(["--train", "2", "--eval", "2", "--export", str(path),
          "--submit", "https://example.invalid/submit",
          "--contact", "someone@example.org"])
    out = capsys.readouterr().out

    exported = json.loads(path.read_text(encoding="utf-8"))
    sent = json.loads(opener.requests[0].data.decode("utf-8"))
    assert "contact" not in exported          # the file never carries the contact
    assert sent["contact"] == "someone@example.org"
    assert {k: v for k, v in sent.items() if k != "contact"} == exported
    assert BADGE_URL in out
    for doi in CITATION_DOIS:
        assert doi in out


def test_cli_dry_run_sends_nothing(capsys, no_network):
    main(["--train", "2", "--eval", "2", "--dry-run",
          "--submit", "https://example.invalid/submit"])
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert "pit-screen-results" in out


def test_cli_rejects_contact_or_dry_run_without_submit(capsys):
    for argv in (["--contact", "a@b.org"], ["--dry-run"]):
        with pytest.raises(SystemExit) as exc:
            main(["--train", "2", "--eval", "2", *argv])
        assert exc.value.code != 0


def test_plain_cli_run_writes_no_file_and_opens_no_socket(tmp_path, capsys, no_network):
    main(["--train", "2", "--eval", "2"])
    out = capsys.readouterr().out
    assert "gated" in out
    assert list(tmp_path.iterdir()) == []

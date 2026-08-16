"""Smoke tests: the CLI demo runs end-to-end, and the completeness
monitor reports sane values. Complements test_reproduces_paper.py,
which asserts the demo's numerical claims."""
import subprocess
import sys

import numpy as np

from pit_release_gate import (AsOfDataStore, CompletenessMonitor, badge_snippet,
                              make_group, run_demo)


def test_cli_demo_runs_and_prints_verdicts():
    out = subprocess.run(
        [sys.executable, "-m", "pit_release_gate"],
        capture_output=True, text=True, timeout=600,
    )
    assert out.returncode == 0
    text = out.stdout
    # one line per planted condition, and the headline policies all present
    for token in ("Clean", "Composition", "Mild-leak", "Strong-leak",
                  "naive", "deadline", "gated", "kappa"):
        assert token in text, f"CLI output missing {token!r}"


def test_demo_main_in_process(capsys):
    # run the full demo in-process so coverage sees simulate.py
    from pit_release_gate.simulate import main
    main(["--train", "4", "--eval", "8"])
    text = capsys.readouterr().out
    for token in ("Clean", "Strong-leak", "gated", "deadline", "kappa"):
        assert token in text


def test_badge_snippet_reports_the_screen_result():
    r = run_demo(n_train=2, n_eval=4, verbose=False)
    text = badge_snippet(r)

    # the markdown a user actually pastes
    assert "img.shields.io/badge/screened%20with-pit--release--gate-blue" in text
    assert "github.com/MaxWellApexLab/pit-release-gate" in text

    # the summary comment carries every signal's frozen rho_hat
    for key in ("clean", "composition", "mild_leak", "strong_leak"):
        assert key in text
    # demo plants two benign and two susceptible signals
    assert "2 benign, 2 susceptible" in text


def test_badge_snippet_makes_no_pass_fail_claim():
    text = badge_snippet(run_demo(n_train=2, n_eval=4, verbose=False)).lower()
    assert "screened with" in text
    assert "not that anything passed" in text
    for forbidden in ("certif", "approv", "endors", "official", "trusted"):
        assert forbidden not in text, f"badge output must not claim {forbidden!r}"


def test_badge_flag_does_not_change_demo_output(capsys):
    from pit_release_gate.simulate import main

    main(["--train", "2", "--eval", "4"])
    plain = capsys.readouterr().out
    main(["--train", "2", "--eval", "4", "--badge"])
    badged = capsys.readouterr().out

    # the badge is strictly appended: the demo output is byte-identical
    assert badged.startswith(plain)
    assert "Badge snippet" in badged[len(plain):]
    assert "Badge snippet" not in plain


def test_completeness_monitor_fraction_and_shift():
    rng = np.random.default_rng(7)
    store = make_group(c_a=0.0, c_x=1.0, rng=rng)
    mon = CompletenessMonitor()
    early, late = mon.fraction(store, 0.2), mon.fraction(store, 0.9)
    assert 0.0 <= early < late <= 1.0
    # full cross-section by the deadline
    assert mon.fraction(store, 1.0) == 1.0
    # covariate-shift gauge is finite and shrinks as the group completes
    s_early = mon.covariate_shift(store, 0.3)
    s_late = mon.covariate_shift(store, 1.0)
    assert np.isfinite(s_early) and np.isfinite(s_late)
    assert abs(s_late) <= abs(s_early) + 1e-9

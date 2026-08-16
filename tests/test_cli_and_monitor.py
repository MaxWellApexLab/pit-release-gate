"""Smoke tests: the CLI demo runs end-to-end, and the completeness
monitor reports sane values. Complements test_reproduces_paper.py,
which asserts the demo's numerical claims."""
import subprocess
import sys

import numpy as np

from pit_release_gate import AsOfDataStore, CompletenessMonitor, make_group


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

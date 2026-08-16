"""Reproduction tests for the known-ground-truth worked example.

Two layers:

1. A fast, reduced-size run (3 train / 8 eval periods, < 5 s) that checks the
   qualitative behavior of the gate end-to-end.
2. A full-fidelity run at the paper's settings (10 train / 60 eval periods,
   ~10 s) asserting the headline numbers of the release-control paper
   (doi:10.6084/m9.figshare.33158615) within tolerance:

   * benign signals (Clean / Composition) release early -- gated completeness
     36% and 39% respectively;
   * the Strong-leak signal is forced to the deadline-complete cross-section
     (completeness exactly 1.0) where its released-signal bias is exactly 0.0;
   * the kappa sensitivity sweep is monotone: required completeness rises
     with kappa while the systematic bias shrinks to exactly 0.0.
"""
import numpy as np
import pytest

from pit_release_gate import (
    AsOfDataStore,
    CompletenessMonitor,
    PropensityReweighter,
    ReleaseController,
    SusceptibilityGate,
    make_group,
    run_demo,
)


# ---------------------------------------------------------------------------
# full-fidelity run (paper settings), computed once per test session
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def full():
    return run_demo(n_train=10, n_eval=60, verbose=False)


# ---------------------------------------------------------------------------
# 1. fast reduced-size end-to-end run
# ---------------------------------------------------------------------------
def test_reduced_simulation_end_to_end():
    r = run_demo(n_train=3, n_eval=8, verbose=False)
    assert set(r["signals"]) == {"clean", "composition", "mild_leak", "strong_leak"}
    for key in r["signals"]:
        assert set(r["signals"][key]["policies"]) == {
            "naive", "threshold", "reweight", "deadline", "gated"}

    # benign signals classified benign and released early; leaky ones wait
    assert not r["signals"]["clean"]["susceptible"]
    assert not r["signals"]["composition"]["susceptible"]
    assert r["signals"]["mild_leak"]["susceptible"]
    assert r["signals"]["strong_leak"]["susceptible"]

    assert r["signals"]["clean"]["policies"]["gated"]["comp_mean"] < 0.5
    assert r["signals"]["composition"]["policies"]["gated"]["comp_mean"] < 0.5
    assert r["signals"]["strong_leak"]["policies"]["gated"]["comp_mean"] == 1.0
    # at completeness 1.0 the released signal equals the complete-cross-section
    # signal, so the bias is identically zero
    assert r["signals"]["strong_leak"]["policies"]["gated"]["bias_mean"] == 0.0


def test_simulation_is_deterministic():
    a = run_demo(n_train=2, n_eval=4, verbose=False)
    b = run_demo(n_train=2, n_eval=4, verbose=False)
    for key in a["signals"]:
        for p in a["signals"][key]["policies"]:
            assert (a["signals"][key]["policies"][p]["bias_mean"]
                    == b["signals"][key]["policies"][p]["bias_mean"])
            assert (a["signals"][key]["policies"][p]["comp_mean"]
                    == b["signals"][key]["policies"][p]["comp_mean"])


# ---------------------------------------------------------------------------
# 2. full-fidelity headline numbers (paper Table 1 settings)
# ---------------------------------------------------------------------------
def test_benign_signals_release_early_at_36_to_39_percent(full):
    clean = full["signals"]["clean"]["policies"]["gated"]
    comp_ = full["signals"]["composition"]["policies"]["gated"]

    # headline: gated completeness 36% (Clean) and 39% (Composition)
    assert round(100 * clean["comp_mean"]) == 36
    assert round(100 * comp_["comp_mean"]) == 39
    assert 0.36 <= clean["comp_mean"] <= 0.39 or abs(clean["comp_mean"] - 0.36) < 0.005
    assert 0.36 <= comp_["comp_mean"] <= 0.39 or abs(comp_["comp_mean"] - 0.39) < 0.005

    # benign classification: |rho_trailing| under the 0.10 threshold
    assert abs(full["signals"]["clean"]["rho_trailing"]) < 0.10
    assert abs(full["signals"]["composition"]["rho_trailing"]) < 0.10
    assert not full["signals"]["clean"]["susceptible"]
    assert not full["signals"]["composition"]["susceptible"]

    # gated matches naive timeliness on benign signals (same release times)
    assert clean["comp_mean"] == pytest.approx(
        full["signals"]["clean"]["policies"]["naive"]["comp_mean"], abs=0.01)


def test_strong_leak_gated_bias_is_exactly_zero_at_full_completeness(full):
    strong = full["signals"]["strong_leak"]
    gated = strong["policies"]["gated"]

    # headline: the gate forces the deadline-complete cross-section ...
    assert gated["comp_mean"] == 1.0
    # ... where the released signal IS the complete-cross-section signal
    assert gated["bias_mean"] == 0.0
    assert gated["flip_mean"] == 0.0

    # the susceptibility that drives the decision (paper value ~ -0.868)
    assert strong["susceptible"]
    assert strong["rho_trailing"] == pytest.approx(-0.868, abs=0.02)

    # contrast: naive release of the same signal is materially biased (~ -0.386)
    naive = strong["policies"]["naive"]
    assert naive["bias_mean"] == pytest.approx(-0.386, abs=0.05)
    assert naive["bias_mean"] < -0.3


def test_mild_leak_intermediate_operating_point(full):
    mild = full["signals"]["mild_leak"]
    assert mild["susceptible"]
    assert mild["rho_trailing"] == pytest.approx(-0.526, abs=0.02)
    gated = mild["policies"]["gated"]
    # paper value: gated waits to ~88% completeness, bias ~ -0.099
    assert round(100 * gated["comp_mean"]) == 88
    assert gated["bias_mean"] == pytest.approx(-0.099, abs=0.02)
    # strictly between the naive and deadline operating points
    naive = mild["policies"]["naive"]
    assert naive["comp_mean"] < gated["comp_mean"] < 1.0
    assert abs(gated["bias_mean"]) < abs(naive["bias_mean"])


def test_deadline_policy_is_always_unbiased(full):
    for key in full["signals"]:
        d = full["signals"][key]["policies"]["deadline"]
        assert d["comp_mean"] == 1.0
        assert d["bias_mean"] == 0.0
        assert d["flip_mean"] == 0.0


def test_kappa_sweep_ordering(full):
    ks = full["kappa_sweep"]
    assert list(ks) == [0.5, 1.0, 2.0]
    comps = [ks[k]["comp_mean"] for k in (0.5, 1.0, 2.0)]
    biases = [ks[k]["bias_mean"] for k in (0.5, 1.0, 2.0)]
    # required completeness (and realized completeness) rises with kappa ...
    assert comps[0] < comps[1] < comps[2] == 1.0
    assert ks[0.5]["phi_req"] < ks[1.0]["phi_req"] <= ks[2.0]["phi_req"] == 1.0
    # ... while the systematic bias shrinks monotonically to exactly zero
    assert abs(biases[0]) > abs(biases[1]) > abs(biases[2]) == 0.0
    # paper values: comp 59% / 83% / 100%
    assert round(100 * comps[0]) == 59
    assert round(100 * comps[1]) == 83


# ---------------------------------------------------------------------------
# component-level sanity
# ---------------------------------------------------------------------------
def test_component_behavior():
    rng = np.random.default_rng(7)
    store = make_group(n=120, c_a=0.0, c_x=0.5, rng=rng)
    assert isinstance(store, AsOfDataStore)
    assert store.n == 120

    mon = CompletenessMonitor()
    assert mon.fraction(store, 1.0) == 1.0
    assert 0.0 <= mon.fraction(store, 0.5) <= 1.0

    # IPW weights: zero for not-yet-arrived, normalized over arrived
    w = PropensityReweighter().weights(store, 0.5)
    m = store.arrived_mask(0.5)
    assert np.all(w[~m] == 0.0)
    assert w[m].sum() == pytest.approx(m.sum())

    # deadline decision releases the complete cross-section
    ctrl = ReleaseController(gate=SusceptibilityGate())
    d = ctrl.decide(store, 1.0, policy="deadline")
    assert d.action == "RELEASE"
    assert d.completeness == 1.0
    assert len(d.values) == store.n

    # early naive decision below the completeness floor withholds
    d0 = ctrl.decide(store, 0.01, policy="naive")
    assert d0.action == "WITHHOLD"
    assert d0.values is None

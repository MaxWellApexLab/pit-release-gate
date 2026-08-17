"""Self-contained synthetic worked example with KNOWN ground truth.

Runs the release controller on simulated staggered-arrival cross-sections
in which the strength of selection on the disturbance (the true leakage
knob) is planted and therefore known exactly. No licensed data required.

Run it with ``python -m pit_release_gate`` or the ``pit-release-gate``
console script.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from .controller import MIN_ENTITIES, ReleaseController, ReleaseDecision, _ols_resid
from .gate import SusceptibilityGate
from .results import (
    SCHEMA,
    SCHEMA_VERSION,
    build_results,
    screen_config,
    summarize_signal,
    write_results,
)
from .reweight import PropensityReweighter
from .store import AsOfDataStore

SEED = 20260601

#: Susceptibility threshold the demo screen runs at (|rho_hat| above it is
#: susceptible). Named so the exported screen record cannot drift from it.
DEMO_RHO_THRESHOLD = 0.10

#: The four planted-truth signal configurations reported in the demo:
#: (key, label, c_a, c_x)
DEMO_SIGNALS = [
    ('clean',       'Clean        (c_a=0.0, c_x=0.3)', 0.0, 0.3),
    ('composition', 'Composition  (c_a=0.0, c_x=2.0)', 0.0, 2.0),   # benign incompleteness (selection on x)
    ('mild_leak',   'Mild-leak    (c_a=0.3, c_x=0.7)', 0.3, 0.7),
    ('strong_leak', 'Strong-leak  (c_a=1.0, c_x=0.7)', 1.0, 0.7),
]

DEMO_POLICIES = ['naive', 'threshold', 'reweight', 'deadline', 'gated']


def make_group(n=120, c_a=0.0, c_x=0.7, b=(0.0, 0.6, -0.4), rng=None) -> AsOfDataStore:
    """One cross-sectional group with staggered arrival.

    c_a = strength of selection ON the disturbance (the true leakage knob);
    c_x = strength of selection on the observable size regressor (composition).
    Larger c_a -> early filers selected on u -> incomplete-cross-section bias.
    """
    rng = rng or np.random.default_rng(SEED)
    size = rng.standard_normal(n)                 # standardized log-size
    x2 = rng.standard_normal(n)                   # placebo regressor (uncorrelated w/ arrival)
    u = rng.standard_normal(n)                    # disturbance == the signal of interest
    X = np.column_stack([np.ones(n), size, x2])
    y = b[0] + b[1] * size + b[2] * x2 + u
    # arrival: earlier (smaller) when c_a*u + c_x*size is larger (big, unusual-u firms file early)
    lat_index = -(c_a * (u - u.mean()) / (u.std() + 1e-9)
                  + c_x * (size - size.mean()) / (size.std() + 1e-9)) \
                + 0.5 * rng.standard_normal(n)
    arrival = rankdata(lat_index) / n             # in (0,1]; 1.0 == deadline
    truth_resid = _ols_resid(X, y)                # complete-cross-section residual (estimand)
    return AsOfDataStore(X=X, y=y, arrival=arrival, size=size, truth_resid=truth_resid)


def flip_and_bias(store: AsOfDataStore, d: ReleaseDecision):
    """How far the released signal departs from the complete-cross-section truth,
    measured ONLY on the entities that were released."""
    if d.values is None or len(d.values) < 6:
        return np.nan, np.nan
    idx = d.entity_idx
    truth = store.truth_resid[idx]
    da = pd.qcut(pd.Series(d.values).rank(method='first'), min(10, len(idx)), labels=False).to_numpy()
    db = pd.qcut(pd.Series(truth).rank(method='first'), min(10, len(idx)), labels=False).to_numpy()
    flip = float((da != db).mean())
    # coefficient bias on the size regressor vs complete-cross-section coef
    m = store.arrived_mask(d.t)
    w = None
    if d.action == 'REWEIGHT_RELEASE':
        w = PropensityReweighter().weights(store, d.t)[m]
    Xs, ys = store.X[m], store.y[m]
    if w is None:
        ba, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
    else:
        sw = np.sqrt(w)
        ba, *_ = np.linalg.lstsq(Xs * sw[:, None], ys * sw, rcond=None)
    bfull, *_ = np.linalg.lstsq(store.X, store.y, rcond=None)
    return flip, float(ba[1] - bfull[1])


def _ci(a):
    """mean and 95% CI half-width across replications (nan-aware)."""
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    if len(a) == 0:
        return np.nan, np.nan
    return float(a.mean()), float(1.96 * a.std(ddof=1) / np.sqrt(len(a)))


def run_demo(n_train=10, n_eval=60, verbose=True) -> dict:
    """HONEST evaluation with known ground truth: the gate's rho_hat is fitted
    on n_train PRIOR COMPLETED periods, then FROZEN and applied to n_eval fresh
    evaluation periods -- no information from the period being gated is used.
    All five policies are reported, with 95% CIs across evaluation periods.

    Returns a dict with per-signal, per-policy summary statistics and the
    kappa sensitivity sweep, so the same numbers the console table shows are
    available programmatically (the test suite consumes this).
    """
    rng = np.random.default_rng(SEED)
    policies = DEMO_POLICIES
    results = {'n_train': n_train, 'n_eval': n_eval, 'signals': {}, 'kappa_sweep': {}}

    if verbose:
        print("=" * 96)
        print("Completeness-Aware Release Controller -- HONEST worked example (known ground truth)")
        print(f"rho_hat fitted on {n_train} prior completed periods, frozen, applied to {n_eval} eval periods.")
        print("at release: comp%=completeness | flip%=decile disagreement vs complete | |biasB|=size-coef bias")
        print("=" * 96)

    for key, name, c_a, c_x in DEMO_SIGNALS:
        # --- honest trailing estimation on prior completed periods ---
        gate = SusceptibilityGate(threshold=DEMO_RHO_THRESHOLD)
        train = [make_group(n=120, c_a=c_a, c_x=c_x, rng=rng) for _ in range(n_train)]
        rho_tr = gate.fit_trailing(train)
        ctrl = ReleaseController(gate=gate)
        # the settings that produced the verdicts, recorded for --export
        # (identical for every signal; the kappa sweep below is separate)
        results['config'] = screen_config(rho_threshold=gate.threshold,
                                          phi_min=ctrl.phi_min,
                                          kappa=ctrl.suscept_slope,
                                          trailing_k=n_train,
                                          min_entities=MIN_ENTITIES)
        # --- evaluation on fresh periods, gated with the FROZEN estimate ---
        agg = {p: {'comp': [], 'flip': [], 'bias': [], 'act': []} for p in policies}
        rho_realized = []
        for _ in range(n_eval):
            store = make_group(n=120, c_a=c_a, c_x=c_x, rng=rng)
            rho_realized.append(gate._rho_one_period(store))  # ex-post, reporting only
            for p in policies:
                d = ctrl.run_until_release(store, policy=p)
                flip, bias = flip_and_bias(store, d)
                agg[p]['comp'].append(d.completeness)
                agg[p]['flip'].append(flip)
                agg[p]['bias'].append(bias)   # SIGNED: mean over reps isolates SYSTEMATIC bias; finite-sample noise shows in flip%
                agg[p]['act'].append(d.policy or d.action)

        sig = {'label': name, 'c_a': c_a, 'c_x': c_x,
               'rho_trailing': rho_tr,
               'rho_realized': [float(r) for r in rho_realized],
               'rho_realized_mean': float(np.mean(rho_realized)),
               'rho_realized_std': float(np.std(rho_realized)),
               # constant across periods: the gate runs on the FROZEN estimate
               'phi_req': ctrl.required_completeness(rho_tr),
               'susceptible': bool(gate.is_susceptible(rho_tr)),
               'policies': {}}
        for p in policies:
            cm, ch = _ci(agg[p]['comp'])
            fm, fh = _ci(agg[p]['flip'])
            bm, bh = _ci(agg[p]['bias'])  # bm = systematic bias
            route = pd.Series(agg[p]['act']).mode().iat[0]
            sig['policies'][p] = {'comp_mean': cm, 'comp_ci': ch,
                                  'flip_mean': fm, 'flip_ci': fh,
                                  'bias_mean': bm, 'bias_ci': bh,
                                  'route': route}
        results['signals'][key] = sig

        if verbose:
            print(f"\n{name}   rho_trailing={rho_tr:+.3f} (fitted ex ante)  "
                  f"realized per-period rho: {np.mean(rho_realized):+.3f}±{np.std(rho_realized):.3f}  "
                  f"({'SUSCEPTIBLE -> wait' if gate.is_susceptible(rho_tr) else 'benign -> release early'})")
            print(f"  {'policy':<10} {'comp% [95%CI]':>16} {'flip% [95%CI]':>16} {'biasB(signed) [CI]':>20}   route")
            for p in policies:
                s = sig['policies'][p]
                tag = '  <-- gated' if p == 'gated' else ''
                print(f"  {p:<10} {100*s['comp_mean']:7.0f} ±{100*s['comp_ci']:4.1f}  "
                      f"{100*s['flip_mean']:8.1f} ±{100*s['flip_ci']:4.1f}  "
                      f"{s['bias_mean']:+9.3f} ±{s['bias_ci']:5.3f}   {s['route']}{tag}")

    # --- sensitivity of the policy knob: kappa sweep on Mild-leak ---
    if verbose:
        print("\n" + "-" * 96)
        print("Sensitivity: required-completeness slope kappa on Mild-leak (c_a=0.3, c_x=0.7)")
    gate = SusceptibilityGate(threshold=DEMO_RHO_THRESHOLD)
    train = [make_group(n=120, c_a=0.3, c_x=0.7, rng=rng) for _ in range(n_train)]
    rho_tr = gate.fit_trailing(train)
    for kappa in [0.5, 1.0, 2.0]:
        ctrl = ReleaseController(gate=gate, suscept_slope=kappa)
        comps, biases = [], []
        for _ in range(n_eval):
            store = make_group(n=120, c_a=0.3, c_x=0.7, rng=rng)
            d = ctrl.run_until_release(store, policy='gated')
            _, b = flip_and_bias(store, d)
            comps.append(d.completeness)
            biases.append(b)
        cm, ch = _ci(comps)
        bm, bh = _ci(biases)
        phi_req = float(min(1.0, 0.35 + kappa * abs(rho_tr)))
        results['kappa_sweep'][kappa] = {'phi_req': phi_req,
                                         'rho_trailing': rho_tr,
                                         'comp_mean': cm, 'comp_ci': ch,
                                         'bias_mean': bm, 'bias_ci': bh}
        if verbose:
            print(f"  kappa={kappa:3.1f}: phi_req={phi_req:.2f}  "
                  f"comp {100*cm:5.0f}%±{100*ch:.1f}  biasB {bm:+.3f}±{bh:.3f}")

    if verbose:
        print("\n" + "=" * 88)
        print("READING:")
        print("  * 'deadline' is always unbiased (|biasB|~0) but releases latest (comp~100%) for ALL")
        print("    signals -- a blanket timeliness penalty.")
        print("  * 'naive' releases earliest but is biased exactly when rho_hat is large (Strong-leak).")
        print("  * Selection on an OBSERVABLE (Composition row) does NOT bias OLS (|biasB|~0 even for")
        print("    naive) and yields rho_hat~0 -- the gate correctly treats it as benign and releases")
        print("    early, rather than over-withholding benign incompleteness.")
        print("  * 'gated' sets a PER-SIGNAL required completeness from rho_hat: it matches 'naive'")
        print("    timeliness on benign signals and rises toward 'deadline' (low bias) on genuinely")
        print("    susceptible signals -- preventing release of leakage-biased incomplete cross-")
        print("    sections WITHOUT a blanket timeliness penalty. (IPW reweighting cannot fix")
        print("    selection-on-disturbance and is offered only as an optional composition-correction")
        print("    module; the gate grades on completeness, which is what actually suppresses the bias.)")
        print("=" * 88)

    return results


def demo(n_train=10, n_eval=60):
    """Print the full known-truth worked example (console table)."""
    return run_demo(n_train=n_train, n_eval=n_eval, verbose=True)


def results_from_demo(run: dict, date: str = None) -> dict:
    """Reduce a :func:`run_demo` result to a ``pit-screen-results`` record.

    Only summary statistics survive the reduction: per signal, the number of
    screened periods, how many of them the susceptibility measure flagged,
    the mean and maximum |rho_hat|, the required completeness the controller
    assigned, and the verdict. The simulated cross-sections themselves stay
    on this machine.

    ``date`` is optional and caller-supplied; nothing here reads a clock, so
    the same screen always reduces to the same record.
    """
    threshold = run['config']['rho_threshold']
    signals = [
        summarize_signal(
            key,
            rhos=sig['rho_realized'],
            phi_reqs=[sig['phi_req']] * len(sig['rho_realized']),
            rho_threshold=threshold,
            # the verdict the screen actually acted on: the frozen trailing
            # estimate, not the ex-post realized ones summarized above
            susceptible=sig['susceptible'],
        )
        for key, sig in run['signals'].items()
    ]
    return build_results(signals, run['config'], date=date)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='pit-release-gate',
        description='Run the self-contained known-ground-truth demo of the '
                    'completeness-aware release controller.',
        epilog='This tool never reports anything, anywhere. --export writes a '
               'local file and makes no network call; the package opens no '
               'socket at all.')
    ap.add_argument('--train', type=int, default=10,
                    help='number of prior completed periods used to fit rho_hat (default 10)')
    ap.add_argument('--eval', dest='n_eval', type=int, default=60,
                    help='number of fresh evaluation periods (default 60)')
    ap.add_argument('--export', metavar='PATH',
                    help=f'write the screen result to PATH as a {SCHEMA} '
                         f'v{SCHEMA_VERSION} JSON record (fully offline)')
    a = ap.parse_args(argv)

    run = run_demo(n_train=a.train, n_eval=a.n_eval, verbose=True)
    if not a.export:
        return

    record = results_from_demo(run)
    path = write_results(record, a.export)
    print(f'\nwrote {SCHEMA} v{SCHEMA_VERSION} to {path} '
          f'(local file only -- no network call was made)')


if __name__ == '__main__':
    main()

# pit-release-gate

[![CI](https://github.com/MaxWellApexLab/pit-release-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/MaxWellApexLab/pit-release-gate/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/MaxWellApexLab/pit-release-gate/branch/master/graph/badge.svg)](https://codecov.io/gh/MaxWellApexLab/pit-release-gate)
[![PyPI](https://img.shields.io/pypi/v/pit-release-gate)](https://pypi.org/project/pit-release-gate/)
[![Python](https://img.shields.io/pypi/pyversions/pit-release-gate)](https://pypi.org/project/pit-release-gate/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Completeness-aware release control for staggered-arrival cross-sectional data.

When the entities of a cross-section report on staggered dates — companies filing
financial statements are the canonical case — any same-period cross-sectional signal
computed before the last filer arrives is estimated from an incomplete, and possibly
*selectively* incomplete, cross-section. If filing timing depends on the very
disturbance the signal measures, releasing early produces a systematic bias
(incomplete-cross-section leakage), while a blanket wait-for-the-deadline rule removes
the bias at a timeliness cost paid by every signal, biased or not. `pit-release-gate`
measures each signal's susceptibility to this bias — a disturbance-conditional partial
correlation fitted honestly on prior *completed* periods — and grades the required
completeness per signal, so benign signals release early and susceptible signals are
withheld until enough of the cross-section has arrived to suppress the bias.

## Statement of need

Point-in-time discipline in ML pipelines currently rests on tooling that answers one
question: *was this value readable at time t?* Feature-store as-of joins, bitemporal
and vintage-aware storage, and purged or embargoed cross-validation all enforce
read-time correctness, and they do it well.

None of them answers a second question: given that every value read was legitimately
readable, was the *set* of entities that had reported by t a selected sample? An
as-of join over an incomplete cross-section is a correct join over a biased sample.
The two failures need different remedies — the first is fixed by timestamp hygiene,
the second only by waiting or by an explicit correction. Researchers building
cross-sectional signals on staggered-arrival panels have had no routine, per-signal
screen for the second. `pit-release-gate` is that screen, plus the release controller
that acts on it: one `fit_trailing` call per signal, so reporting a susceptibility
estimate alongside a released signal costs about as much as reporting a standard
error.

## Install

```bash
pip install pit-release-gate
```

Requires Python 3.10+ (`numpy`, `pandas`, `scipy`).

## Quickstart (30 seconds)

```python
import numpy as np
from pit_release_gate import SusceptibilityGate, ReleaseController, make_group

rng = np.random.default_rng(0)

# 1. Fit the susceptibility gate on prior COMPLETED periods (honest estimation:
#    never on the period being gated — its cross-section is still incomplete).
train = [make_group(c_a=0.3, c_x=0.7, rng=rng) for _ in range(10)]
gate = SusceptibilityGate(threshold=0.10)
rho = gate.fit_trailing(train)

# 2. Gate a fresh, live period with the frozen estimate.
controller = ReleaseController(gate=gate)
live = make_group(c_a=0.3, c_x=0.7, rng=rng)
decision = controller.run_until_release(live, policy="gated")

print(f"rho_hat={rho:+.3f}  ->  {decision.action} "
      f"at completeness {decision.completeness:.0%} ({decision.policy})")
```

To gate your own data, build an `AsOfDataStore` from your design matrix, signal
values, and per-entity filing-arrival times, then call
`ReleaseController.decide(store, t)` at each evaluation time — it returns
`WITHHOLD`, `REWEIGHT_RELEASE`, or `RELEASE` plus the released values.

## API overview

Five public components, all importable from the top-level `pit_release_gate` package:

| component | what it does |
|---|---|
| [`AsOfDataStore`](src/pit_release_gate/store.py) | Holds one period's as-filed records for a cross-sectional group: design matrix, signal values, and a filing-arrival time per entity. |
| [`CompletenessMonitor`](src/pit_release_gate/monitor.py) | Reports the arrived fraction at an evaluation time, plus a composition-shift gauge for the arrived subset. |
| [`SusceptibilityGate`](src/pit_release_gate/gate.py) | Estimates ρ̂, the partial correlation between filing latency and the complete-cross-section residual given observables. `fit_trailing` enforces the honest-estimation contract: prior *completed* periods only. |
| [`PropensityReweighter`](src/pit_release_gate/reweight.py) | Inverse-filing-propensity weights. Included to make a negative result executable: reweighting on observables corrects composition, but cannot remove selection on the disturbance. |
| [`ReleaseController`](src/pit_release_gate/controller.py) | Maps \|ρ̂\| to a required completeness `φ_req = min(1, φ_min + κ·\|ρ̂\|)` and returns `WITHHOLD` / `REWEIGHT_RELEASE` / `RELEASE` at each evaluation time. |

`make_group`, `run_demo` and `demo` ([`simulate.py`](src/pit_release_gate/simulate.py))
generate and run the known-ground-truth worked example described below.

## The known-ground-truth demo

The package ships a self-contained worked example with a *planted* leakage strength,
so the right answer is known exactly and no licensed data is needed:

```bash
pit-release-gate            # or: python -m pit_release_gate
```

It compares five release policies (`naive`, `threshold`, `reweight`, `deadline`,
`gated`) on four signal types. Headline behavior:

| signal | susceptibility ρ̂ | gated releases at | gated bias |
|---|---|---|---|
| Clean | ≈ +0.005 (benign) | **36%** completeness | ≈ 0 |
| Composition (selection on observables only) | ≈ −0.036 (benign) | **39%** completeness | ≈ 0 |
| Mild leak | ≈ −0.53 | 88% completeness | −0.099 (naive: −0.319) |
| Strong leak | ≈ −0.87 | 100% (deadline) | **exactly 0.0** (naive: −0.386) |

A sensitivity sweep of the policy slope κ shows the timeliness–bias dial:
κ = 0.5 → release at 59% completeness (bias −0.229); κ = 1.0 → 83% (−0.118);
κ = 2.0 → 100% (bias exactly 0). The demo is deterministic (fixed seed), and
`tests/test_reproduces_paper.py` asserts these numbers.

## Papers

The method and its evaluation are developed in three public papers:

1. **Correct-by-Construction Factor Computation: A Verifiably Point-in-Time Engine
   for Tradeable Signals** — [doi:10.6084/m9.figshare.32952482](https://doi.org/10.6084/m9.figshare.32952482)
2. **Measuring Incomplete-Cross-Section Leakage: A Matched Placebo, a Susceptibility
   Screen, and Evidence from Taiwan and US As-Filed Data** — [doi:10.6084/m9.figshare.33061955](https://doi.org/10.6084/m9.figshare.33061955)
3. **Susceptibility-Graded Release Control: Preventing Incomplete-Cross-Section
   Leakage in Financial Machine-Learning Pipelines without a Blanket Timeliness
   Penalty** — [doi:10.6084/m9.figshare.33158615](https://doi.org/10.6084/m9.figshare.33158615)

This package is the reference implementation of paper 3's release controller; its
demo reproduces the paper's controlled experiment.

## Badge

If you have run the susceptibility screen on your own data — whatever the result — you
are welcome to say so:

```markdown
[![screened with pit-release-gate](https://img.shields.io/badge/screened%20with-pit--release--gate-blue)](https://github.com/MaxWellApexLab/pit-release-gate)
```

The badge reads **screened with**, not *passed* — it states that the screen was run, the
same way a formatter badge states that the formatter was run. A benign result and a
susceptible result are equally worth badging; the second one arguably more, because it
means the screen found something and your pipeline now waits for it.

**Make it point at something.** A badge is worth reading only if there is evidence behind
it. Commit your screen output — which signals came out benign, which came out susceptible,
and the required completeness each was assigned — and link the badge at that file rather
than at this repo. A worked example is the OSAP screen in the
[PIT audit registry](https://github.com/MaxWellApexLab/pit-audit-registry/blob/main/audits/2026-08_osap/report.md).

**Related:** the [PIT Hygiene pledge](https://github.com/MaxWellApexLab/pit-hygiene) is a
broader, tool-neutral statement about how a staggered-arrival pipeline is built; this badge
is the narrower statement that this particular screen was run.

## Cite this

See [`CITATION.cff`](CITATION.cff). If you use this software, please cite paper 3:

```bibtex
@article{wu2026releasecontrol,
  title  = {Susceptibility-Graded Release Control: Preventing Incomplete-Cross-Section
            Leakage in Financial Machine-Learning Pipelines without a Blanket
            Timeliness Penalty},
  author = {Wu, Kuan-Ta and Wu, Kuan-I},
  year   = {2026},
  doi    = {10.6084/m9.figshare.33158615}
}
```

## Community guidelines

- **Report a bug or request a feature:** open an issue at
  [github.com/MaxWellApexLab/pit-release-gate/issues](https://github.com/MaxWellApexLab/pit-release-gate/issues).
- **Contribute:** see [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup,
  test requirements, and pull-request process.
- **Get help:** open an issue with a minimal reproducing example, or email
  maxwellapexlab@proton.me.

## License

MIT — see [LICENSE](LICENSE).

Patent pending: this software implements techniques described in pending U.S.
patent applications. The MIT license above governs use of this code.

---

Max Well Apex LLC — maxwellapexlab@proton.me

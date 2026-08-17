---
title: 'pit-release-gate: completeness-aware release control for staggered-arrival cross-sectional data'
tags:
  - Python
  - data leakage
  - point-in-time data
  - machine learning pipelines
  - quantitative finance
authors:
  - name: Kuan-Ta Wu
    orcid: 0009-0006-0529-8709
    affiliation: 1
affiliations:
  - name: Max Well Apex LLC, NY, United States
    index: 1
date: 1 September 2026
bibliography: paper.bib
---

# Summary

Many empirical cross-sections are assembled from records that arrive on staggered
dates. Companies filing quarterly financial statements are the canonical case: a
fiscal period ends on a single date, but individual filings land over the following
weeks, up to a statutory deadline. Any same-period cross-sectional signal computed
before the last filer has arrived is therefore estimated from an incomplete
cross-section. Incompleteness is harmless when arrival timing is unrelated to what
the signal measures. It is not harmless when filing timing depends on the very
disturbance the signal is meant to capture: the early-arriving subset is then
selected on the estimand itself, and the released signal carries a systematic bias.
The standard defence — wait for the deadline before releasing anything — removes
the bias but charges a timeliness penalty to every signal, including those that
were never at risk.

`pit-release-gate` replaces that blanket rule with a per-signal measurement. It
estimates each signal's susceptibility to this bias — a disturbance-conditional
partial correlation, fitted only on prior *completed* periods — and converts the
estimate into the cross-sectional completeness that the signal must reach before it
may be released. Benign signals release as soon as a minimum completeness floor is
met; susceptible signals are withheld until enough of the cross-section has arrived
to suppress the bias, up to the deadline.

# Statement of need

Point-in-time discipline in machine-learning pipelines currently rests on tooling
that answers one question: *was this value readable at time $t$?* Feature-store
as-of joins, bitemporal and vintage-aware storage, and purged or embargoed
cross-validation all enforce read-time correctness, and they do it well.

None of them answers a second question: given that every value read was legitimately
readable, was the *set* of entities that had reported by $t$ a selected sample? An
as-of join over an incomplete cross-section is a correct join over a biased sample.
The distinction matters because the two failures need different remedies — the
first is fixed by timestamp hygiene, the second only by waiting or by an explicit
correction. Existing leakage taxonomies [@kaufman2012] and recent surveys of leakage
in machine-learning-based science [@kapoor2023] name this family of problems, and
the mechanism is a selection problem in the classical sense [@heckman1979], but
researchers have had no routine, per-signal screen they can execute inside a
pipeline.

`pit-release-gate` provides one. The susceptibility measure, the grading rule that
turns it into a release threshold, and their evaluation on as-filed data are
developed in three publicly available preprints [@wu2026a; @wu2026b; @wu2026c]; this
package is the reference implementation of the release controller of the third. It
is aimed at researchers who build cross-sectional signals on staggered-arrival
panels — most immediately in empirical accounting and quantitative finance, but the
same arrival structure appears wherever administrative records backfill after a
reporting period closes. The design goal is that the screen costs one function call
per signal, so that reporting a susceptibility estimate alongside a released signal
becomes as ordinary as reporting a standard error.

# Functionality

The public API has five components:

- `AsOfDataStore` holds the as-filed records for one period and cross-sectional
  group: a design matrix, the constructed signal values, and a filing-arrival time
  per entity.
- `CompletenessMonitor` reports the arrived fraction at an evaluation time, plus a
  composition-shift gauge for the arrived subset.
- `SusceptibilityGate` estimates $\hat{\rho}$, the partial correlation between
  filing latency and the complete-cross-section residual, conditional on
  observables. Its `fit_trailing` method enforces an honest-estimation contract:
  $\hat{\rho}$ is fitted on prior completed periods only, never on the period being
  gated, whose cross-section is by definition still incomplete.
- `PropensityReweighter` supplies inverse-filing-propensity weights. It is included
  to make a negative result executable: reweighting on observables corrects
  composition shift but cannot remove selection on the disturbance, which is why the
  controller grades on completeness rather than on reweighting.
- `ReleaseController` maps $|\hat{\rho}|$ to a required completeness,
  $\varphi_{\mathrm{req}} = \min(1,\ \varphi_{\min} + \kappa|\hat{\rho}|)$, and
  returns at each evaluation time one of `WITHHOLD`, `REWEIGHT_RELEASE` or
  `RELEASE`, together with the released values.

The package ships a self-contained worked example in which the strength of selection
on the disturbance is *planted*, so the correct decision is known exactly and no
licensed data is required. Running `pit-release-gate` compares five release policies
across four signal types and prints the resulting timeliness and bias. The run is
deterministic under a fixed seed and the test suite asserts its headline numbers, so
a reader can confirm in one command that the gate releases benign signals at roughly
a third of the cross-section, while holding a strongly selected signal to the
complete cross-section, where its bias is exactly zero.

Installation is `pip install pit-release-gate`. The package requires Python 3.10 or
later and depends only on NumPy, pandas and SciPy; it is MIT licensed and tested on
Linux and Windows against Python 3.10 and 3.13.

# Acknowledgements

The methodology preprints cited above are co-authored with Kuan-I Wu; the software
described here was designed and written solely by the author. The author used
AI-assisted drafting tools in preparing this manuscript; all technical content,
experiments, and claims were designed, executed, and verified by the author.

# References

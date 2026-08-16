# Changelog

## 0.1.0 — 2026-08-15

First public release.

- Susceptibility screen: disturbance-conditional partial correlation (rho-hat),
  fitted on prior completed periods and frozen before gating.
- Graded release controller: per-signal required completeness
  `phi_req = min(1, phi_min + kappa * |rho_hat|)`, with naive / fixed-threshold /
  IPW-reweight / statutory-deadline baselines.
- Self-contained known-ground-truth demo (`pit-release-gate`), deterministic,
  reproducing the controlled experiment of doi:10.6084/m9.figshare.33158615.
- Test suite asserting the paper's headline numbers.

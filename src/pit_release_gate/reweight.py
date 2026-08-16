"""Reconstruction module: inverse-propensity / size-kernel reweighting.

Reweighting on observables corrects covariate-composition shift in the
arrived subset, but it cannot remove selection on the disturbance --
that is why the release controller grades on completeness rather than
on IPW (see :mod:`pit_release_gate.controller`).
"""
from __future__ import annotations

import numpy as np

from .store import AsOfDataStore


def _logistic_p(Xc: np.ndarray, yb: np.ndarray, iters: int = 50) -> np.ndarray:
    """Ridge-logistic P(arrived|x); Xc includes an intercept column."""
    n, k = Xc.shape
    w = np.zeros(k)
    lam = 1e-3
    for _ in range(iters):
        z = Xc @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = Xc.T @ (p - yb) + lam * w
        S = p * (1 - p)
        H = (Xc * S[:, None]).T @ Xc + lam * np.eye(k)
        try:
            w -= np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
    z = Xc @ w
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class PropensityReweighter:
    """Fits P(arrived|x) and returns per-entity weights so that a
    reweighted estimate over the ARRIVED entities approximates the
    complete-cross-section estimate (Horvitz-Thompson / IPW)."""

    def weights(self, store: AsOfDataStore, t: float) -> np.ndarray:
        m = store.arrived_mask(t)
        arrived = m.astype(float)
        Xp = np.column_stack([np.ones(store.n), store.size])
        p = _logistic_p(Xp, arrived)
        p = np.clip(p, 1e-3, 1 - 1e-3)
        w = np.zeros(store.n)
        w[m] = 1.0 / p[m]          # inverse filing propensity on arrived units
        w[m] *= m.sum() / w[m].sum()  # normalize to arrived count
        return w

"""Susceptibility gate: disturbance-conditional dependence measure."""
from __future__ import annotations

import numpy as np
from scipy.stats import rankdata

from .store import AsOfDataStore


class SusceptibilityGate:
    """Computes rho_hat = partial corr( filing latency , complete residual | x ),
    the single primitive that scales the leakage bias, and compares
    |rho_hat| to a stored threshold.

    HONEST-ESTIMATION CONTRACT: at release time the current period's
    cross-section is incomplete, so rho_hat must NEVER be computed from
    the period being gated. Production use: call fit_trailing() on K
    prior COMPLETED periods (their residuals are legitimately available)
    and gate the live period with the stored estimate."""

    def __init__(self, threshold: float = 0.10):
        self.threshold = threshold
        self.rho_trailing: float = None   # estimate from prior completed periods

    def _rho_one_period(self, store: AsOfDataStore) -> float:
        """rho_hat on ONE completed period (only valid ex post)."""
        u = store.truth_resid
        lat = rankdata(store.arrival) / store.n
        Xp = np.column_stack([np.ones(store.n), store.size])
        bl, *_ = np.linalg.lstsq(Xp, lat, rcond=None)
        rl = lat - Xp @ bl
        bu, *_ = np.linalg.lstsq(Xp, u, rcond=None)
        ru = u - Xp @ bu
        if rl.std() < 1e-9 or ru.std() < 1e-9:
            return 0.0
        return float(np.corrcoef(rl, ru)[0, 1])

    def fit_trailing(self, completed_periods: list) -> float:
        """Pool rho_hat over K prior COMPLETED periods; store for live gating."""
        rs = [self._rho_one_period(s) for s in completed_periods]
        self.rho_trailing = float(np.mean(rs))
        return self.rho_trailing

    def rho_hat(self, store: AsOfDataStore) -> float:
        """Rho used at gating time: the trailing estimate if fitted (honest),
        else the same-period value (ORACLE -- for upper-bound analysis only)."""
        if self.rho_trailing is not None:
            return self.rho_trailing
        return self._rho_one_period(store)

    def is_susceptible(self, rho: float) -> bool:
        return abs(rho) > self.threshold

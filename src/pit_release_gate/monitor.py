"""Completeness monitoring for a staggered-arrival cross-section."""
from __future__ import annotations

import numpy as np

from .store import AsOfDataStore


class CompletenessMonitor:
    """Tracks what fraction of a cross-sectional group has filed by a
    given evaluation time, plus a composition-shift gauge."""

    def fraction(self, store: AsOfDataStore, t: float) -> float:
        return float(store.arrived_mask(t).mean())

    def covariate_shift(self, store: AsOfDataStore, t: float) -> float:
        """Standardized mean difference of the size regressor between the
        arrived subset and the full cross-section -- a composition-shift
        gauge the controller can log."""
        m = store.arrived_mask(t)
        if m.sum() < 2:
            return np.inf
        full_sd = store.size.std() + 1e-9
        return abs(store.size[m].mean() - store.size.mean()) / full_sd

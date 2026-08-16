"""As-of data store for staggered-arrival cross-sectional records."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class AsOfDataStore:
    """Holds, for each entity in a cross-sectional group and one fiscal
    period, an as-filed record tagged with a filing-arrival timestamp
    and construction regressors (including a size regressor)."""

    X: np.ndarray          # (n, k) design matrix incl. intercept col 0; col 1 = size regressor
    y: np.ndarray          # (n,)   construction-recipe value (e.g. scaled accruals)
    arrival: np.ndarray    # (n,)   filing-arrival time in [0, 1] (1 = statutory deadline)
    size: np.ndarray       # (n,)   standardized log-size (the observable composition driver)
    truth_resid: np.ndarray = field(default=None)  # complete-cross-section residual (the estimand)

    @property
    def n(self) -> int:
        return len(self.y)

    def arrived_mask(self, t: float) -> np.ndarray:
        """Entities whose filing has arrived by evaluation time t."""
        return self.arrival <= t

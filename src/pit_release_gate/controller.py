"""Release controller: the automated withhold / reweight / release gate."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .gate import SusceptibilityGate
from .monitor import CompletenessMonitor
from .reweight import PropensityReweighter
from .store import AsOfDataStore

#: Minimum number of arrived entities before anything is released; below it a
#: cross-section is too small for the residualization to mean much. Named here
#: so a screen record can report the floor it ran under.
MIN_ENTITIES = 6


def _ols_resid(X: np.ndarray, y: np.ndarray, w: np.ndarray = None) -> np.ndarray:
    if w is None:
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
    else:
        sw = np.sqrt(w)
        b, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    return y - X @ b


@dataclass
class ReleaseDecision:
    action: str            # 'WITHHOLD' | 'RELEASE' | 'REWEIGHT_RELEASE'
    t: float
    completeness: float
    values: np.ndarray = None      # emitted signal for arrived entities (None if withheld)
    entity_idx: np.ndarray = None  # which entities the values correspond to
    policy: str = ''


class ReleaseController:
    """Decides, at evaluation time t, whether to WITHHOLD a same-period
    cross-sectional signal or to RELEASE (optionally after IPW
    reconstruction), gated by the susceptibility measure, a completeness
    floor, and a statutory deadline."""

    def __init__(self, phi_min=0.35, phi_high=0.90, suscept_slope=1.0,
                 gate: SusceptibilityGate = None,
                 reweighter: PropensityReweighter = None,
                 monitor: CompletenessMonitor = None):
        self.phi_min = phi_min          # min completeness before any early release
        self.phi_high = phi_high        # completeness threshold for "release as complete"
        self.suscept_slope = suscept_slope  # how fast the required completeness rises with |rho_hat|
        self.gate = gate or SusceptibilityGate()
        self.reweighter = reweighter or PropensityReweighter()
        self.monitor = monitor or CompletenessMonitor()

    def required_completeness(self, rho: float) -> float:
        """Susceptibility-graded completeness threshold (the timeliness-bias
        frontier operating point). |rho_hat|~0 -> release at phi_min;
        high |rho_hat| -> approach 1.0 (wait for the deadline-complete
        cross-section). Only completeness suppresses selection-on-disturbance
        bias; reweighting observables cannot, which is why the gate grades on
        completeness, not on IPW."""
        return float(min(1.0, self.phi_min + self.suscept_slope * abs(rho)))

    def _emit(self, store, t, mask, w, action, policy):
        vals = _ols_resid(store.X[mask], store.y[mask],
                          None if w is None else w[mask])
        return ReleaseDecision(action=action, t=t,
                               completeness=float(mask.mean()),
                               values=vals, entity_idx=np.where(mask)[0],
                               policy=policy)

    def decide(self, store: AsOfDataStore, t: float, policy: str = 'gated') -> ReleaseDecision:
        m = store.arrived_mask(t)
        comp = self.monitor.fraction(store, t)

        # fixed baseline policies (for comparison / fallback configs) ----
        if policy == 'naive':
            if comp < self.phi_min or m.sum() < MIN_ENTITIES:
                return ReleaseDecision('WITHHOLD', t, comp, policy=policy)
            return self._emit(store, t, m, None, 'RELEASE', policy)
        if policy == 'threshold':
            if comp < self.phi_high or m.sum() < MIN_ENTITIES:
                return ReleaseDecision('WITHHOLD', t, comp, policy=policy)
            return self._emit(store, t, m, None, 'RELEASE', policy)
        if policy == 'deadline':
            if t < 1.0:
                return ReleaseDecision('WITHHOLD', t, comp, policy=policy)
            return self._emit(store, t, m, None, 'RELEASE', policy)
        if policy == 'reweight':
            if comp < self.phi_min or m.sum() < MIN_ENTITIES:
                return ReleaseDecision('WITHHOLD', t, comp, policy=policy)
            w = self.reweighter.weights(store, t)
            return self._emit(store, t, m, w, 'REWEIGHT_RELEASE', policy)

        # ---- susceptibility-GRADED completeness gate (the 'gated' policy) ----
        # The disturbance-conditional susceptibility rho_hat sets a per-signal
        # required completeness. Benign signals (rho_hat~0) release at phi_min
        # (full timeliness); susceptible signals must wait until enough of the
        # cross-section has arrived to suppress the selection-on-disturbance
        # bias, up to the statutory deadline (completeness=1.0).
        rho = self.gate.rho_hat(store)
        phi_req = self.required_completeness(rho)
        if (comp >= phi_req or t >= 1.0) and m.sum() >= MIN_ENTITIES:
            return self._emit(store, t, m, None, 'RELEASE', f'gated(phi_req={phi_req:.2f})')
        return ReleaseDecision('WITHHOLD', t, comp, policy=f'gated(phi_req={phi_req:.2f})')

    def run_until_release(self, store: AsOfDataStore, policy: str = 'gated',
                          grid=None) -> ReleaseDecision:
        """Advance evaluation time over a grid; return the first non-withheld decision."""
        if grid is None:
            grid = np.unique(np.concatenate([store.arrival, [1.0]]))
        last = None
        for t in grid:
            d = self.decide(store, float(t), policy)
            last = d
            if d.action != 'WITHHOLD':
                return d
        return last  # may be a final WITHHOLD if never releasable

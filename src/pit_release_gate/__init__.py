"""pit-release-gate: completeness-aware release control for
staggered-arrival cross-sectional data.

The package ingests records that arrive on staggered dates and, for each
cross-sectional signal at each evaluation time, emits one of three
decisions -- WITHHOLD / REWEIGHT-AND-RELEASE / RELEASE -- so that a
cross-sectionally incomplete (and therefore potentially leakage-biased)
signal is never handed to a downstream trading or training stage.

Public API
----------
AsOfDataStore        staggered-arrival records for one (period, group)
CompletenessMonitor  arrived-fraction and composition-shift gauges
PropensityReweighter optional IPW composition-correction module
SusceptibilityGate   disturbance-conditional dependence measure rho_hat
ReleaseController    the automated withhold / reweight / release gate
ReleaseDecision      the controller's per-evaluation-time output record
make_group           one synthetic staggered-arrival cross-section (known truth)
run_demo             the full known-ground-truth worked example (returns dict)
demo                 same, console-table form
"""
from .controller import ReleaseController, ReleaseDecision
from .gate import SusceptibilityGate
from .monitor import CompletenessMonitor
from .reweight import PropensityReweighter
from .simulate import DEMO_POLICIES, DEMO_SIGNALS, SEED, demo, main, make_group, run_demo
from .store import AsOfDataStore

__version__ = "0.1.1"

__all__ = [
    "AsOfDataStore",
    "CompletenessMonitor",
    "PropensityReweighter",
    "SusceptibilityGate",
    "ReleaseController",
    "ReleaseDecision",
    "make_group",
    "run_demo",
    "demo",
    "main",
    "SEED",
    "DEMO_SIGNALS",
    "DEMO_POLICIES",
    "__version__",
]

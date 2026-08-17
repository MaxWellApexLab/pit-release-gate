"""pit-release-gate: completeness-aware release control for
staggered-arrival cross-sectional data.

The package ingests records that arrive on staggered dates and, for each
cross-sectional signal at each evaluation time, emits one of three
decisions -- WITHHOLD / REWEIGHT-AND-RELEASE / RELEASE -- so that a
cross-sectionally incomplete (and therefore potentially leakage-biased)
signal is never handed to a downstream trading or training stage.

Public API
----------
screen_dataframe     screen a long table (pandas/polars/dict) -> results record
stores_from_frame    the per-period stores that screen builds, for inspection
AsOfDataStore        staggered-arrival records for one (period, group)
CompletenessMonitor  arrived-fraction and composition-shift gauges
PropensityReweighter optional IPW composition-correction module
SusceptibilityGate   disturbance-conditional dependence measure rho_hat
ReleaseController    the automated withhold / reweight / release gate
ReleaseDecision      the controller's per-evaluation-time output record
make_group           one synthetic staggered-arrival cross-section (known truth)
run_demo             the full known-ground-truth worked example (returns dict)
demo                 same, console-table form
build_results        assemble a pit-screen-results record (summary stats only)
validate_results     check such a record; returns a list of problems
badge_snippet        README badge markdown for a completed screen run
"""
# defined first: results.tool_version() reads it while the submodules below
# are still importing
__version__ = "0.1.1"

from .controller import ReleaseController, ReleaseDecision
from .frame import screen_dataframe, stores_from_frame
from .gate import SusceptibilityGate
from .monitor import CompletenessMonitor
from .results import (
    SCHEMA,
    SCHEMA_VERSION,
    build_results,
    screen_config,
    summarize_signal,
    validate_results,
    write_results,
)
from .reweight import PropensityReweighter
from .simulate import (
    DEMO_POLICIES,
    DEMO_SIGNALS,
    SEED,
    badge_snippet,
    demo,
    main,
    make_group,
    results_from_demo,
    run_demo,
)
from .store import AsOfDataStore

__all__ = [
    "AsOfDataStore",
    "screen_dataframe",
    "stores_from_frame",
    "CompletenessMonitor",
    "PropensityReweighter",
    "SusceptibilityGate",
    "ReleaseController",
    "ReleaseDecision",
    "make_group",
    "run_demo",
    "demo",
    "main",
    "badge_snippet",
    "SEED",
    "DEMO_SIGNALS",
    "DEMO_POLICIES",
    "SCHEMA",
    "SCHEMA_VERSION",
    "summarize_signal",
    "screen_config",
    "build_results",
    "validate_results",
    "write_results",
    "results_from_demo",
    "__version__",
]

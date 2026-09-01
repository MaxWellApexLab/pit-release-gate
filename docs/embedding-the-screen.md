# Embedding the susceptibility screen in your own registry

This guide is for projects that keep their own data registry or feature store
and want a selection-on-arrival screen inside it — without adopting this
package's storage, CLI, or badge machinery. Everything below uses only the
public API and the versioned record format.

Two integration depths, smallest first.

## Depth 1: call the screen, keep the record (five lines)

If you can produce one long table — one row per (entity, period) — you do not
need any of the package's internal objects:

```python
import pandas as pd
from pit_release_gate import screen_dataframe

df = pd.DataFrame({
    "period":  [...],   # groups the cross-section, e.g. fiscal quarter
    "arrival": [...],   # when THIS entity's record became available
    "value":   [...],   # the signal being screened (or pass a list of columns)
    "size":    [...],   # the observable the screen conditions on
})

record = screen_dataframe(df, trailing_k=5, rho_threshold=0.10)
```

`record` is a complete `pit-screen-results` v1.0 record (a plain dict):
per-signal verdicts, the settings that produced them, and summary statistics
only — no row-level data leaves your system. Persist it in your registry like
any other artifact. The estimate is fitted on the first `trailing_k` completed
periods and frozen before any period is screened, so the record is honest by
construction: no period contributes to the estimate that gates it.

Accepted inputs: pandas, polars, pyarrow, or a plain dict of arrays — anything
whose columns are addressable by name.

## Depth 2: wire the gate into your release path

If your registry decides *when* a computed value becomes visible to consumers,
use the two core objects directly:

```python
from pit_release_gate import AsOfDataStore, SusceptibilityGate, ReleaseController

gate = SusceptibilityGate()                          # threshold configurable
rho  = gate.fit_trailing(completed_period_stores)    # prior COMPLETED periods only

ctrl = ReleaseController(gate=gate, phi_min=0.35, suscept_slope=1.0)
decision = ctrl.decide(live_period_store, t=eval_time)  # WITHHOLD / REWEIGHT / RELEASE
```

`ReleaseDecision` carries the decision, the completeness at evaluation time,
and the threshold that was applied — enough to log an audit trail entry per
release. The contract to preserve if you reimplement rather than import:

1. fit only on prior completed periods, freeze before gating (`fit_trailing`);
2. gate on the *conditional* measure (latency vs. the residual given the
   observable), not the raw latency-signal correlation — the raw number
   confounds selection with composition;
3. never release later than your statutory or policy deadline — the gate
   tightens release, it must not loosen it.

## Emitting compatible records without importing anything

The record format is a separately versioned spec:
[`docs/results-schema.md`](results-schema.md). If your registry is not Python,
or you prefer your own implementation, emit JSON conforming to the spec and
validate it with `pit-screen-results` tooling later (or not at all — the spec
is self-contained). Records produced by different implementations are
comparable by design.

## Interface questions

Open an issue — interface questions are in scope, and if your registry needs
a field the record format lacks, the schema takes versioned extensions.

# Worked example: build an `AsOfDataStore` from a pandas DataFrame

If your input already looks like a long table, this is the normal path:

- one row per `(entity, period)`;
- a filing-arrival timestamp or date;
- a signal value you want to gate;
- a size column the gate conditions on.

The idea is simple:

1. take one period;
2. build a design matrix from the size column;
3. normalize the arrival times to `[0, 1]` inside that period;
4. package those pieces into `AsOfDataStore`;
5. fit the gate on earlier completed periods;
6. call `ReleaseController.decide(...)` on the live period.

This is the same pattern production pipelines use: honest estimation first, then a gated decision on the new period.

```python
import numpy as np
import pandas as pd

from pit_release_gate import AsOfDataStore, ReleaseController, SusceptibilityGate


def build_store(frame: pd.DataFrame) -> AsOfDataStore:
    """Turn one period of a long table into one as-of store."""
    size = (frame["size"] - frame["size"].mean()) / frame["size"].std(ddof=0)
    X = np.column_stack([np.ones(len(frame)), size.to_numpy()])
    y = frame["signal_value"].to_numpy()

    # The estimand is the complete-cross-section residual from the design matrix.
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    truth_resid = y - X @ beta

    # Arrival is a time inside the period: 0 = earliest filer, 1 = deadline.
    arrival_ts = pd.to_datetime(frame["arrival_date"]).astype("int64").to_numpy() / 1e9
    lo = arrival_ts.min()
    hi = arrival_ts.max()
    if hi == lo:
        arrival = np.zeros_like(arrival_ts, dtype=float)
    else:
        arrival = (arrival_ts - lo) / (hi - lo)

    return AsOfDataStore(
        X=X,
        y=y,
        arrival=arrival,
        size=size.to_numpy(),
        truth_resid=truth_resid,
    )


rows = []
for period in [2023, 2024, 2025]:
    for entity in ["A", "B", "C", "D", "E", "F"]:
        size = 10 + (ord(entity) % 10) + 0.2 * period
        signal_value = 5 + 0.9 * size + (0.4 if period in (2023, 2024) else 0.0)
        arrival_date = pd.Timestamp(f"{period}-01-01") + pd.Timedelta(
            days=(ord(entity) % 6) * 5 + (period - 2023) * 12
        )
        rows.append(
            {
                "entity": entity,
                "period": period,
                "arrival_date": arrival_date,
                "signal_value": signal_value,
                "size": size,
            }
        )

panel = pd.DataFrame(rows)

# Honest estimate: fit on earlier completed periods only.
completed = [build_store(panel[panel["period"] == p]) for p in [2023, 2024]]
gate = SusceptibilityGate(threshold=0.10)
rho = gate.fit_trailing(completed)

# Live period: the gate uses the frozen rho estimate from the completed periods.
live = build_store(panel[panel["period"] == 2025])
controller = ReleaseController(gate=gate)
decision = controller.decide(live, t=1.0, policy="gated")

assert decision.action == "RELEASE"
assert decision.t == 1.0
assert decision.completeness == 1.0
assert decision.values is not None

print(f"rho_hat={rho:.3f} -> {decision.action} at completeness {decision.completeness:.0%}")
```
What happened here?

- `panel` was a long table, not a custom object.
- `build_store()` converted that long table into one `AsOfDataStore` for one period.
- `gate.fit_trailing(completed)` learned the susceptibility estimate from earlier periods only.
- `controller.decide(live, t=1.0, policy="gated")` asked, "Should we release now?" At the deadline, the answer is `RELEASE` because the full cross-section has arrived.

The important point is that the gate never uses the same period it is trying to judge. That is the honest-estimation rule inside `pit-release-gate`.

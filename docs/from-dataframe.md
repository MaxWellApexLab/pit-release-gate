\# Worked example: build an `AsOfDataStore` from a pandas DataFrame



If your input already looks like a long table, this is the normal path:



\- one row per `(entity, period)`;

\- a filing-arrival timestamp or date;

\- a signal value you want to gate;

\- a size column the gate conditions on.



The idea is simple:



1\. take one period;

2\. build a design matrix from the size column;

3\. normalize the arrival times to `\[0, 1]` inside that period;

4\. package those pieces into `AsOfDataStore`;

5\. fit the gate on earlier completed periods;

6\. call `ReleaseController.decide(...)` on the live period.



This is the same pattern production pipelines use: honest estimation first, then a gated decision on the new period.



```python

import numpy as np

import pandas as pd



from pit\_release\_gate import AsOfDataStore, ReleaseController, SusceptibilityGate





def build\_store(frame: pd.DataFrame) -> AsOfDataStore:

&#x20;   """Turn one period of a long table into one as-of store."""

&#x20;   size = (frame\["size"] - frame\["size"].mean()) / frame\["size"].std(ddof=0)

&#x20;   X = np.column\_stack(\[np.ones(len(frame)), size.to\_numpy()])

&#x20;   y = frame\["signal\_value"].to\_numpy()



&#x20;   # The estimand is the complete-cross-section residual from the design matrix.

&#x20;   beta, \*\_ = np.linalg.lstsq(X, y, rcond=None)

&#x20;   truth\_resid = y - X @ beta



&#x20;   # Arrival is a time inside the period: 0 = earliest filer, 1 = deadline.

&#x20;   arrival\_ts = pd.to\_datetime(frame\["arrival\_date"]).astype("int64").to\_numpy() / 1e9

&#x20;   lo = arrival\_ts.min()

&#x20;   hi = arrival\_ts.max()

&#x20;   if hi == lo:

&#x20;       arrival = np.zeros\_like(arrival\_ts, dtype=float)

&#x20;   else:

&#x20;       arrival = (arrival\_ts - lo) / (hi - lo)



&#x20;   return AsOfDataStore(

&#x20;       X=X,

&#x20;       y=y,

&#x20;       arrival=arrival,

&#x20;       size=size.to\_numpy(),

&#x20;       truth\_resid=truth\_resid,

&#x20;   )





rows = \[]

for period in \[2023, 2024, 2025]:

&#x20;   for entity in \["A", "B", "C", "D", "E", "F"]:

&#x20;       size = 10 + (ord(entity) % 10) + 0.2 \* period

&#x20;       signal\_value = 5 + 0.9 \* size + (0.4 if period in (2023, 2024) else 0.0)

&#x20;       arrival\_date = pd.Timestamp(f"{period}-01-01") + pd.Timedelta(

&#x20;           days=(ord(entity) % 6) \* 5 + (period - 2023) \* 12

&#x20;       )

&#x20;       rows.append(

&#x20;           {

&#x20;               "entity": entity,

&#x20;               "period": period,

&#x20;               "arrival\_date": arrival\_date,

&#x20;               "signal\_value": signal\_value,

&#x20;               "size": size,

&#x20;           }

&#x20;       )



panel = pd.DataFrame(rows)



\# Honest estimate: fit on earlier completed periods only.

completed = \[build\_store(panel\[panel\["period"] == p]) for p in \[2023, 2024]]

gate = SusceptibilityGate(threshold=0.10)

rho = gate.fit\_trailing(completed)



\# Live period: the gate uses the frozen rho estimate from the completed periods.

live = build\_store(panel\[panel\["period"] == 2025])

controller = ReleaseController(gate=gate)

decision = controller.decide(live, t=1.0, policy="gated")



assert decision.action == "RELEASE"

assert decision.t == 1.0

assert decision.completeness == 1.0

assert decision.values is not None



print(f"rho\_hat={rho:.3f} -> {decision.action} at completeness {decision.completeness:.0%}")


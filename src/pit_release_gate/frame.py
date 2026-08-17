"""Screen a tabular panel directly, without building stores by hand.

`screen_dataframe` takes one long table — an entity, a period, a filing
arrival time, one or more signal values, and a conditioning covariate — and
runs the same frozen protocol the published audits use: fit the
susceptibility estimate on prior *completed* periods, freeze it, apply it
forward, and report per-signal verdicts as a `pit-screen-results` record.

The table can be anything that hands over a column: a pandas DataFrame, a
polars DataFrame, a pyarrow Table, or a plain dict of arrays. Nothing is
imported from any dataframe library — columns are read by duck typing and
converted to numpy, so the screen itself carries no dataframe dependency.
"""
from __future__ import annotations

import numpy as np

from .controller import ReleaseController
from .gate import SusceptibilityGate
from .results import build_results, screen_config, summarize_signal
from .store import AsOfDataStore

__all__ = ["screen_dataframe", "stores_from_frame"]


def _column(data, name):
    """One column as a 1-D numpy array, from any column-addressable table."""
    try:
        col = data[name]
    except (KeyError, IndexError, TypeError) as exc:
        raise KeyError(f"column {name!r} not found in the table") from exc
    for attr in ("to_numpy", "__array__"):          # pandas / polars / pyarrow / numpy
        if hasattr(col, attr):
            arr = np.asarray(col.to_numpy() if attr == "to_numpy" else col)
            break
    else:
        arr = np.asarray(col)
    return arr.reshape(-1)


def _as_float(arr, name):
    """Numeric view of a column, accepting datetimes for arrival times."""
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[s]").astype(np.float64)
    if np.issubdtype(arr.dtype, np.timedelta64):
        return arr.astype("timedelta64[s]").astype(np.float64)
    try:
        return arr.astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"column {name!r} is not numeric (dtype {arr.dtype})") from exc


def _ols_resid(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


def stores_from_frame(data, *, period="period", arrival="arrival",
                      value="value", size="size", min_entities=6):
    """Build one `AsOfDataStore` per period, oldest first.

    Rows with a missing value, size or arrival are dropped for that signal,
    and periods left with fewer than `min_entities` rows are skipped —
    a cross-section too small to residualize honestly is not screened
    rather than screened badly.
    """
    per = _column(data, period)
    arr = _as_float(_column(data, arrival), arrival)
    val = _as_float(_column(data, value), value)
    siz = _as_float(_column(data, size), size)
    if not (len(per) == len(arr) == len(val) == len(siz)):
        raise ValueError("columns have different lengths")

    stores, kept = [], []
    for key in _ordered_unique(per):
        m = (per == key) & np.isfinite(arr) & np.isfinite(val) & np.isfinite(siz)
        if m.sum() < min_entities:
            continue
        a, v, s = arr[m], val[m], siz[m]

        span = a.max() - a.min()
        # arrival on [0, 1] within the period, 1 = the last filer (the deadline)
        norm = np.ones_like(a) if span <= 0 else (a - a.min()) / span
        sd = s.std()
        s_std = np.zeros_like(s) if sd < 1e-12 else (s - s.mean()) / sd
        X = np.column_stack([np.ones(m.sum()), s_std])

        stores.append(AsOfDataStore(
            X=X, y=v, arrival=norm, size=s_std,
            # the estimand: the residual the COMPLETE cross-section implies
            truth_resid=_ols_resid(X, v),
        ))
        kept.append(key)
    return stores, kept


def _ordered_unique(a):
    """Unique period keys, sorted — periods must be screened in time order."""
    return sorted(set(a.tolist()))


def screen_dataframe(data, *, period="period", arrival="arrival",
                     value="value", size="size", trailing_k=5,
                     rho_threshold=0.10, phi_min=0.35, kappa=1.0,
                     min_entities=6, date=None) -> dict:
    """Screen one or more signals in a long table for incomplete-cross-section
    leakage, and return a `pit-screen-results` v1.0 record.

    Parameters
    ----------
    data
        A long table: one row per (entity, period). Any object whose columns
        are addressable by name — pandas, polars, pyarrow, or a dict of
        arrays.
    period, arrival, size
        Column names. `period` groups the cross-section, `arrival` is when
        that entity's record became available (a date or any increasing
        number), `size` is the observable the screen conditions on.
    value
        The signal column, or a list of them to screen several at once.
    trailing_k
        How many prior completed periods the estimate is fitted on before
        it is frozen and applied forward. The first `trailing_k` periods
        are therefore used for fitting only and are not screened.
    rho_threshold, phi_min, kappa, min_entities
        Screen settings, recorded in the returned record so a reader can
        tell which settings produced the verdicts.

    Returns
    -------
    dict
        A validated `pit-screen-results` record. Write it with
        `write_results`, publish it, and point a *screened with* badge at it.

    Notes
    -----
    A signal's verdict is ``susceptible`` if the frozen estimate exceeded the
    threshold in **any** screened period — the convention the published
    audit reports use, because a channel that opens in one year is not
    closed by averaging it against years where it did not.

    Because the verdict fires on any single period, it inherits that period's
    sampling noise: the standard error of the estimate is roughly
    ``1 / sqrt(trailing_k * entities_per_period)``, so on small panels a
    reading just over the threshold may be noise rather than a channel.
    Establish the noise floor for your panel — screen a signal you have
    reason to believe is unexposed, or shuffle arrival order within periods
    and re-screen — before treating a marginal verdict as a finding. The
    published audit reports do this and state the floor they measured.

    The screen is honest by construction: the estimate applied to a period is
    never fitted on that period. Nothing is sent anywhere; this function
    performs no network I/O.
    """
    names = [value] if isinstance(value, str) else list(value)
    if not names:
        raise ValueError("no signal column given")
    if trailing_k < 1:
        raise ValueError("trailing_k must be at least 1")

    controller = ReleaseController(phi_min=phi_min, suscept_slope=kappa)
    signals = []
    for name in names:
        stores, kept = stores_from_frame(
            data, period=period, arrival=arrival, value=name,
            size=size, min_entities=min_entities)
        if len(stores) <= trailing_k:
            raise ValueError(
                f"{name}: {len(stores)} usable periods, need more than "
                f"trailing_k={trailing_k} so at least one period can be screened "
                f"(periods with fewer than {min_entities} entities are skipped)")

        rhos, phi_reqs = [], []
        for i in range(trailing_k, len(stores)):
            gate = SusceptibilityGate(threshold=rho_threshold)
            rho = gate.fit_trailing(stores[i - trailing_k:i])   # frozen before use
            rhos.append(rho)
            phi_reqs.append(controller.required_completeness(rho))

        signals.append(summarize_signal(
            name, rhos, phi_reqs, rho_threshold=rho_threshold,
            susceptible=any(abs(r) > rho_threshold for r in rhos)))

    config = screen_config(rho_threshold, phi_min, kappa,
                           trailing_k=trailing_k, min_entities=min_entities)
    return build_results(signals, config, date=date)

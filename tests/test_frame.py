"""The tabular entry point: planted-truth behaviour, framework independence,
and the honest-estimation contract."""
import numpy as np
import pytest

from pit_release_gate import screen_dataframe, stores_from_frame, validate_results


def planted_panel(n_periods=12, n=60, leak=0.0, seed=0):
    """A long table whose leakage strength is known by construction.

    ``leak`` couples filing latency to the signal's disturbance: at 0 the
    arrival order carries no information about the disturbance, and the
    screen should read ~0; raise it and the early cross-section becomes a
    selected sample, which is what the screen is built to catch.
    """
    rng = np.random.default_rng(seed)
    cols = {k: [] for k in ("period", "entity", "arrival", "value", "size")}
    for p in range(n_periods):
        size = rng.normal(size=n)
        u = rng.normal(size=n)
        cols["period"] += [p] * n
        cols["entity"] += list(range(n))
        cols["arrival"] += list(rng.normal(size=n) - leak * u)
        cols["value"] += list(0.5 * size + u)
        cols["size"] += list(size)
    return {k: np.array(v) for k, v in cols.items()}


def test_clean_panel_reads_benign():
    r = screen_dataframe(planted_panel(leak=0.0))
    sig = r["signals"][0]
    assert sig["verdict"] == "benign"
    assert sig["periods_flagged"] == 0
    assert abs(sig["mean_rho"]) < 0.10


def test_planted_leak_is_flagged_and_gated_to_the_deadline():
    r = screen_dataframe(planted_panel(leak=2.0))
    sig = r["signals"][0]
    assert sig["verdict"] == "susceptible"
    assert sig["periods_flagged"] == sig["periods_screened"]
    # a strongly susceptible signal must be held until the cross-section is complete
    assert sig["mean_phi_req"] == pytest.approx(1.0)


def test_record_validates_against_the_published_schema():
    r = screen_dataframe(planted_panel(leak=1.0))
    assert validate_results(r) == []
    assert r["config"]["trailing_k"] == 5
    assert r["config"]["rho_threshold"] == pytest.approx(0.10)


def test_first_k_periods_are_used_for_fitting_only():
    # 12 periods, k=5 -> exactly 7 screened; the fitted periods are never graded
    r = screen_dataframe(planted_panel(n_periods=12), trailing_k=5)
    assert r["signals"][0]["periods_screened"] == 7
    r8 = screen_dataframe(planted_panel(n_periods=12), trailing_k=8)
    assert r8["signals"][0]["periods_screened"] == 4


def test_several_signals_in_one_pass():
    # 200 entities per period: the sampling noise floor of rho is ~1/sqrt(k*n),
    # small enough here that a genuinely unrelated signal stays under threshold
    p = planted_panel(n=200, leak=2.0)
    p["quiet"] = p["size"] * 0.3 + np.random.default_rng(1).normal(size=len(p["size"]))
    r = screen_dataframe(p, value=["value", "quiet"])
    by_name = {s["name"]: s for s in r["signals"]}
    assert by_name["value"]["verdict"] == "susceptible"
    assert by_name["quiet"]["verdict"] == "benign"
    assert r["totals"]["signals_susceptible"] == 1
    assert r["totals"]["signals_benign"] == 1


def test_pandas_polars_and_dict_agree():
    """The screen reads columns, not a dataframe library."""
    base = planted_panel(leak=1.5)
    want = screen_dataframe(base)

    pd = pytest.importorskip("pandas")
    assert screen_dataframe(pd.DataFrame(base)) == want

    pl = pytest.importorskip("polars")
    assert screen_dataframe(pl.DataFrame(base)) == want


def test_datetime_arrivals_are_accepted():
    p = planted_panel(leak=2.0)
    days = (p["arrival"] - p["arrival"].min()) * 5
    p["filed"] = np.datetime64("2020-01-01") + days.astype("timedelta64[D]")
    r = screen_dataframe(p, arrival="filed")
    assert r["signals"][0]["verdict"] == "susceptible"


def test_custom_column_names():
    p = planted_panel(leak=2.0)
    renamed = {"fy": p["period"], "filed_at": p["arrival"],
               "accruals": p["value"], "logme": p["size"]}
    r = screen_dataframe(renamed, period="fy", arrival="filed_at",
                         value="accruals", size="logme")
    assert r["signals"][0]["name"] == "accruals"
    assert r["signals"][0]["verdict"] == "susceptible"


def test_short_periods_are_skipped_not_screened_badly():
    p = planted_panel(n_periods=8, n=60)
    # starve one period down to 3 entities
    keep = ~((p["period"] == 3) & (p["entity"] >= 3))
    p = {k: v[keep] for k, v in p.items()}
    stores, kept = stores_from_frame(p, value="value", min_entities=6)
    assert 3 not in kept
    assert len(stores) == 7


def test_missing_values_are_dropped_per_signal():
    p = planted_panel(leak=2.0)
    p["value"] = p["value"].astype(float)
    p["value"][:5] = np.nan
    r = screen_dataframe(p)                       # must not raise, must not poison
    assert r["signals"][0]["verdict"] == "susceptible"


def test_errors_are_actionable():
    p = planted_panel(n_periods=4)
    with pytest.raises(KeyError, match="no_such_column"):
        screen_dataframe(p, value="no_such_column")
    with pytest.raises(ValueError, match="trailing_k"):
        screen_dataframe(p, trailing_k=5)         # 4 periods, none screenable
    with pytest.raises(ValueError, match="at least 1"):
        screen_dataframe(p, trailing_k=0)


def test_screen_is_deterministic():
    p = planted_panel(leak=1.0)
    assert screen_dataframe(p) == screen_dataframe(p)


def test_no_network_machinery_in_the_frame_module():
    import pit_release_gate.frame as m
    src = open(m.__file__, encoding="utf-8").read()
    for forbidden in ("urllib", "requests", "http", "socket", "atexit", "threading"):
        assert forbidden not in src, f"frame.py must not reference {forbidden!r}"

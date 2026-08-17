# Changelog

## Unreleased

Screen your own panel. **No change to package behavior:**
`tests/test_reproduces_paper.py` is untouched and the demo reproduces the same
numbers as 0.1.1.

- `screen_dataframe(table, value=..., trailing_k=...)` screens a long table
  directly and returns a `pit-screen-results` record. The table may be a
  pandas or polars DataFrame, a pyarrow Table, or a dict of arrays — columns
  are read by duck typing, so no dataframe library is imported and none is
  required. Datetime arrival columns are accepted.
- `stores_from_frame` exposes the per-period stores the screen builds, for
  callers who want to inspect or gate them individually.
- CLI: `--csv PATH --value COLUMN` screens a user panel instead of running the
  demo, with `--period/--arrival/--size/--trailing-k/--threshold` and the
  existing `--export` and `--badge`. CSV reading uses the standard library.
- The verdict convention is documented, including its noise floor: a signal is
  susceptible if any screened period crossed the threshold, which on small
  panels can fire on sampling noise.

## 0.1.2 — unreleased (earlier work)

Screen-result export. **No change to package behavior:**
`tests/test_reproduces_paper.py` is untouched and the demo reproduces the same
numbers as 0.1.1.

- `--export PATH` writes a `pit-screen-results` v1.0 record — per-signal summary
  statistics and the screen settings that produced the verdicts. Fully offline
  (local file, no network call) and free of clocks, so the same screen exports
  byte-identical bytes.
- `docs/results-schema.md`: the schema as a standalone versioned interchange
  spec, free for other tools to adopt.
- New module `pit_release_gate.results`: `summarize_signal`, `screen_config`,
  `build_results`, `validate_results`, `write_results`. Totals are derived, so
  they cannot disagree with the per-signal rows.
- Still no telemetry of any kind, now enforced structurally rather than by
  policy: no module in the package imports a transport, and a test asserts that
  over every module — no background thread, no `atexit` hook, nothing to opt
  out of.

## 0.1.1 — 2026-08-16

Documentation and submission materials only. **No change to package behavior:**
the test suite, including `tests/test_reproduces_paper.py`, is untouched and the
demo reproduces the same numbers as 0.1.0.

- `paper.md` and `paper.bib`: software paper prepared for submission to the
  Journal of Open Source Software.
- README: added *Statement of need*, *API overview*, and *Community guidelines*
  sections.
- CI: `draft-pdf.yml` builds a preview PDF of `paper.md` with the Open Journals
  toolchain and uploads it as a build artifact.

## 0.1.0 — 2026-08-15

First public release.

- Susceptibility screen: disturbance-conditional partial correlation (rho-hat),
  fitted on prior completed periods and frozen before gating.
- Graded release controller: per-signal required completeness
  `phi_req = min(1, phi_min + kappa * |rho_hat|)`, with naive / fixed-threshold /
  IPW-reweight / statutory-deadline baselines.
- Self-contained known-ground-truth demo (`pit-release-gate`), deterministic,
  reproducing the controlled experiment of doi:10.6084/m9.figshare.33158615.
- Test suite asserting the paper's headline numbers.

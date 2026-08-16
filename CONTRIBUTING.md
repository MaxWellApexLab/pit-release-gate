# Contributing

Issues and pull requests are welcome.

## Development setup

```bash
pip install -e .[dev]
pytest -q --cov=pit_release_gate
```

All tests must pass; `tests/test_reproduces_paper.py` pins the numerical
behavior of the reference implementation to the published paper
(doi:10.6084/m9.figshare.33158615) — changes that move those numbers need a
very good reason and a version bump.

## Reporting a susceptibility/leakage case

If you have a real-world pipeline where the screen flagged (or missed)
incomplete-cross-section leakage, an issue with a minimal reproduction is the
most valuable contribution you can make.

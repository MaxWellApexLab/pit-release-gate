"""The ``pit-screen-results`` record: build it, validate it, write it.

A screen result is a *summary*: per signal, how many periods were screened,
how many of them the susceptibility measure flagged, the mean and maximum
susceptibility, the required completeness the controller assigned, and the
verdict. Nothing else. No input rows, no file paths, no identities, no
environment details beyond the tool version -- so a record is safe to commit
next to the badge, or to hand to a third party.

This module is deliberately **offline**: it imports no transport machinery,
so nothing that builds or writes a record can send it anywhere. Neither does
anything else in this package -- there is no submission path at all, and a
record goes where you put it and nowhere else.

It is also deliberately **timeless**: no clock is read here, so two runs of
the same screen produce byte-identical records. A caller that wants a date
in the record passes one in explicitly (``build_results(..., date=...)``).

The schema is documented as a standalone interchange format in
``docs/results-schema.md``; other tools are free to emit it.
"""
from __future__ import annotations

import json
from pathlib import Path

#: Self-identifying name of the interchange format (not of the producing tool).
SCHEMA = 'pit-screen-results'
SCHEMA_VERSION = '1.0'
KNOWN_SCHEMA_VERSIONS = ('1.0',)

#: The tool that produces the record in this package.
TOOL = 'pit-release-gate'

#: The only two verdicts a screened signal can carry.
VERDICTS = ('benign', 'susceptible')

_TOP_FIELDS = ('schema', 'schema_version', 'tool', 'tool_version',
               'config', 'signals', 'totals')
_CONFIG_FIELDS = ('rho_threshold', 'phi_min', 'kappa', 'trailing_k', 'min_entities')
_SIGNAL_FIELDS = ('name', 'periods_screened', 'periods_flagged', 'mean_rho',
                  'max_abs_rho', 'mean_phi_req', 'verdict')
_TOTALS_FIELDS = ('signal_cycles', 'signals_benign', 'signals_susceptible')


def tool_version() -> str:
    """Version of the code that actually ran.

    The in-tree ``__version__`` is preferred over installed distribution
    metadata, because a source checkout on ``PYTHONPATH`` can shadow an older
    installed wheel; the metadata is the fallback. Never a hardcoded literal.
    """
    try:
        from . import __version__
        return str(__version__)
    except ImportError:  # pragma: no cover - only if the package is half-built
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version(TOOL)
        except PackageNotFoundError:
            return 'unknown'


def screen_config(rho_threshold: float, phi_min: float, kappa: float,
                  trailing_k: int, min_entities: int) -> dict:
    """The screen settings that determine a verdict, in record form.

    These five are what another party needs in order to read a verdict:
    the susceptibility threshold, the completeness floor and slope of
    ``phi_req = min(1, phi_min + kappa*|rho_hat|)``, how many prior completed
    periods the estimate was fitted on, and the minimum arrived count below
    which the controller releases nothing.
    """
    return {
        'rho_threshold': float(rho_threshold),
        'phi_min': float(phi_min),
        'kappa': float(kappa),
        'trailing_k': int(trailing_k),
        'min_entities': int(min_entities),
    }


def summarize_signal(name: str, rhos, phi_reqs, rho_threshold: float = 0.10,
                     susceptible: bool = None) -> dict:
    """Reduce one signal's per-period screen to the record's summary row.

    ``rhos`` are the per-period susceptibility estimates and ``phi_reqs`` the
    required completeness the controller assigned in each of those periods;
    they must be the same length, and that length is ``periods_screened``.
    A period is *flagged* when ``|rho|`` exceeds ``rho_threshold``, so
    ``periods_flagged <= periods_screened`` by construction.

    The verdict defaults to the same test applied to the mean susceptibility;
    a caller that gates on a frozen trailing estimate should pass its own
    verdict as ``susceptible`` so the record states what the screen actually
    decided.
    """
    rhos = [float(r) for r in rhos]
    phi_reqs = [float(p) for p in phi_reqs]
    if len(rhos) != len(phi_reqs):
        raise ValueError(f'{name}: got {len(rhos)} rho values but '
                         f'{len(phi_reqs)} required-completeness values')
    if not rhos:
        raise ValueError(f'{name}: no screened periods')
    mean_rho = sum(rhos) / len(rhos)
    if susceptible is None:
        susceptible = abs(mean_rho) > rho_threshold
    return {
        'name': str(name),
        'periods_screened': len(rhos),
        'periods_flagged': sum(1 for r in rhos if abs(r) > rho_threshold),
        'mean_rho': mean_rho,
        'max_abs_rho': max(abs(r) for r in rhos),
        'mean_phi_req': sum(phi_reqs) / len(phi_reqs),
        'verdict': VERDICTS[1] if susceptible else VERDICTS[0],
    }


def build_results(signals, config: dict, tool: str = TOOL,
                  version: str = None, date: str = None) -> dict:
    """Assemble a complete ``pit-screen-results`` record.

    ``signals`` is a list of :func:`summarize_signal` rows. The totals are
    derived here rather than accepted from the caller, so they cannot
    disagree with the rows. ``date`` is optional and purely caller-supplied
    -- this module never reads a clock.
    """
    signals = [dict(s) for s in signals]
    record = {
        'schema': SCHEMA,
        'schema_version': SCHEMA_VERSION,
        'tool': str(tool),
        'tool_version': version or tool_version(),
        'config': dict(config),
        'signals': signals,
        'totals': {
            'signal_cycles': sum(int(s['periods_screened']) for s in signals),
            'signals_benign': sum(1 for s in signals if s['verdict'] == VERDICTS[0]),
            'signals_susceptible': sum(1 for s in signals if s['verdict'] == VERDICTS[1]),
        },
    }
    if date is not None:
        record['date'] = str(date)
    return record


def validate_results(obj) -> list[str]:
    """Return a list of human-readable problems with ``obj``; empty == valid.

    Written so that a reader of the format -- not just this package -- can
    check a record before relying on it, and so that any receiver of the
    format can refuse something malformed.
    """
    problems: list[str] = []
    if not isinstance(obj, dict):
        return [f'record must be a JSON object, got {type(obj).__name__}']

    version = obj.get('schema_version')
    if version is None:
        problems.append('missing required field: schema_version')
    elif version not in KNOWN_SCHEMA_VERSIONS:
        problems.append(f'unknown schema_version {version!r} '
                        f'(known: {", ".join(KNOWN_SCHEMA_VERSIONS)})')
    if obj.get('schema') != SCHEMA:
        problems.append(f'schema must be {SCHEMA!r}, got {obj.get("schema")!r}')
    for field in _TOP_FIELDS:
        if field not in obj:
            if field != 'schema_version':      # already reported above
                problems.append(f'missing required field: {field}')

    config = obj.get('config')
    if config is not None and not isinstance(config, dict):
        problems.append('config must be a JSON object')
    elif isinstance(config, dict):
        for field in _CONFIG_FIELDS:
            if field not in config:
                problems.append(f'missing required config field: {field}')

    signals = obj.get('signals')
    cycles = 0
    if signals is not None and not isinstance(signals, list):
        problems.append('signals must be a list')
    elif isinstance(signals, list):
        if not signals:
            problems.append('signals is empty: nothing was screened')
        for i, sig in enumerate(signals):
            where = f'signals[{i}]'
            if not isinstance(sig, dict):
                problems.append(f'{where} must be a JSON object')
                continue
            where = f'signals[{i}] ({sig.get("name", "unnamed")})'
            for field in _SIGNAL_FIELDS:
                if field not in sig:
                    problems.append(f'{where}: missing required field: {field}')
            if sig.get('verdict') not in VERDICTS and 'verdict' in sig:
                problems.append(f'{where}: verdict must be one of '
                                f'{", ".join(VERDICTS)}, got {sig["verdict"]!r}')
            screened, flagged = sig.get('periods_screened'), sig.get('periods_flagged')
            if isinstance(screened, int) and isinstance(flagged, int):
                cycles += screened
                if flagged > screened:
                    problems.append(f'{where}: periods_flagged ({flagged}) exceeds '
                                    f'periods_screened ({screened})')
                if flagged < 0 or screened < 0:
                    problems.append(f'{where}: periods_screened and periods_flagged '
                                    f'must not be negative')
            elif screened is not None or flagged is not None:
                problems.append(f'{where}: periods_screened and periods_flagged '
                                f'must be integers')

    totals = obj.get('totals')
    if totals is not None and not isinstance(totals, dict):
        problems.append('totals must be a JSON object')
    elif isinstance(totals, dict):
        for field in _TOTALS_FIELDS:
            if field not in totals:
                problems.append(f'missing required totals field: {field}')
        if isinstance(signals, list) and 'signal_cycles' in totals:
            if totals['signal_cycles'] != cycles:
                problems.append(f'totals.signal_cycles ({totals["signal_cycles"]}) '
                                f'does not equal the sum over signals ({cycles})')
        if isinstance(signals, list):
            benign = sum(1 for s in signals
                         if isinstance(s, dict) and s.get('verdict') == VERDICTS[0])
            suspect = sum(1 for s in signals
                          if isinstance(s, dict) and s.get('verdict') == VERDICTS[1])
            if totals.get('signals_benign') != benign:
                problems.append(f'totals.signals_benign ({totals.get("signals_benign")}) '
                                f'does not equal the number of benign signals ({benign})')
            if totals.get('signals_susceptible') != suspect:
                problems.append(f'totals.signals_susceptible '
                                f'({totals.get("signals_susceptible")}) does not equal '
                                f'the number of susceptible signals ({suspect})')
    return problems


def dumps_results(obj) -> str:
    """Canonical JSON text of a record -- exactly what ``--export`` writes."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


def write_results(obj, path) -> Path:
    """Write a validated record to ``path`` as JSON. Local file I/O only.

    Raises ``ValueError`` rather than writing a record that would not survive
    :func:`validate_results`.
    """
    problems = validate_results(obj)
    if problems:
        raise ValueError('refusing to write an invalid ' + SCHEMA + ' record: '
                         + '; '.join(problems))
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_results(obj) + '\n', encoding='utf-8', newline='\n')
    return path

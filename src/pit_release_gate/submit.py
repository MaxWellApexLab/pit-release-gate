"""Opt-in submission of a ``pit-screen-results`` record.

Nothing in this module runs unless the user typed ``--submit URL`` on this
invocation. There is no background thread, no ``atexit`` hook, no implicit
or opt-out reporting path, and no other module imports this one at run time
except the command line, on that flag. The package never phones home.

What leaves the machine is exactly what is printed first: the record built
by :mod:`pit_release_gate.results` (per-signal summary statistics only),
plus a ``contact`` field if -- and only if -- the user passed ``--contact``.
``--dry-run`` prints the same bytes and sends nothing.

Standard library only (``urllib.request``): submitting must not cost the
package a dependency.
"""
from __future__ import annotations

import http.client
import json
import urllib.request

from .results import SCHEMA, dumps_results, tool_version, validate_results

#: Printed after a successful submission.
CITATION_DOIS = (
    '10.6084/m9.figshare.32952482',
    '10.6084/m9.figshare.33061955',
    '10.6084/m9.figshare.33158615',
)

#: Deliberately the tool and its version only -- not the Python build, not the
#: platform. It replaces urllib's default agent string, which would leak more.
USER_AGENT = f'pit-release-gate/{tool_version()}'

DEFAULT_TIMEOUT = 30.0


class SubmissionError(RuntimeError):
    """Raised when a submission is refused or fails. Never swallowed."""


def build_payload(record: dict, contact: str = None) -> dict:
    """The record, plus an opt-in contact address.

    Without ``contact`` the key is absent from the payload entirely -- not
    empty, not null.
    """
    payload = dict(record)
    if contact:
        payload['contact'] = str(contact)
    return payload


def submit_results(record: dict, url: str, contact: str = None,
                   dry_run: bool = False, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """POST a screen record to ``url`` and print the score / badge URL.

    Prints the exact payload before sending it, so the user can see precisely
    what leaves the machine. Refuses to send a record that fails
    :func:`~pit_release_gate.results.validate_results`. Network failures raise
    :class:`SubmissionError` -- they are never retried silently and never
    ignored. Returns the decoded response, or ``None`` under ``dry_run``.
    """
    payload = build_payload(record, contact)
    problems = validate_results(payload)
    if problems:
        raise SubmissionError(f'refusing to submit an invalid {SCHEMA} record: '
                              + '; '.join(problems))

    body = dumps_results(payload)
    data = body.encode('utf-8')
    print(f'\nabout to POST {len(data)} bytes to {url}')
    print('this is the complete payload -- nothing else leaves this machine:')
    print(body)

    if dry_run:
        print('\n--dry-run: nothing was sent.')
        return None

    req = urllib.request.Request(
        url, data=data, method='POST',
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json',
                 'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
    except (OSError, ValueError, http.client.HTTPException) as exc:
        # urllib.error.URLError / HTTPError are OSError subclasses; a bad URL
        # scheme raises ValueError. All of them are reported, none is hidden.
        raise SubmissionError(f'submission to {url} failed: {exc}') from exc

    try:
        reply = json.loads(raw)
    except ValueError:
        reply = {}
    if not isinstance(reply, dict):
        reply = {}

    print('\nsubmitted.')
    score = reply.get('score')
    badge = reply.get('badge_url') or reply.get('badge')
    if score is not None:
        print(f'  score: {score}')
    if badge:
        print(f'  badge: {badge}')
    if score is None and not badge:
        print(f'  response: {raw.strip()[:500] or "(empty)"}')

    print('\nIf you use this in research, cite:')
    for doi in CITATION_DOIS:
        print(f'  doi:{doi}')
    return reply

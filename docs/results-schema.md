# `pit-screen-results` — screen-result interchange format

**Schema name:** `pit-screen-results`
**Version:** `1.0`
**Media type:** `application/json`
**Reference implementation:** [`src/pit_release_gate/results.py`](../src/pit_release_gate/results.py)
**Status:** stable

A `pit-screen-results` record states what an incomplete-cross-section
susceptibility screen found: for each signal that was screened, how many periods
it was screened over, how susceptible it looked, how much completeness the
release controller therefore required, and whether the verdict was **benign** or
**susceptible**. It is the evidence a *screened with* badge should point at.

The format is deliberately small. It is not a report format, not a results
database, and not a telemetry envelope.

## Design rules

These three rules are what make the record safe to commit to a public
repository or hand to a third party, and they are binding on any producer:

1. **Summary statistics only.** A record carries per-signal aggregates.
   It must never carry input rows, entity identifiers, residuals, file paths,
   usernames, hostnames, or any environment detail beyond the producing tool's
   name and version.
2. **Offline by construction.** Writing a record is local file I/O. In the
   reference implementation the module that builds and writes records imports
   no transport machinery at all; sending one is a separate, explicitly
   requested act (see [Submission envelope](#submission-envelope-non-normative)).
3. **No clocks.** A producer must not read the system clock while building a
   record: two runs of the same screen must produce byte-identical bytes. If a
   date belongs in the record, the caller passes it in (`date`, below).

## Top-level fields

| field | type | required | meaning |
|---|---|---|---|
| `schema` | string | yes | Always `"pit-screen-results"`. Identifies the format, not the producer. |
| `schema_version` | string | yes | `"1.0"` for this document. |
| `tool` | string | yes | Name of the producing tool, e.g. `"pit-release-gate"`. Any tool may emit this format under its own name. |
| `tool_version` | string | yes | Version of the producing tool. The only environment detail permitted anywhere in the record. |
| `config` | object | yes | The screen settings that determine the verdicts. See below. |
| `signals` | array of objects | yes | One entry per screened signal, non-empty. See below. |
| `totals` | object | yes | Aggregates over `signals`, derived — never independently asserted. |
| `date` | string | no | Caller-supplied date (ISO 8601 `YYYY-MM-DD` recommended). Absent unless the caller passed one; producers must not fill it in from a clock. |

## `config`

The five settings a reader needs in order to interpret a verdict. All are
required.

| field | type | meaning |
|---|---|---|
| `rho_threshold` | number | A signal is susceptible when \|ρ̂\| exceeds this. |
| `phi_min` | number | Completeness floor: the earliest completeness at which anything is released. |
| `kappa` | number | Slope of the graded requirement `phi_req = min(1, phi_min + kappa·\|ρ̂\|)`. |
| `trailing_k` | integer | Number of prior **completed** periods the susceptibility estimate was fitted on. |
| `min_entities` | integer | Minimum arrived entity count below which nothing is released. |

## `signals[]`

| field | type | meaning |
|---|---|---|
| `name` | string | Caller-chosen signal name. Must not encode a path, a file name, or an identity. |
| `periods_screened` | integer ≥ 0 | Number of periods the signal was screened over. |
| `periods_flagged` | integer | Of those, how many had a *per-period* \|ρ̂\| above `rho_threshold`. Must be ≤ `periods_screened`. |
| `mean_rho` | number | Mean of the per-period susceptibility estimates (signed). |
| `max_abs_rho` | number | Largest per-period \|ρ̂\| observed. |
| `mean_phi_req` | number | Mean required completeness the controller assigned across those periods. |
| `verdict` | string | `"benign"` or `"susceptible"` — no other value is valid. |

**`periods_flagged` is a noise gauge, not the verdict.** A single period's ρ̂ is
a small-sample estimate and will cross the threshold now and then on a perfectly
benign signal; that is exactly why a screen pools over `trailing_k` completed
periods before deciding. In the worked example below, `clean` has 3 of 5 periods
flagged and is still — correctly — `benign`: its pooled estimate is far under the
threshold, while `max_abs_rho = 0.164` records how noisy a single period was.
Read `verdict` for the decision, `periods_flagged` and `max_abs_rho` for how
stable that decision was.

## `totals`

Derived from `signals`; a producer computes them rather than accepting them, and
a consumer may treat a mismatch as a corrupt record.

| field | type | meaning |
|---|---|---|
| `signal_cycles` | integer | Sum of `periods_screened` over all signals — the total screening work the record represents. |
| `signals_benign` | integer | Number of signals with `verdict == "benign"`. |
| `signals_susceptible` | integer | Number with `verdict == "susceptible"`. |

## Validity

A record is valid when all of the following hold. The reference implementation
is `validate_results(obj) -> list[str]`, which returns one human-readable string
per problem and an empty list for a valid record.

1. The record is a JSON object with `schema == "pit-screen-results"`.
2. `schema_version` is present and known to the reader (`"1.0"`).
3. Every required top-level, `config`, `signals[]`, and `totals` field is present.
4. Every `verdict` is `"benign"` or `"susceptible"`.
5. `totals.signal_cycles` equals the sum of `periods_screened` over `signals`,
   and the two verdict counts equal the corresponding counts in `signals`.
6. For every signal, `0 <= periods_flagged <= periods_screened`.

Validation is a check on the record, not on the science: a record can be
perfectly valid and report a thoroughly susceptible pipeline. That is the point.

## Worked example

Produced by `pit-release-gate --train 3 --eval 5 --export results.json`
(reduced settings, so the file fits here):

```json
{
  "schema": "pit-screen-results",
  "schema_version": "1.0",
  "tool": "pit-release-gate",
  "tool_version": "0.1.1",
  "config": {
    "rho_threshold": 0.1,
    "phi_min": 0.35,
    "kappa": 1.0,
    "trailing_k": 3,
    "min_entities": 6
  },
  "signals": [
    {
      "name": "clean",
      "periods_screened": 5,
      "periods_flagged": 3,
      "mean_rho": -0.018502844357097172,
      "max_abs_rho": 0.16437940321670516,
      "mean_phi_req": 0.40870844204483336,
      "verdict": "benign"
    },
    {
      "name": "composition",
      "periods_screened": 5,
      "periods_flagged": 1,
      "mean_rho": 0.054842113923429116,
      "max_abs_rho": 0.1916906690936213,
      "mean_phi_req": 0.3622517271310478,
      "verdict": "benign"
    },
    {
      "name": "mild_leak",
      "periods_screened": 5,
      "periods_flagged": 5,
      "mean_rho": -0.5050242025985237,
      "max_abs_rho": 0.6073065398308837,
      "mean_phi_req": 0.8244168498651367,
      "verdict": "susceptible"
    },
    {
      "name": "strong_leak",
      "periods_screened": 5,
      "periods_flagged": 5,
      "mean_rho": -0.868283463437835,
      "max_abs_rho": 0.8934707972913439,
      "mean_phi_req": 1.0,
      "verdict": "susceptible"
    }
  ],
  "totals": {
    "signal_cycles": 20,
    "signals_benign": 2,
    "signals_susceptible": 2
  }
}
```

How to read it: four signals were screened over five periods each (20 signal
cycles). Two came out benign and release at roughly the completeness floor
(`mean_phi_req` ≈ 0.36–0.41). `mild_leak` is susceptible and is held until 82%
of its cross-section has arrived; `strong_leak` is held to the
deadline-complete cross-section (`mean_phi_req == 1.0`).

## Transport (deliberately unspecified)

This spec describes a **file format**, not a protocol. `pit-release-gate` writes
a record with `--export` and does nothing else with it: the package contains no
submission path and imports no transport at all. Where a record travels — a
commit next to a badge, an artifact in CI, an attachment, an endpoint of your own
— is the emitter's choice and outside this document.

If you build something that receives records, validate them the way §"Validity
rules" describes and treat everything in a record as publishable. A record
carries summary statistics only: it is designed so that publishing one leaks
nothing about the data it was computed from.

## Versioning

`schema_version` is `MAJOR.MINOR`. A **minor** bump only adds optional fields;
a reader for `1.0` may ignore fields it does not know and keep working. A
**major** bump may remove or repurpose fields, and readers should refuse a major
version they do not know rather than guess. The schema name never changes
meaning: a document identified as `pit-screen-results` always means a screen
result in the sense described here.

## Adoption

**This format is free for any tool to emit or consume**, with no attribution
requirement, no coordination with this project, and no compatibility obligation
in either direction. A screen result is more useful when it is comparable across
tools, so put your own name in `tool`, keep `schema` and `schema_version` as
specified, and the record will read the same everywhere. Extensions are welcome
under a namespaced key of your own (e.g. `"x_yourtool"`); a `1.0` reader must
ignore what it does not recognize.

If you extend the format in a way you think belongs in the core schema, open an
issue at
[github.com/MaxWellApexLab/pit-release-gate](https://github.com/MaxWellApexLab/pit-release-gate/issues).

# Bad-Case Attribution Pipeline — Target Specification

## 1. Purpose

Decision traces + human annotations become reviewable bad-case candidates
with deterministic root-cause attribution and a suggested patch target.
Nothing is applied automatically.

## 2. Attribution categories and rules

`attribute_failure(observed, expected) -> AttributionResult`

`observed`: the trace record (decision, capabilityId, errorType,
missingParameters, parameters, …); `expected`: the annotation
(`expectedDecision`, `expectedCapabilityId`).

Rules, evaluated in order (first match wins; secondary signals recorded):

| # | Signal | Category | Patch target example |
|---|---|---|---|
| 1 | Expected SELECT, actual CLARIFY, intent capability matched (`observed.capabilityId == expected.expectedCapabilityId`) | `extraction` | `.../MM.Inventory.GetAvailability.inputs/extraction` |
| 2 | Expected SELECT, actual CLARIFY/REJECT, intent did **not** match; `errorType` unknown-intent-like or no capability | `registry-alias` | `.../MM.Inventory.GetAvailability.aliases` |
| 3 | Expected SELECT, actual SELECT with expected capability, but mismatch on caliber/facts | `caliber` | `ontology Definition id` |
| 4 | Expected REJECT, actual SELECT (or an execution/binding error type) | `binding` for binding-mismatch error types; else `governance` | `executor-bindings.yaml#<bindingId>` |
| 5 | Expected anything, actual REJECT with a `*_BINDING_MISMATCH` / `SOURCE_LOAD_ERROR` / `SNAPSHOT_*` type | `binding` | binding/source pointer |
| 6 | No rule matches | `governance` | — |

> Precedence note: Rule 5 binding-error signals take precedence over Rule 2
> even when the intent did not match — an explicit binding/snapshot error is
> more specific than an alias guess.

Error-type memberships are fixed tables in the module (e.g.
`BINDING_ERROR_TYPES`, `UNKNOWN_INTENT_TYPES`).

`AttributionResult`:

```json
{
  "category": "registry-alias",
  "rationale": "intent did not match; errorType=UNKNOWN_INTENT",
  "evidenceRefs": ["<traceId>"],
  "patchTarget": "registry/capabilities.yaml#MM.Inventory.GetAvailability.aliases",
  "secondarySignals": []
}
```

## 3. Pipeline

Inputs:

- `--traces`: Phase-1 JSONL trace file;
- `--annotations`: JSON array of
  `{"traceId": "...", "expectedDecision": "SELECT", "expectedCapabilityId": "..."}`;
- Traces with `userCorrection: true` and no annotation are emitted as
  `needs-review` candidates without attribution.

Process:

1. Join annotations to traces by `traceId` (missing → error).
2. Only mismatches (`observed.decision != expected`, or expected
   capability differs) produce candidates.
3. Attribute each mismatch; cluster by
   `(category, observed.capabilityId, errorType)`.
4. Write one artifact per case to `<output-dir>/<caseId>.json`:

```json
{
  "schema": "sap-nexus.badcase-review.v1",
  "caseId": "bc-candidate-<short hash>",
  "status": "candidate",
  "sourceTraceId": "dtrace-...",
  "utteranceHash": "...",
  "observed": {"decision": "REJECT", "capabilityId": null, "errorType": "UNKNOWN_INTENT"},
  "expected": {"decision": "SELECT", "capabilityId": "MM.Inventory.GetAvailability"},
  "attribution": {"category": "registry-alias", "...": "..."},
  "clusterKey": "registry-alias|null|UNKNOWN_INTENT",
  "utterance": null
}
```

`utterance` stays `null` until ratification. A `clusters` summary object
(per cluster key: member caseIds) is written to
`<output-dir>/clusters.json`.

## 4. CLI

`.venv/bin/python scripts/attribute_badcases.py --traces <path>
--annotations <path> [--output-dir <path>]`

Default output dir: `runtime/badcase-review`. Stdout one line:

```text
Badcase review: candidates=N clusters=M corrections=K | dir=<relative>
```

## 5. Invariants and error behavior

- Deterministic: identical inputs → identical artifacts (ids derive from
  traceId + expected).
- Writes stay within the output dir; never touches `evals/`, `registry/`,
  or `ontology/`.
- Unreadable inputs → non-zero exit with the original error; an annotation
  matching no trace is a hard error.

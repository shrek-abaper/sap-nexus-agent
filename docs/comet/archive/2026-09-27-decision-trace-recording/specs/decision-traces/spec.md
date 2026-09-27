# Decision Trace Recording — Target Specification

## 1. Purpose

Each agent turn emits one append-only decision trace record. Traces are the
input for the offline review loop and the future attribution/bad-case change.

## 2. Storage and location

- Format: JSONL, one JSON object per line, appended with a single write and
  fsynced. The store is append-only (never rewrites previous lines).
- Location: `SAP_NEXUS_DECISION_TRACE` env (a file path) or default
  `<repo-root>/runtime/traces/decisions.jsonl`. Parent directories are created
  on demand.
- Default location is gitignored (`runtime/*`).

## 3. Record shape

```json
{
  "schema": "sap-nexus.decision-trace.v1",
  "traceId": "dtrace-<uuid4>",
  "recordedAt": "ISO-8601 UTC",
  "utteranceHash": "<sha256 hex>",
  "decision": "SELECT",
  "capabilityId": "MM.Inventory.GetAvailability",
  "parameters": {"material": "DEMOA1", "plant": "1000"},
  "slotRoles": {"material": "EXPLICIT", "plant": "INHERITED"},
  "missingParameters": [],
  "errorType": null,
  "turnId": "...",
  "frameId": "...",
  "gatewayTraceId": "...",
  "model": "rule",
  "userCorrection": false
}
```

- `decision`: `outcome.match_decision.decision_type` when present; otherwise
  mapped from `outcome.status`: `success → SELECT`, `clarification → CLARIFY`,
  `failure → REJECT`; `awaiting_approval → SELECT`; other statuses use the
  raw status string.
- `parameters`: from `call_plan.parameters`; `slotRoles` only when
  `outcome.read_state` provides per-slot roles.
- `model`: `"rule"` by default; when the turn ran an LLM intent adapter, its
  model identifier (or `"llm"` if unavailable).
- `userCorrection`: `true` when an active frame existed and the turn switched
  `capabilityId` away from it (explicit correction heuristic).
- Fields without values are emitted as `null` / empty, never omitted.

## 4. Privacy invariants

- Raw utterances are never stored; only `utteranceHash`.
- Parameter keys matching forbidden names (`credential`, `password`, `token`,
  `url`, `sql`, …) are excluded.
- Traces outside the default path are the operator's explicit responsibility.

## 5. Integration

- `run_query` is wrapped once in `orchestrator.py`: the wrapper builds the
  record after the underlying call returns and appends it via the store.
- Tracing errors are swallowed with a stderr warning; they never alter the
  outcome or its status.
- Tests/runs may disable tracing via an empty `SAP_NEXUS_DECISION_TRACE`
  value (`"0"` or `"off"`) to keep test runs side-effect free; the eval
  runner and unit-test execution set this automatically where needed.

## 6. Error behavior

- Unwritable path → one warning line on stderr, turn unaffected.
- Malformed outcome (no decision derivable) → record with `decision: null`
  and an `errorType: "unclassifiable-outcome"`; still append the line.

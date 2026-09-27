# Outcome

Every agent turn persists an append-only **decision trace** so the offline loop
(architecture v1.2: `IntentDecisionRecord → human review → alias/relation
backflow`) has a real input. Today only WRITE approvals are persisted
(`runtime/traces/approval.jsonl`); capability-selection, clarification,
rejection, and user corrections leave no record and long-tail evidence is lost.

# Scope

1. **New `agent/sap_nexus_agent/decision_traces.py`.**
   - `DecisionTraceStore`: append JSONL; one record per line; fsync after write.
   - Path resolution: env `SAP_NEXUS_DECISION_TRACE`; default
     `<repo-root>/runtime/traces/decisions.jsonl`.
   - `build_decision_record(utterance, outcome)` extracting: `traceId`,
     `recordedAt`, `utteranceHash` (sha256, raw utterance not stored),
     `decision` (five-state from `match_decision`, fallback mapped from
     `status`), `capabilityId`, `parameters` (slot values; slot roles when
     `read_state` slots exist), `missingParameters`, `errorType`,
     `turnId`/`frameId`, `gatewayTraceId`, `model` (`rule` unless an LLM
     adapter ran, then the model id), `userCorrection` marker when the turn
     was an explicit switch vs the active frame.
2. **Integration at a single chokepoint in `orchestrator.py`.** Wrap
   `run_query` with an internal name rebinding so every real turn is recorded;
   recording failures never break the user flow (best-effort, stderr warning).
3. **Tests under `agent/tests/`** for record extraction, append/JSONL behavior,
   chokepoint invocation, and sensitivity (no raw utterance; no secrets).

# Non-goals

- No bad-case generation, LLM attribution/clustering, or candidate patches
  (that is the next change, Phase 2).
- No raw utterance or full parameter payloads committed to git: traces live
  only under gitignored `runtime/` (or an explicitly configured path).
- No changes to selection/extraction behavior; the recorder is observational.
- No ontology-core/ontology-tenant physical split yet (required only before
  real tenant data / open publication of traces).

# Acceptance examples

1. Run a scripted session (SELECT → CLARIFY → REJECT) → all three records
   appended in order; JSON parses line-by-line; SELECT record has the right
   `capabilityId` and parameters; no raw utterance text anywhere in the file.
2. A trace path configured via env is honored; a non-writable path logs a
   warning and the turn still succeeds.
3. New tests pass; full `agent/tests` stays green.

# Constraints and invariants

- Append-only; writes are atomic per line (single `write` + newline + fsync).
- PII discipline: store utterance hash, never the utterance; parameters are
  business identifiers already present in registry/evals, filtered against
  forbidden keys as defense in depth.
- Deterministic in tests: timestamp/ids injectable.

# Decisions

- **D1 (2026-09-27):** One wrapper chokepoint over `run_query` rather than
  edits at every return branch; zero behavior change when tracing is disabled
  or fails.
- **D2 (2026-09-27):** Phase 2 (attribution/bad-case lifecycle) is a separate
  Native change to keep each change independently verifiable.

# Open questions

- Resolved 2026-09-27: scope and placement confirmed by the autonomous
  `/goal` directive (no clarification round-trip).

# Verification expectations

- New unit tests; full agent pytest green.
- Scripted-session end-to-end producing the three record shapes; verify
  gitignore keeps the trace out of git.
- `git status --short` before/after.

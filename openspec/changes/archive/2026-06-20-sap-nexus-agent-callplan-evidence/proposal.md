## Why

The Gateway and Registry baseline is complete, but SAP Nexus Agent still lacks the read-only Python Agent slice that turns Chinese inventory intent into an auditable CallPlan, Gateway execution, ReasoningFact, and Chinese narrative. This change establishes that Agent evidence chain now, while the scope is still limited to the single registered `MM.Inventory.GetAvailability` capability.

## What Changes

- Add a read-only Python Agent MVP for Chinese inventory availability queries.
- Parse `material`, `plant`, and optional `unit` from Chinese user intent.
- Select only the registered `MM.Inventory.GetAvailability` capability from the Registry closed set.
- Block missing `material` or `plant` with clarification before any Gateway call.
- Generate a structured CallPlan before Gateway validate / execute.
- Add a Gateway client for capability-level validate / execute APIs without exposing or accepting arbitrary `rfcName`.
- Convert Gateway `ExecutionResult` into `ReasoningFact` evidence.
- Render Chinese narrative only from fields present in `ReasoningFact`.
- Add eval cases and tests for happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard.

## Capabilities

### New Capabilities

- `agent-callplan-evidence`: Covers the read-only Python Agent path from Chinese intent through closed-set capability selection, CallPlan generation, Gateway execution, ReasoningFact creation, guarded Chinese narration, and eval evidence.

### Modified Capabilities

- None. Existing `capability-registry-gateway` requirements remain the source-of-truth Gateway contract and are consumed without changing Gateway behavior.

## Impact

- Affected code: new `agent/` Python package, Agent tests, eval runner, and eval cases.
- Affected contracts: new CallPlan and ReasoningFact schemas under `schemas/`; existing `schemas/execution-result.schema.json` is consumed.
- Affected systems: Java Gateway must already be running for live smoke, but fast tests and evals must support fixture or fake-client execution without live SAP.
- Safety: no SAP write actions, no arbitrary RFC execution, no `.env`, SAP password, destination config, token, or runtime trace committed.

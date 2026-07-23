# Eval Harness Seed Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `06-eval-harness-seed` |
| Version | `v0.2.0` |
| Status | `Implemented` |
| Created | `2026-06-28` |
| Updated | `2026-07-04` |
| Workstream | Eval Harness seed cases, bad case schema, and regression gate alignment |
| Related Change | `sap-nexus-eval-harness-seed` |
| Current Phase | Implemented directly without OpenSpec archive |

---

## 1. Session Goal

Create the first Eval Harness seed so SAP Nexus Agent quality is measured before adding more executor families or matching complexity.

Target product path:

```text
Natural-language case
-> expected MatchDecision
-> expected capabilityId
-> expected parameters or clarification
-> expected business caliber or reject reason
-> agent run / matching output
-> EvalResult
-> regression pass / fail
```

This workstream is about quality contract and regression readiness. It does not add new executor families, implement retrieval / rerank, build SQL runtime, add OData / CDS / REST runtime, or execute SAP write actions.

---

## 2. Source Of Truth

Read these before opening or implementing the change:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/06-eval-harness-seed.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/gateway-execution-contract/spec.md
registry/capabilities.yaml
scripts/verify-agent-callplan-evidence.sh
```

Expected baseline:

- `MM.Inventory.GetAvailability` remains the current live read capability.
- MVP matching uses rules + Registry exact lookup + required-param checks.
- `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, `SQL_READ`, retrieval / rerank, Graph Registry, and OWL runtime are reserved or Phase 3+.
- `ontologyIri` is reserved metadata; current gates are JSON Schema, Registry validator, OpenSpec validation, and Eval Harness.

---

## 3. Proposed Scope

In scope:

- Define or document the seed bad case storage location.
- Add seed cases for:
  - capability hit
  - parameter completion
  - missing parameter clarification
  - business caliber accuracy
  - unsafe execution rejection
  - narrative grounding
- Align existing eval output from `scripts/verify-agent-callplan-evidence.sh` with the Eval Harness Contract where possible.
- Define how Registry, prompt, matcher, reasoning, and narrator changes select the relevant regression subset.

Out of scope:

- New SAP business capability implementation.
- Capability Index, embedding retrieval, or LLM rerank.
- SQL runtime Gateway.
- OData / CDS / REST runtime.
- SAP write action runtime.
- OWL / SHACL gate implementation.

---

## 4. Eval Case Contract

Seed cases should follow the architecture contract shape:

```json
{
  "caseId": "bc_mm_inventory_missing_plant_001",
  "status": "active",
  "utterance": "查一下 DEMOA1 还有多少可用库存",
  "expectedDecision": "CLARIFY",
  "expectedCapabilityId": "MM.Inventory.GetAvailability",
  "expectedParameters": {
    "material": "DEMOA1"
  },
  "expectedBusinessCaliber": {
    "caliberId": "MM.Inventory.AvailabilityForCommitment.v1"
  },
  "expectedClarification": {
    "missingFields": ["plant"],
    "questionIntent": "ask_for_plant"
  },
  "expectedRejectReason": null,
  "sourceTraceId": null,
  "regressionTags": ["MM", "inventory", "missing-parameter"],
  "createdAt": "2026-06-28T00:00:00+08:00"
}
```

---

## 5. Seed Coverage Targets

| Area | Required seed case |
|---|---|
| Capability hit | Inventory availability utterance selects `MM.Inventory.GetAvailability` |
| Parameter completion | Material and plant are extracted without guessing defaults |
| Missing parameter | Missing `plant` returns `CLARIFY` and does not call Gateway |
| Business caliber | Availability response uses declared facts and does not equate unrestricted stock with ATP blindly |
| Unsafe execution | Raw RFC / raw SQL / raw URL request returns `REJECT` |
| Narrative grounding | Narrator only cites fields present in `ReasoningFact` |

---

## 6. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Schema | Every seed case has utterance, expected decision, expected capability, expected parameters or clarification, tags, and expected reject reason when applicable |
| Regression | Seed cases can be run locally or through the existing eval harness command documented by the change |
| Traceability | Failing cases include enough context to add a regression or link a `sourceTraceId` |
| Gate mapping | Registry, prompt, matcher, reasoning, and narrator changes state which seed subsets must run |
| Scope discipline | No new executor family, retrieval / rerank, OWL gate, or write runtime is introduced by this change |

Recommended verification after implementation:

```bash
git diff --check
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json
```

---

## 7. Implementation Notes - 2026-07-04

Completed directly without Comet / OpenSpec archive because the work stayed within the existing Eval Harness boundary and did not change capability, registry schema, Gateway contract, executor family, or SAP WRITE behavior.

Implemented artifacts:

- `evals/eval_harness_seed_cases.json` stores the first active seed / bad-case set.
- `agent/sap_nexus_agent/eval.py` accepts the Eval Harness contract fields while preserving the legacy `expected` case format.
- `agent/tests/test_eval_runner.py` covers both legacy inventory evals and the new seed contract.
- `scripts/verify-agent-callplan-evidence.sh` now runs both eval files.

Seed coverage now includes:

| Area | Seed case |
|---|---|
| Capability hit | `bc_mm_inventory_capability_hit_001` |
| Parameter completion | `bc_mm_inventory_parameter_completion_001` |
| Missing parameter clarification | `bc_mm_inventory_missing_plant_001` |
| Business caliber accuracy | `bc_mm_inventory_business_caliber_001` |
| Unsafe execution rejection | `bc_mm_inventory_unsafe_raw_request_001` |
| Narrative grounding | `bc_mm_inventory_narrative_grounding_001` |

## Session Closeout - 2026-07-04

### Completed

- Added the first Eval Harness seed file and local runner contract assertions.
- Kept matching at MVP rules + Registry exact lookup; no retrieval / rerank / planner was added.
- Kept executor scope unchanged; no SQL, OData, CDS, REST, or SAP WRITE runtime was added.

### Verified

- Command: `git diff --check -- .`
- Result: passed
- Command: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- Result: `Registry contract valid: registry/capabilities.yaml`
- Command: `.venv/bin/python -m pytest agent/tests/test_eval_runner.py -q`
- Result: `2 passed`
- Command: `.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json`
- Result: `Eval passed: 6/6`
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: `55 passed, 1 skipped`; legacy eval `7/7`; seed eval `6/6`; OpenSpec `5 passed, 0 failed`
- Command: `openspec list --json`
- Result: `{"changes":[]}`

### Blockers

- None.

### Next Start Here

1. Run the full verification bundle in `scripts/verify-agent-callplan-evidence.sh`.
2. Start `sap-nexus-second-sap-read-capability` only after this seed baseline remains green.
3. Add future bad cases to `evals/eval_harness_seed_cases.json` when matcher, prompt, reasoning, narrator, or Registry behavior changes.

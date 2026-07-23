# Capability Matching Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `08-capability-matching-contract` |
| Version | `v0.2.0` |
| Status | `Deferred / Phase 3+` |
| Created | `2026-06-26` |
| Updated | `2026-06-28` |
| Workstream | Deferred matching scale-up; MVP keeps rules + Registry exact lookup and MatchDecision only |
| Related Change | `sap-nexus-capability-matching-contract` |
| Current Phase | Deferred until scale thresholds or Eval bad cases justify retrieval / rerank |

---

## 1. Session Goal

This runbook is now deferred. MVP matching does not build a Capability Index, embedding retrieval, LLM rerank, or planner. The current product path is intentionally small:

```text
User utterance
-> Rule / keyword / trigger phrase match
-> Registry exact capability lookup
-> Required parameter check
-> Governance filter
-> MatchDecision
-> CallPlan
```

This workstream should restart only when capability scale or Eval bad cases prove rules + Registry exact lookup are insufficient.

---

## 2. Source Of Truth

Read these before opening or implementing the change:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/08-capability-matching-contract.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
docs/wiki/sap-nexus-agent-technology-selection.md
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/registry-ontology-contract/spec.md
registry/README.md
registry/capabilities.yaml
```

Expected baseline:

- `sap-nexus-registry-ontology-contract` and `sap-nexus-gateway-execution-contract` are complete and archived.
- The active capability catalog remains small, closed-set, and Registry-owned.
- MVP matching uses rules + Registry exact lookup; LLM output remains advisory until accepted by deterministic Harness.
- Gateway continues to accept only `capabilityId` / allowlisted `bindingId` paths, never request-provided technical execution details.

---

## 3. Proposed Scope

Current MVP scope:

- Keep `MatchDecision` with five decisions: `SELECT`, `CLARIFY`, `SHOW_OPTIONS`, `REJECT`, `ESCALATE_TO_PLANNER`.
- Use rules, trigger phrases, keywords, existing Registry metadata, required-param checks, and governance fail-closed.
- Add matching-related seed cases through `08-eval-harness-seed.md` before changing matcher complexity.

Deferred until Phase 3+:

- Capability Index derivation from Registry.
- embedding retrieval.
- LLM rerank.
- candidate scoring beyond lightweight deterministic signals.
- Multi-capability DAG planner implementation.
- Knowledge Graph / Graph Registry runtime dependency.

Out of scope always:

- Automatic capability creation or self-registration by LLM.
- Request-provided `capabilityId`, `bindingId`, `rfcName`, URL, SQL, endpoint, headers, `credentialRef`, or JSON mapping.

---

## 4. MatchDecision Contract

MVP decision set:

| Decision | Meaning | Next Step |
|---|---|---|
| `SELECT` | One registered capability is clearly selected and required inputs are complete | Build single-capability `CallPlan` |
| `CLARIFY` | A candidate is likely but required inputs are missing or ambiguous | Ask user a clarification question |
| `SHOW_OPTIONS` | Multiple candidates are plausible and safe automatic selection is not justified | Show 2-3 business options |
| `REJECT` | No registered capability, unsafe request, permission failure, or request-owned technical execution detail | Reject with traceable reason |
| `ESCALATE_TO_PLANNER` | User goal requires multiple capabilities or reasoning over multiple facts | Record and explain; MVP does not auto-plan or execute DAG |

Representative output shape:

```json
{
  "decision": "CLARIFY",
  "domain": "MM.Inventory",
  "candidateCapabilityId": "MM.Inventory.GetAvailability",
  "extractedParameters": {
    "material": "A100"
  },
  "missingParameters": ["plant"],
  "clarificationQuestion": "请问要查询哪个工厂的库存可用量？",
  "candidateTrace": [
    {
      "capabilityId": "MM.Inventory.GetAvailability",
      "matchedSignals": ["domain", "intentType", "material", "availability"],
      "governanceStatus": "PASSED",
      "parameterFit": "MISSING_REQUIRED_INPUT"
    }
  ]
}
```

---

## 5. Safety Notes

- Do not let LLM create `capabilityId`, `bindingId`, `rfcName`, URL, endpoint, HTTP method, headers, `credentialRef`, or JSON mapping.
- Do not let matching output execute Gateway directly. Matching output must go through CallPlan or planner.
- Do not guess required SAP parameters. Missing or ambiguous required inputs must produce `CLARIFY`.
- Treat write intent as action proposal / approval scope, not direct execution.
- Treat complex shortage or replenishment requests as `ESCALATE_TO_PLANNER`, not a single inventory read.

---

## 6. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Closed set | Every candidate comes from Registry; Capability Index is deferred |
| MatchDecision | Five decision types have schema, examples, trace fields, and Eval Harness seed coverage |
| Governance | Unsafe, disabled, write, unapproved, or unauthorized candidates fail closed |
| Parameters | Missing and ambiguous required inputs produce `CLARIFY` |
| Rejection | Bare RFC / endpoint / technical override requests produce `REJECT` |
| Planner boundary | Multi-fact goals produce `ESCALATE_TO_PLANNER`; no MVP auto-planning |
| Eval | Matching evals cover direct hit, synonym hit, missing parameter, ambiguous candidate, unsafe technical request, write intent, and planner escalation |

Recommended verification after implementation:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
# plus future matching-specific tests/evals documented by the change
```

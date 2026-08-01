# Capability Matching Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `08-capability-matching-contract` |
| Version | `v0.3.1` |
| Status | `S2-A Done / Phase 3+ Scale-up Deferred` |
| Created | `2026-06-26` |
| Updated | `2026-07-25` |
| Workstream | S2-A baseline semantic decision hardening done (archived in sap-nexus-planner-dry-run); Phase 3+ retrieval / rerank later |
| Related Change | `sap-nexus-planner-dry-run` (S2-A); `sap-nexus-capability-matching-contract` (Phase 3+ scale-up) |
| Current Phase | Implement explicit five-state MatchDecision, multi-intent / ambiguity handling, visibility and matcher Eval before S2-B dry-run |

---

## 1. Session Goal

This runbook now separates baseline decision correctness from scale-stage retrieval. S2-A does not build a Capability Index, embedding retrieval, LLM rerank, or executable planner, but it must turn the current implicit selector behavior into a deterministic five-state `MatchDecision`:

```text
User utterance
-> Multi-intent / ambiguity detection
-> Server-owned context + visibility pre-filter
-> Rule / alias / domain / Registry exact candidate discovery
-> Required parameter and governance fit
-> MatchDecision
-> CallPlan / clarification / options / rejection / planner handoff
```

Current runtime status: `IntentParseResult -> SelectionResult` supports three active capabilities, missing-parameter clarification and technical-override rejection, but does not implement a first-class five-state `MatchDecision`. The rule parser returns the first matching intent, so a request containing inventory and purchase-order goals can be silently reduced to inventory. S2-A must close this gap before S2-B generates GoalSpec / PlanDraft candidates.

Only the scale-up portion restarts when capability scale or Eval bad cases prove lightweight discovery insufficient.

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
- Current code does not yet guarantee `SHOW_OPTIONS` or `ESCALATE_TO_PLANNER`; documentation must not present those decisions as implemented runtime behavior before S2-A verification.

---

## 3. Proposed Scope

S2-A baseline scope:

- Implement `MatchDecision` with five decisions: `SELECT`, `CLARIFY`, `SHOW_OPTIONS`, `REJECT`, `ESCALATE_TO_PLANNER`.
- Detect single-goal, parallel multi-goal, conditional multi-goal and ambiguous-candidate requests before selecting a capability.
- Use rules, aliases, domain / businessObject, existing Registry metadata, required-param checks, visibility and governance fail-closed.
- Bind decision evidence to candidate reasons, Registry Snapshot and trace.
- Add matching-specific Eval cases before S2-B planner generation.
- Define the safe `CapabilityCard` projection consumed by S2-B.

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
  "registrySnapshotId": "sha256:<snapshot>",
  "traceId": "match-<id>",
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

Decision rules:

- One uniquely justified capability with complete required inputs -> `SELECT`.
- One clear capability with missing or ambiguous required inputs -> `CLARIFY`.
- Two or three same-level candidates remain plausible after deterministic scoring -> `SHOW_OPTIONS`.
- Multiple business goals or required Facts are detected -> `ESCALATE_TO_PLANNER`.
- Unknown, invisible, unsafe or technical-override request -> `REJECT`.
- Multiple goals must never be reduced to the first keyword match.

### 4.1.1 CLARIFY Cross-Turn Continuation (Multi-Turn Slot-Filling)

The five-state `MatchDecision` is single-turn by default: each utterance is parsed independently. This produces a multi-turn gap when a user answers a `CLARIFY` with bare parameters (e.g. turn 1 "你能查库存吗" -> `CLARIFY` missing [material, plant]; turn 2 "DEMOA2 1000" matches no capability keyword and falls to `REJECT(UNSUPPORTED_INTENT)`). This subsection defines the cross-turn continuation contract for the lightweight multi-turn instance introduced in technical-architecture §4.2.2.

**PendingClarification state (advisory, in-memory):** when a turn resolves to `CLARIFY`, the backend records `PendingClarification { capability_id, parameters, missing_parameters, clarification_text }` under `sessions: Map<conversationId, SessionState>`. This is `ConversationState` (advisory context), not execution authority; it does not interact with `CallPlan` / `ApprovalRecord` lifecycle.

**Sticky-CLARIFY resolution:** when the next utterance arrives and the session has a pending CLARIFY:

- If the utterance contains **no primary keyword** of any registered capability, treat it as a slot-fill answer for the pending `capability_id`. Re-run that capability's parameter extractor on the new utterance, merge into the pending `parameters`, and re-evaluate `missing_parameters`. If complete -> `SELECT`; if still missing -> `CLARIFY` again with the reduced missing set.
- If the utterance contains a primary keyword, treat it as a new turn: discard the pending CLARIFY and run the normal single-turn pipeline.

This mechanism is the mandatory baseline for both rule and LLM paths (the rule path must work without any LLM call, preserving the hybrid safe-fallback contract).

**IntentAdapter signature:** `Callable[[str], IntentParseResult]` extends to `Callable[[str, ConversationContext | None], IntentParseResult]`, where `ConversationContext` carries `pending_clarification` and optional `history`. Default `None` preserves all existing single-turn tests unchanged.

**History re-injection (LLM path only):** when the LLM path consumes `history`, it MUST apply the authority/untrusted-data separation contract from §4.2.2 (static authority rules as `SystemMessage`; historical text as a hidden `<durable_context_data>` `HumanMessage` marked as data). The rule path does not call the LLM and is unaffected.

**v1 scope and non-goals:** v1 covers `CLARIFY` cross-turn slot-fill only. Cross-turn `ESCALATE_TO_PLANNER` disambiguation, `SHOW_OPTIONS` selection, coexistence of approval-pending with CLARIFY-pending, cross-restart persistence, and long-conversation compaction are explicit non-goals (P0B or independent change). The `ConversationState` interface is aligned with the §4.2.1 three-layer stratification so P0B can swap the in-memory Map for a durable store without restructuring the advisory layer.

**Multi-value batch query (cross-reference):** the `awaiting_batch_confirm` / `continue_batch` workflow (multi-parameter split, per-combination execution, READ-only v1) built on this session layer is documented in `docs/runbooks/12-conversational-context-and-multi-value-batch.md`; the architecture contract lives in technical-architecture §4.2.3.

---

## 4.1 CapabilityCard Projection For S2-B

S2-A publishes the safe projection contract; S2-B implements progressive discovery. Include:

```text
capabilityId
capabilityVersion
domain
businessObject
kind
intentSummary
aliases
positiveExamples
negativeExamples
inputSemanticTypes
outputFactTypes
sideEffect
requiresApproval
visibilityScope
registrySnapshotId
evalLinkage
```

Exclude `rfcName`, service URL, entity set, HTTP method/headers, credential reference, raw SQL, binding implementation and technical mapping. Apply visibility before candidate cards enter model context. Local S2 may use a fixed synthetic governed context; shared candidate discovery requires the separate trusted-identity gate.

---

## 5. Safety Notes

- Do not let LLM create `capabilityId`, `bindingId`, `rfcName`, URL, endpoint, HTTP method, headers, `credentialRef`, or JSON mapping.
- Do not let matching output execute Gateway directly. Matching output must go through CallPlan or planner.
- Do not guess required SAP parameters. Missing or ambiguous required inputs must produce `CLARIFY`.
- Treat write intent as action proposal / approval scope, not direct execution.
- Treat complex shortage or replenishment requests as `ESCALATE_TO_PLANNER`, not a single inventory read.
- Do not treat explicit capability selection as permission, approval or publish authority.
- Do not expose an invisible capability to the model and rely on execution-time rejection.

---

## 6. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Closed set | Every candidate comes from Registry; Capability Index is deferred |
| MatchDecision | Five decision types have schema, examples, candidate reasons, Registry Snapshot, trace fields, and Eval coverage |
| Current/target boundary | Documentation and traces distinguish current selector behavior from verified S2-A behavior |
| Multi-intent | Parallel or conditional multi-goal requests produce `ESCALATE_TO_PLANNER`, never first-match `SELECT` |
| Ambiguity | Multiple plausible same-level candidates produce `SHOW_OPTIONS` |
| Visibility | Candidate cards are filtered by server-owned governed context before model exposure |
| Governance | Unsafe, disabled, write, unapproved, or unauthorized candidates fail closed |
| Parameters | Missing and ambiguous required inputs produce `CLARIFY` |
| Rejection | Bare RFC / endpoint / technical override requests produce `REJECT` |
| Planner boundary | Multi-fact goals produce `ESCALATE_TO_PLANNER`; no MVP auto-planning |
| Eval | Matching evals cover direct/synonym hit, missing parameter, multi-intent, ambiguous candidate, capability gap, visibility leakage, unsafe technical request, prompt injection, write intent and planner escalation; false `SELECT` fails regression |

Recommended verification after implementation:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
# plus future matching-specific tests/evals documented by the change
```

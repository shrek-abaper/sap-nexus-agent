# Governed READ Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace destructive `LastContext` merging with a typed, deterministic, durable READ context state machine so ambiguous multi-turn input cannot create a wrong `CallPlan` or reach SAP.

**Architecture:** LLM and rule parsers emit advisory slot candidates. A pure Python `ContextReducer` combines those candidates with a versioned `ReadContextFrame`, Registry metadata, and explicit user evidence; a fail-closed decision gate is the only path from a `READY` frame to `SELECT`. The TypeScript runtime owns durable conversation sequencing with a lease, compare-and-swap, and `turnId` idempotency. The Java Gateway remains a second defensive boundary and validates Registry-declared patterns without performing language or coreference reasoning.

**Tech Stack:** Python 3.12/dataclasses/pytest, TypeScript 5.8/Vitest/JSON session files, Java 21/Gradle/JUnit, YAML capability Registry, existing Agent Eval and release-gate runners.

## Global Constraints

- This implementation meets the project HEAVY signal because it touches more than two modules and more than five files. Start execution through `/comet` using Native change name `sap-nexus-governed-read-context`.
- The first execution action is Native Shape. Do not edit implementation code until the workflow requests and receives Shape confirmation. This plan is preparation, not Shape confirmation.
- Work on the currently checked-out branch. Do not create or switch branches. Do not commit, archive, or push unless the user explicitly authorizes that action.
- Scope is all READ capabilities. WRITE selection, `ApprovalRecord`, Human Approval, Action continuation, and SAP WRITE execution remain unchanged and outside the authority of `ConversationReadState`.
- LLM output, recent turns, summaries, migrated `LastContext`, and `PendingInteraction` are advisory. None may supply principal, visibility, Registry authority, technical binding, credential, RFC name, approval, or WRITE authority.
- A non-`READY` frame, failed lease, failed CAS, duplicate in-flight turn, stale Registry binding, or principal mismatch must produce zero Gateway validation and execution calls.
- Use offline deterministic, recorded-LLM, fake-Gateway, and restart/concurrency tests first. Do not run a live LLM or live SAP READ smoke automatically; record live smoke as `not_run` unless separately authorized.
- Preserve the legacy path only as an observable compatibility bridge during shadow rollout. Do not remove it until every hard gate added in Task 8 has passed again during Task 9 and all callers are migrated.
- For each task, record current snapshot-bound Native evidence using the workflow-provided command. Never write a passed evidence receipt for a command that was not run.
- Every commit step below is conditional: execute it only after explicit user authorization, stage only the listed files, and inspect the staged diff before committing.

## Target Interfaces

```text
IntentEnvelope / deterministic spans
                |
                v
        ContextCandidateSet
                |
                v
ReadContextFrame + RegistrySnapshot -> ContextReducer -> ContextResolution
                                                        |
                                                        v
                                               ContextDecisionGate
                                                        |
                     CLARIFY / SHOW_OPTIONS / ESCALATE <-+-> SELECT
                                                                    |
                                                                    v
                                                             READ CallPlan
```

The canonical persisted concept is `ConversationSessionV2`; its TypeScript implementation is named `SessionStateV2` to evolve the existing `SessionState` contract. The Python process receives a serialized `ConversationReadState` view for semantic resolution, but the TypeScript durable store owns the lease, version, idempotency, and persist-before-execute protocol.

---

### Task 1: Versioned Python READ context contracts and legacy migration

**Files:**
- Create: `agent/sap_nexus_agent/read_context.py`
- Create: `agent/sap_nexus_agent/context_migration.py`
- Create: `agent/tests/test_read_context.py`
- Create: `agent/tests/test_context_migration.py`
- Modify: `agent/sap_nexus_agent/conversation_context.py`

**Interfaces:**
- Consumes: existing `ConversationContext`, `LastContext`, Registry snapshot id, capability version, `turnId`.
- Produces: immutable `SlotBinding`, `ReadContextFrame`, `PendingInteraction`, `ConversationReadState`, and `migrate_legacy_context(...)`.

- [ ] **Step 1: Write failing round-trip and invariant tests**

```python
def test_ready_frame_rejects_a_non_resolved_slot():
    with pytest.raises(ValueError, match="READY frame"):
        ReadContextFrame(
            frame_id="frame-1",
            capability_id="MM.Inventory.GetAvailability",
            slots={"material": cleared_slot("material", "turn-2")},
            status="READY",
            created_turn_id="turn-1",
            updated_turn_id="turn-2",
            registry_snapshot_id="snapshot-1",
            capability_version="2",
        )

def test_pending_interaction_is_bound_to_frame_version_and_snapshot():
    pending = PendingInteraction.slot_clarification(
        frame_id="frame-1",
        expected_fields=("material",),
        state_version=3,
        registry_snapshot_id="snapshot-1",
        expires_at="2026-08-06T09:15:00Z",
    )
    assert pending.binding_key == ("frame-1", 3, "snapshot-1")
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest agent/tests/test_read_context.py agent/tests/test_context_migration.py -q`

Expected: FAIL during collection because `sap_nexus_agent.read_context` and `sap_nexus_agent.context_migration` do not exist.

- [ ] **Step 3: Implement the minimum immutable contracts**

```python
FrameStatus = Literal["COLLECTING", "READY", "CONFLICTED", "STALE"]
SlotState = Literal["RESOLVED", "CONFLICTED", "CLEARED"]
SlotProvenance = Literal[
    "EXPLICIT", "CONFIRMED", "INHERITED", "MODEL_CANDIDATE", "INHERITED_LEGACY"
]

@dataclass(frozen=True)
class SlotBinding:
    name: str
    value: str | None
    candidates: tuple[str, ...]
    state: SlotState
    provenance: SlotProvenance
    source_turn_id: str
    source_span: tuple[int, int] | None
    issues: tuple[str, ...]

@dataclass(frozen=True)
class ReadContextFrame:
    frame_id: str
    capability_id: str
    slots: Mapping[str, SlotBinding]
    status: FrameStatus
    created_turn_id: str
    updated_turn_id: str
    registry_snapshot_id: str
    capability_version: str
```

Use explicit `to_dict()`/`from_dict()` methods. Validate legal enum values and structural invariants, but keep required-input completeness in the Reducer where the Registry descriptor is available.

- [ ] **Step 4: Add legacy migration tests**

Cover `SELECT`, `CLARIFY`, empty parameters, malformed source payload, and preservation of the source object. A migrated frame must be `STALE`; each copied slot must be `INHERITED_LEGACY`; migration must never return a directly executable `READY` frame.

```python
state = migrate_legacy_context(legacy, snapshot_id="snapshot-2", turn_id="turn-9")
assert state.active_frame.status == "STALE"
assert state.active_frame.slots["plant"].provenance == "INHERITED_LEGACY"
```

- [ ] **Step 5: Implement the compatibility container**

Add optional `read_state` and `schema_version` fields to `ConversationContext` without changing legacy serialization when those fields are absent. Do not add merge policy to `conversation_context.py`.

- [ ] **Step 6: Verify GREEN**

Run: `.venv/bin/python -m pytest agent/tests/test_read_context.py agent/tests/test_context_migration.py agent/tests/test_cli_context.py -q`

Expected: PASS; legacy CLI JSON still deserializes, and migrated context is never `READY`.

- [ ] **Step 7: Conditional commit**

Only after explicit user authorization:

```bash
git add agent/sap_nexus_agent/read_context.py agent/sap_nexus_agent/context_migration.py agent/sap_nexus_agent/conversation_context.py agent/tests/test_read_context.py agent/tests/test_context_migration.py
git diff --cached --check
git commit -m "feat: add versioned read context contracts"
```

---

### Task 2: Deterministic candidate extraction and semantic validation

**Files:**
- Create: `agent/sap_nexus_agent/context_candidates.py`
- Create: `agent/tests/test_context_candidates.py`
- Modify: `agent/sap_nexus_agent/registry_loader.py`
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Modify: `agent/tests/test_registry_loader.py`
- Modify: `agent/tests/test_llm_intent.py`

**Interfaces:**
- Consumes: current utterance, advisory `IntentEnvelope`, visible `CapabilityDescriptor`, input aliases/examples/semantic metadata.
- Produces: `ContextCandidateSet` containing typed deterministic and model candidates plus discard reasons; no Session mutation.

- [ ] **Step 1: Write failing extraction tests for the real wording**

```python
def test_f101_followed_by_plant_is_a_deterministic_plant_candidate():
    candidates = extract_context_candidates(
        "查下这个物料 1000 工厂库存", inventory_descriptor(), bad_model_envelope()
    )
    assert candidates.for_slot("plant").deterministic_values == ("1000",)
    assert candidates.for_slot("material").model_values == ("1000",)
    assert "invalid_semantic_value:plant:工厂" in candidates.discard_reasons

def test_model_candidate_alone_cannot_be_marked_explicit():
    candidate = extract_context_candidates("查库存", inventory_descriptor(), model_only())
    assert candidate.for_slot("material").sources == ("MODEL_CANDIDATE",)
```

Also cover `工厂 1000`, `工厂改成 1000`, `物料改成 M001`, explicit confirmation, `换个物料`, technical-field injection, malformed model JSON, and LLM unavailable.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest agent/tests/test_context_candidates.py -q`

Expected: FAIL because `context_candidates.py` does not exist.

- [ ] **Step 3: Extend Registry descriptors without inventing execution authority**

```python
@dataclass(frozen=True)
class InputDescriptor:
    name: str
    semantic_name: str
    semantic_type: str
    binding_kind: str | None
    required: bool
    type: str
    min_length: int | None
    max_length: int | None
    pattern: str | None
```

Load these fields from `registry/capabilities.yaml`. Do not load `sapParameter`, executor, binding id, credential, or RFC into candidate extraction.

- [ ] **Step 4: Implement pure candidate extraction**

```python
def extract_context_candidates(
    utterance: str,
    descriptor: CapabilityDescriptor,
    envelope: IntentEnvelope | None,
) -> ContextCandidateSet: ...
```

Use Registry examples/semantic names only as language hints. Deterministic label and adjacency evidence may identify a slot; lexical shape may reject an impossible value but must not assign an ambiguous token to a business role. LLM values remain `MODEL_CANDIDATE` regardless of confidence.

- [ ] **Step 5: Make LLM context output explicitly advisory**

Keep `parse_with_hybrid()` backward compatible, but add a candidate-producing entry that never calls `resolve_with_context()` and never merges `LastContext` into trusted parameters.

```python
def parse_context_candidates(
    text: str,
    *,
    client: JsonChatClient | None,
    catalog: IntentCatalog,
) -> IntentEnvelope: ...
```

The prompt may include Registry examples and semantic slot descriptions, but the output contract must state that the result is advisory and will be deterministically validated.

- [ ] **Step 6: Verify GREEN**

Run: `.venv/bin/python -m pytest agent/tests/test_context_candidates.py agent/tests/test_registry_loader.py agent/tests/test_llm_intent.py -q`

Expected: PASS; the recorded bad model value is retained as evidence but is not promoted to an explicit slot.

- [ ] **Step 7: Conditional commit**

Only after explicit user authorization:

```bash
git add agent/sap_nexus_agent/context_candidates.py agent/sap_nexus_agent/registry_loader.py agent/sap_nexus_agent/llm_intent.py agent/tests/test_context_candidates.py agent/tests/test_registry_loader.py agent/tests/test_llm_intent.py
git diff --cached --check
git commit -m "feat: extract advisory read context candidates"
```

---

### Task 3: Pure ContextReducer and the exact failure sequence

**Files:**
- Create: `agent/sap_nexus_agent/context_reducer.py`
- Create: `agent/tests/test_context_reducer.py`
- Create: `agent/tests/fixtures/governed_read_context_cases.json`

**Interfaces:**
- Consumes: prior `ConversationReadState`, current `ContextCandidateSet`, visible capability descriptor, snapshot/version, `turnId`, and server time.
- Produces: immutable `ContextResolution(next_state, operation, issues, evidence)`; performs no IO and calls neither Gateway nor SAP.

- [ ] **Step 1: Freeze the three-turn regression before implementation**

```python
turn_1 = reduce_context(empty_state(), explicit_inventory("DEMOA2", "5100"))
assert turn_1.next_state.active_frame.status == "READY"

turn_2 = reduce_context(turn_1.next_state, utterance_candidates("换个物料能查吗"))
assert turn_2.operation == "CLEAR_SLOT"
assert turn_2.slot("material").state == "CLEARED"
assert turn_2.slot("plant").value == "5100"

turn_3 = reduce_context(
    turn_2.next_state,
    candidates_for("查下这个物料 1000 工厂库存", model={"material": "1000", "plant": "工厂"}),
)
assert turn_3.next_state.active_frame.status in {"COLLECTING", "CONFLICTED"}
assert turn_3.slot("plant").value == "1000"
assert turn_3.slot("material").state != "RESOLVED"
```

The JSON fixture must also include the direct two-turn plant switch and the explicit Turn 4 correction.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest agent/tests/test_context_reducer.py -q`

Expected: FAIL because `ContextReducer` is missing.

- [ ] **Step 3: Implement operation classification first**

```python
ContextOperation = Literal[
    "CONTINUE_FRAME",
    "REPLACE_SLOT",
    "CLEAR_SLOT",
    "SWITCH_CAPABILITY",
    "CONFIRM_PENDING",
    "REJECT_PENDING",
    "NEW_MULTI_GOAL",
]
```

An explicit correction or valid pending answer outranks deterministic labels, which outrank inherited confirmed values, which outrank model candidates. A model candidate alone cannot resolve a required slot. `CLEARED`, `CONFLICTED`, and `INHERITED_LEGACY` values cannot be silently inherited into `READY`.

- [ ] **Step 4: Implement immutable reduction and state derivation**

```python
@dataclass(frozen=True)
class ContextResolution:
    next_state: ConversationReadState
    operation: ContextOperation
    changed_slots: tuple[str, ...]
    issues: tuple[str, ...]
    evidence: tuple[ResolutionEvidence, ...]

def reduce_context(request: ContextReductionRequest) -> ContextResolution: ...
```

Derive `READY` only when the unique visible READ capability is current-snapshot compatible, all required inputs are `RESOLVED`, semantic validation passes, and no conflict or unconsumed pending item remains. Move a switched frame to `recent_frames`, capped at two. Never automatically restore a recent frame by similarity.

- [ ] **Step 5: Add property-style invariant cases**

Parameterize all slot operations across inventory and purchase-order READ descriptors. Assert immutability, deterministic replay, no cross-capability incompatible inheritance, no multiple active frames, and no more than one pending interaction.

- [ ] **Step 6: Verify GREEN**

Run: `.venv/bin/python -m pytest agent/tests/test_context_reducer.py -q`

Expected: PASS; Case B remains non-READY until explicit Turn 4 correction, after which parameters equal `{material: DEMOA2, plant: 1000}`.

- [ ] **Step 7: Conditional commit**

Only after explicit user authorization:

```bash
git add agent/sap_nexus_agent/context_reducer.py agent/tests/test_context_reducer.py agent/tests/fixtures/governed_read_context_cases.json
git diff --cached --check
git commit -m "feat: add deterministic read context reducer"
```

---

### Task 4: Fail-closed context decision gate and shadow-mode orchestration

**Files:**
- Create: `agent/sap_nexus_agent/context_decision_gate.py`
- Create: `agent/tests/test_context_decision_gate.py`
- Modify: `agent/sap_nexus_agent/capability_selector.py`
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Modify: `agent/sap_nexus_agent/workbench_output.py`
- Modify: `agent/tests/test_orchestrator.py`
- Modify: `agent/tests/test_workbench_output.py`

**Interfaces:**
- Consumes: `ContextResolution`, current `VisibleCapabilitySet`, current Registry snapshot, and existing five-state selection contracts.
- Produces: `ContextDecisionResult(decision, resolution_report)` and shadow comparison evidence; legacy remains authoritative in this task.

- [ ] **Step 1: Write decision-gate tests before integration**

```python
@pytest.mark.parametrize("status", ["COLLECTING", "CONFLICTED", "STALE"])
def test_non_ready_frame_cannot_select(status):
    result = decide_read_context(frame_with(status=status), visible_inventory())
    assert result.decision.decision_type != "SELECT"
    assert result.call_plan_parameters is None

def test_ready_frame_uses_only_resolved_slots():
    result = decide_read_context(ready_inventory_frame(), visible_inventory())
    assert result.decision.parameters == {"material": "DEMOA2", "plant": "1000"}
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest agent/tests/test_context_decision_gate.py -q`

Expected: FAIL because `context_decision_gate.py` does not exist.

- [ ] **Step 3: Implement the gate as the only Frame-to-decision adapter**

```python
def decide_read_context(
    resolution: ContextResolution,
    *,
    visible: VisibleCapabilitySet,
    current_snapshot_id: str,
) -> ContextDecisionResult: ...
```

Return `CLARIFY` for missing/conflicted slots, `SHOW_OPTIONS` for bounded capability ambiguity, `ESCALATE_TO_PLANNER` for multiple goals, and `REJECT` for visibility/closed-set/technical violations. Only `READY` may return `SELECT`.

- [ ] **Step 4: Add shadow-mode integration tests**

Inject the bad model envelope and assert the legacy path still determines behavior during this phase, while the output records a redacted `contextShadow` object:

```json
{
  "legacyDecision": "SELECT",
  "frameV2Decision": "CLARIFY",
  "slotDiff": ["material", "plant"],
  "wouldBlockLegacyExecution": true,
  "wouldClarify": true
}
```

Shadow v2 must not call Gateway, mutate the authoritative Session, or include raw history/model payloads.

- [ ] **Step 5: Wire shadow mode behind one server-owned switch**

Add a single explicit runtime mode such as `READ_CONTEXT_MODE=legacy|shadow|v2`, defaulting to `legacy` until Task 7. Do not let the request or model set it. Reuse the existing parsed envelope and Registry snapshot; do not make a second LLM call.

- [ ] **Step 6: Verify GREEN and existing behavior**

Run: `.venv/bin/python -m pytest agent/tests/test_context_decision_gate.py agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py -q`

Expected: PASS; shadow evidence identifies the real false `SELECT` without changing legacy execution semantics.

Run: `scripts/verify-agent-callplan-evidence.sh`

Expected: PASS; every created CallPlan remains closed-set and snapshot-bound.

- [ ] **Step 7: Conditional commit**

Only after explicit user authorization:

```bash
git add agent/sap_nexus_agent/context_decision_gate.py agent/sap_nexus_agent/capability_selector.py agent/sap_nexus_agent/orchestrator.py agent/sap_nexus_agent/workbench_output.py agent/tests/test_context_decision_gate.py agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py
git diff --cached --check
git commit -m "feat: add read context shadow decision gate"
```

---

### Task 5: Registry and Gateway semantic pattern validation

**Files:**
- Modify: `registry/capabilities.yaml`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/registry/CapabilityDefinition.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryLoader.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryValidator.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/validation/CapabilityValidationService.java`
- Modify: `services/gateway/core/src/test/java/com/sapnexus/gateway/registry/CapabilityRegistryLoaderTest.java`
- Create: `services/gateway/core/src/test/java/com/sapnexus/gateway/validation/CapabilityValidationServiceTest.java`

**Interfaces:**
- Consumes: optional Registry `pattern` on an input field.
- Produces: compiled fail-fast Registry metadata and `INVALID_PARAMETER` before SAP for pattern mismatch; no language or context inference.

- [ ] **Step 1: Write failing loader and validation tests**

```java
assertThat(inventory.inputs().stream()
        .filter(input -> input.name().equals("plant"))
        .findFirst().orElseThrow().pattern())
        .isEqualTo("^[A-Z0-9]{4}$");

CapabilityResponse response = service.validate(
        "MM.Inventory.GetAvailability",
        Map.of("material", "1000", "plant", "工厂"));
assertThat(response.success()).isFalse();
assertThat(response.errorType()).isEqualTo(ErrorType.INVALID_PARAMETER);
```

Also reject an invalid Registry regex at load/validation time rather than during a request.

- [ ] **Step 2: Verify RED**

Run: `cd services/gateway && ./gradlew :core:test --tests '*CapabilityRegistryLoaderTest' --tests '*CapabilityValidationServiceTest'`

Expected: FAIL because `InputField` has no `pattern` and `plant="工厂"` currently passes length validation.

- [ ] **Step 3: Add the minimal Registry contract**

Add `pattern: ^[A-Z0-9]{4}$` only to `sapnexus:Plant` inputs on the in-scope READ capabilities in `registry/capabilities.yaml`. Do not change the `MM.PR.CreateDraft` WRITE definition in this change. Extend `InputField` and the loader with nullable `pattern`, then validate syntax at Registry load time.

Do not add an automatic material/plant swap and do not infer that an SAP `BUSINESS_ERROR` proves the user's intended slot role.

- [ ] **Step 4: Enforce full-string matching in Gateway validation**

```java
if (input.pattern() != null && !Pattern.matches(input.pattern(), text)) {
    return false;
}
```

Keep required, type, minimum, and maximum checks unchanged. Return only the existing redacted `Invalid parameter: <name>` message.

- [ ] **Step 5: Verify GREEN and Registry contracts**

Run: `cd services/gateway && ./gradlew :core:test :app:test`

Expected: PASS; `5100` and `1000` are valid plants, `工厂` is rejected before execution, and existing capabilities still load.

Run: `openspec list --json`

Expected: exit 0 and authoritative totals reported.

Run: `openspec validate --all --strict`

Expected: exit 0; no strict Registry/spec errors.

- [ ] **Step 6: Conditional commit**

Only after explicit user authorization:

```bash
git add registry/capabilities.yaml services/gateway/core/src/main/java/com/sapnexus/gateway/registry/CapabilityDefinition.java services/gateway/core/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryLoader.java services/gateway/core/src/main/java/com/sapnexus/gateway/registry/CapabilityRegistryValidator.java services/gateway/core/src/main/java/com/sapnexus/gateway/validation/CapabilityValidationService.java services/gateway/core/src/test/java/com/sapnexus/gateway/registry/CapabilityRegistryLoaderTest.java services/gateway/core/src/test/java/com/sapnexus/gateway/validation/CapabilityValidationServiceTest.java
git diff --cached --check
git commit -m "feat: validate registry parameter patterns"
```

---

### Task 6: Durable Session v2, conversation lease, CAS, and turn idempotency

**Files:**
- Modify: `frontend/src/runtime/durable/types.ts`
- Modify: `frontend/src/runtime/durable/jsonl-conversation-store.ts`
- Modify: `frontend/src/runtime/durable/jsonl-conversation-store.test.ts`
- Create: `frontend/src/runtime/durable/conversation-protocol.test.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`

**Interfaces:**
- Consumes: `conversationId`, trusted `principalId`, client/server-generated `turnId`, `SessionStateV2`, worker id, lease TTL.
- Produces: `claim`, `compareAndSwap`, `release`, and duplicate-turn lookup; state is persisted before READ execution becomes eligible.

- [ ] **Step 1: Write failing store contract tests**

```ts
expect(await store.claim("c1", "worker-a", 60_000)).toEqual({ status: "claimed" });
expect(await store.claim("c1", "worker-b", 60_000)).toMatchObject({ status: "rejected" });

const saved = await store.compareAndSwap("c1", 2, { ...next, stateVersion: 3 });
expect(saved).toEqual({ status: "saved", stateVersion: 3 });
expect(await store.compareAndSwap("c1", 2, stale)).toEqual({
  status: "conflict",
  actualVersion: 3,
});
```

Cover cross-restart load, principal mismatch, lease expiry, release ownership, duplicate `turnId`, malformed Session preservation, and atomic rename.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix frontend test -- src/runtime/durable/jsonl-conversation-store.test.ts src/runtime/durable/conversation-protocol.test.ts`

Expected: FAIL because `DurableConversationStore` lacks lease/CAS/idempotency operations.

- [ ] **Step 3: Add versioned TypeScript mirrors**

```ts
export type SessionStateV2 = {
  schemaVersion: 2;
  stateVersion: number;
  principalId: string;
  activeFrame: ReadContextFrame | null;
  recentFrames: ReadContextFrame[];
  pendingInteraction: PendingInteraction | null;
  history: Turn[];
  lastAppliedTurnId: string | null;
  lastRunId: string | null;
};

export interface DurableConversationStore {
  load(conversationId: string, principalId: string): Promise<SessionStateV2 | null>;
  claim(conversationId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome>;
  compareAndSwap(
    conversationId: string,
    expectedVersion: number,
    next: SessionStateV2,
  ): Promise<ConversationCasOutcome>;
  release(conversationId: string, workerId: string): Promise<void>;
}
```

Keep lease metadata separate from the semantic Session payload. Use a per-conversation in-process mutex plus lease file for the local/single-worker baseline. Future shared-store selection remains deferred.

- [ ] **Step 4: Implement migration-safe load and atomic CAS**

Legacy files load through a pure converter, with copied frames marked stale. Preserve a malformed source file and return a typed `CONTEXT_DESERIALIZATION_FAILED` outcome; do not overwrite it with an empty Session.

- [ ] **Step 5: Add runtime protocol tests before wiring**

Assert sequence: claim -> load -> runner/reducer -> CAS -> Gateway eligibility -> event append -> release. Lease rejection returns `CONVERSATION_BUSY`; CAS conflict returns `CONTEXT_VERSION_CONFLICT`; both have zero fake Gateway calls. A completed duplicate `turnId` returns the prior run result and makes zero additional Gateway calls.

- [ ] **Step 6: Implement the protocol around the existing adapter**

Add `turnId` to `CreateAgentRunInput`; generate it server-side only when absent. Keep run lease and conversation lease separate. Release the conversation lease in `finally`. Do not allow Session state to replay a crashed SAP READ.

- [ ] **Step 7: Verify GREEN**

Run: `npm --prefix frontend test -- src/runtime/durable/jsonl-conversation-store.test.ts src/runtime/durable/conversation-protocol.test.ts src/runtime/agent-runtime-adapter.test.ts`

Expected: PASS; concurrent or repeated turns do not overwrite state or duplicate Gateway calls.

- [ ] **Step 8: Conditional commit**

Only after explicit user authorization:

```bash
git add frontend/src/runtime/durable/types.ts frontend/src/runtime/durable/jsonl-conversation-store.ts frontend/src/runtime/durable/jsonl-conversation-store.test.ts frontend/src/runtime/durable/conversation-protocol.test.ts frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts
git diff --cached --check
git commit -m "feat: govern durable conversation updates"
```

---

### Task 7: Make Frame v2 authoritative for READ and unify pending interactions

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Modify: `agent/sap_nexus_agent/capability_selector.py`
- Modify: `agent/sap_nexus_agent/conversation_context.py`
- Modify: `agent/sap_nexus_agent/cli.py`
- Modify: `agent/sap_nexus_agent/workbench_output.py`
- Modify: `agent/tests/test_orchestrator.py`
- Modify: `agent/tests/test_cli_context.py`
- Modify: `agent/tests/test_workbench_output.py`
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`
- Modify: `frontend/src/runtime/durable/types.ts`

**Interfaces:**
- Consumes: authoritative `SessionStateV2` representation of `ConversationSessionV2`, reducer resolution, visible READ capability set, current Registry snapshot.
- Produces: one version-bound `PendingInteraction` model and READ CallPlans created only from `READY` frames; WRITE paths remain on existing governance.

- [ ] **Step 1: Add the authoritative real-failure integration test**

Run the exact four turns through `run_query` and a counting fake Gateway. Required counts:

```text
Turn 1: SELECT, Gateway execute count = 1
Turn 2: CLARIFY, cumulative execute count = 1
Turn 3: CLARIFY, cumulative execute count = 1
Turn 4: SELECT, cumulative execute count = 2
Turn 4 parameters: material=DEMOA2, plant=1000
```

The Turn 3 bad model payload must be the recorded `{material: 1000, plant: 工厂}` rather than an ideal mock.

- [ ] **Step 2: Verify RED against shadow mode**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -k 'governed_read_context_authoritative' -q`

Expected: FAIL because legacy selection is still authoritative.

- [ ] **Step 3: Switch only READ decisions to Frame v2**

Set the server-owned default to `v2` for READ. Route `IntentEnvelope` and deterministic candidates through Reducer and decision gate before `create_call_plan()`. Reject any attempt to construct a READ CallPlan directly from model parameters or a non-READY frame.

Keep WRITE capabilities on the existing selector/approval path. Add a negative test proving a READ frame with WRITE-shaped values cannot create or restore an `ApprovalRecord`.

- [ ] **Step 4: Split contextual READ into resolve and execute phases**

The current CLI invokes Gateway inside `run_query()` before TypeScript can save the next Session. Add an explicit server-internal two-phase interface; do not simulate persist-before-execute by saving after the existing call returns.

```python
def resolve_read_turn(
    text: str,
    *,
    context: ConversationContext,
    intent_adapter: IntentAdapter,
    principal: TrustedPrincipal,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
    turn_id: str,
) -> AgentOutcome:
    """Return decision, next state, and optional CallPlan without Gateway IO."""

def continue_resolved_read(
    call_plan: CallPlan,
    binding: ReadExecutionBinding,
    gateway: GatewayClientProtocol,
) -> AgentOutcome:
    """Execute one server-owned, CAS-bound READY READ plan."""
```

Add CLI modes `--resolve-read-turn` and `--continue-read`. Move `GatewayClient` construction below argument routing so `--resolve-read-turn` cannot instantiate or call it. The resolution output must include `turnId`, `frameId`, expected next `stateVersion`, snapshot id, `ConversationReadState`, resolution report, decision, and optional CallPlan.

The TypeScript adapter sequence is fixed:

```text
claim conversation
-> load SessionStateV2
-> invoke --resolve-read-turn (zero Gateway IO)
-> compareAndSwap next SessionStateV2
-> if non-SELECT, emit response and stop
-> if SELECT, invoke --continue-read with the server-owned binding
-> append RunEvidence/result
-> release conversation
```

`--continue-read` must re-check `turnId + frameId + stateVersion + registrySnapshotId + principalId`, accept only a READ CallPlan, and never rerun the model or Reducer. Its payload is created inside the server runtime and is not accepted from a browser request. A binding mismatch returns a typed failure with zero Gateway calls.

- [ ] **Step 5: Replace READ pending variants with one bound type**

Map `CLARIFY`, `SHOW_OPTIONS`, batch confirmation, and planner confirmation to `PendingInteraction`, always bound to `frameId + stateVersion + registrySnapshotId`. An expired or mismatched pending item is discarded and re-clarified. Do not map approval decisions into this type.

- [ ] **Step 6: Persist state before Gateway eligibility**

The adapter must CAS the reducer result first. Only after successful CAS may a `SELECT` decision invoke `--continue-read`. `CLARIFY`, `SHOW_OPTIONS`, `ESCALATE_TO_PLANNER`, store failure, lease failure, CAS failure, and execution-binding mismatch must return without Gateway validation or execution.

- [ ] **Step 7: Verify authoritative behavior**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py -q`

Expected: PASS; the exact regression sequence asks for clarification and never sends `{material: 1000, plant: 工厂}` to Gateway.

Run: `npm --prefix frontend test -- src/runtime/agent-runtime-adapter.test.ts src/runtime/durable`

Expected: PASS; persisted Frame v2 and pending bindings survive restart, CAS precedes `--continue-read`, and CAS/turn conflicts cause zero continuation/Gateway calls.

Run: `scripts/verify-agent-callplan-evidence.sh`

Expected: PASS; only READY READ frames produce CallPlans.

- [ ] **Step 8: Conditional commit**

Only after explicit user authorization:

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/sap_nexus_agent/capability_selector.py agent/sap_nexus_agent/conversation_context.py agent/sap_nexus_agent/cli.py agent/sap_nexus_agent/workbench_output.py agent/tests/test_orchestrator.py agent/tests/test_cli_context.py agent/tests/test_workbench_output.py frontend/src/runtime/agent-runtime-adapter.ts frontend/src/runtime/agent-runtime-adapter.test.ts frontend/src/runtime/durable/types.ts
git diff --cached --check
git commit -m "feat: make governed read context authoritative"
```

---

### Task 8: Multi-turn Eval fixtures, recorded bad payload, and release hard gates

**Files:**
- Modify: `evals/matcher_cases.yaml`
- Modify: `evals/recorded_llm/end_to_end_agent_release.json`
- Modify: `evals/end_to_end_agent_release_cases.json`
- Modify: `agent/sap_nexus_agent/eval.py`
- Modify: `agent/tests/test_eval_runner.py`
- Modify: `frontend/src/runtime/release-gate/types.ts`
- Modify: `frontend/src/runtime/release-gate/evaluator.ts`
- Modify: `frontend/src/runtime/release-gate/evaluator.test.ts`
- Modify: `frontend/src/runtime/release-gate/scenario-runner.ts`
- Modify: `frontend/src/runtime/release-gate/scenario-runner.test.ts`

**Interfaces:**
- Consumes: versioned multi-turn deterministic fixtures, redacted recorded LLM responses, Gateway call counts, context transition evidence.
- Produces: per-case context metrics and non-compensable hard-gate results in the existing release report.

- [ ] **Step 1: Add failing fixture-contract tests**

Require every multi-turn case to declare ordered turns, initial context, expected frame status/slots/decision per turn, expected validate/execute deltas, snapshot id, and fixture version. Recorded LLM metadata must include provider, model, prompt/schema version, recorded time, and redaction marker.

- [ ] **Step 2: Add the minimum complete fixture set**

Include direct plant switch, clear-then-ambiguous reference, explicit correction, LLM unavailable, malformed JSON, technical override injection, capability switch, recent-frame explicit restoration, Registry drift, principal mismatch, concurrent turns, duplicate `turnId`, and READ-to-WRITE authority isolation.

The bad recording must contain exactly:

```json
{
  "capabilityId": "MM.Inventory.GetAvailability",
  "parameters": {
    "material": "1000",
    "plant": "工厂"
  }
}
```

- [ ] **Step 3: Verify RED**

Run: `.venv/bin/python -m pytest agent/tests/test_eval_runner.py -q`

Expected: FAIL because the Eval runner does not yet execute ordered context transitions or enforce per-turn Gateway deltas.

- [ ] **Step 4: Extend the Eval runner minimally**

Add a multi-turn runner that reuses the production reducer/orchestrator and fake Gateway. Do not implement a separate Eval-only merge policy. Fail a case on any false `SELECT`, wrong slot role, unexpected Gateway call, state overwrite, or WRITE authority creation.

- [ ] **Step 5: Add release-gate metrics and non-compensable gates**

```ts
export type ReadContextMetricCounts = {
  contextConflictCases: number;
  falseSelects: number;
  nonReadyFrames: number;
  nonReadyGatewayCalls: number;
  callPlanSlotChecks: number;
  wrongCallPlanSlotRoles: number;
  duplicateTurnChecks: number;
  duplicateTurnGatewayCalls: number;
  casLeaseConflictChecks: number;
  stateOverwritesAfterConflict: number;
  staleFrameChecks: number;
  staleFrameExecutions: number;
  readWriteIsolationChecks: number;
  readContextWriteAuthorityCreations: number;
};
```

All corresponding rates/counts require zero. Add deterministic-core pass rate and successful-recovery rate gates requiring `1`. Missing/skipped/stale evidence fails the affected level and cannot be offset by unrelated passing cases.

- [ ] **Step 6: Verify GREEN**

Run: `.venv/bin/python -m pytest agent/tests/test_eval_runner.py -q`

Expected: PASS; the recorded bad payload produces `CLARIFY`, null CallPlan, and zero Gateway calls.

Run: `npm --prefix frontend test -- src/runtime/release-gate/evaluator.test.ts src/runtime/release-gate/scenario-runner.test.ts`

Expected: PASS; one injected false `SELECT` or non-READY Gateway call makes the target profile fail.

Run: `npm --prefix frontend run release-gate -- --profile all`

Expected: exit 0 only when every original and new hard gate passes; `liveSmoke.status` remains `not_run`.

- [ ] **Step 7: Conditional commit**

Only after explicit user authorization:

```bash
git add evals/matcher_cases.yaml evals/recorded_llm/end_to_end_agent_release.json evals/end_to_end_agent_release_cases.json agent/sap_nexus_agent/eval.py agent/tests/test_eval_runner.py frontend/src/runtime/release-gate/types.ts frontend/src/runtime/release-gate/evaluator.ts frontend/src/runtime/release-gate/evaluator.test.ts frontend/src/runtime/release-gate/scenario-runner.ts frontend/src/runtime/release-gate/scenario-runner.test.ts
git diff --cached --check
git commit -m "test: gate governed read context regressions"
```

---

### Task 9: Remove the legacy bridge only after hard gates, then verify and archive

**Files:**
- Modify: `agent/sap_nexus_agent/conversation_context.py`
- Modify: `agent/sap_nexus_agent/llm_intent.py`
- Modify: `agent/sap_nexus_agent/intent.py`
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Modify: `agent/tests/test_intent.py`
- Modify: `agent/tests/test_llm_intent.py`
- Modify: `agent/tests/test_cli_context.py`
- Modify: `agent/tests/test_orchestrator.py`
- Modify: `agent/tests/test_workbench_output.py`
- Modify: `frontend/src/runtime/durable/types.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `docs/superpowers/specs/2026-08-06-governed-read-context-design.md`
- Create: `docs/superpowers/reports/2026-08-06-governed-read-context-verify.md`
- Modify: `docs/comet/changes/sap-nexus-governed-read-context/verification.md` only through Comet evidence commands; never hand-edit `.comet.yaml`, `comet-state.yaml`, or archive state.

**Interfaces:**
- Consumes: passing shadow classification, migrated callers, full hard-gate report, current Native acceptance IDs.
- Produces: one authoritative Frame v2 path, verification report, current Native evidence, and archived change artifacts.

- [ ] **Step 1: Prove removal prerequisites before deleting compatibility code**

Run all Task 8 gates and search for callers:

```bash
rg -n "LastContext|resolve_with_context|pending_show_options|pending_escalate|lastContext" agent frontend evals
```

Expected: every remaining hit is either a migration reader, historical fixture, or explicitly listed removal target. If any active caller still depends on legacy merge behavior, stop this task and migrate that caller first.

- [ ] **Step 2: Write failure tests for accidental legacy use**

Add contract assertions that production READ orchestration cannot call `resolve_with_context`, cannot serialize a new schema-v1 Session, and cannot accept request/model selection of `READ_CONTEXT_MODE=legacy`.

```python
def test_v2_contextual_read_does_not_call_legacy_merge(monkeypatch):
    monkeypatch.setattr(
        llm_intent,
        "resolve_with_context",
        lambda *_args, **_kwargs: pytest.fail("legacy merge was called"),
    )
    outcome = run_governed_context_turn(valid_ready_continuation())
    assert outcome.match_decision.decision_type == "SELECT"
```

- [ ] **Step 3: Verify RED**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_intent.py agent/tests/test_llm_intent.py -k 'legacy or v2_contextual_read' -q`

Expected: FAIL because the current production continuation still exposes or invokes the legacy merge path.

- [ ] **Step 4: Remove only the proven-dead bridge**

Delete destructive merge behavior and production writes of `LastContext`. Retain a narrow read-only schema-v1 migration decoder; it must always output a stale Frame. Decoder deletion is explicitly outside this change and requires a separately reviewed retention/telemetry decision.

- [ ] **Step 5: Run focused and project verification**

Run: `.venv/bin/python -m pytest agent/tests`

Expected: PASS.

Run: `scripts/verify-agent-callplan-evidence.sh`

Expected: PASS.

Run: `npm --prefix frontend run verify`

Expected: PASS.

Run: `cd services/gateway && ./gradlew :core:test :app:test`

Expected: PASS.

Run: `openspec list --json`

Expected: exit 0 and authoritative totals reported.

Run: `openspec validate --all --strict`

Expected: exit 0.

Run: `git diff --check`

Expected: exit 0 with no whitespace errors.

- [ ] **Step 6: Write the verification report from actual evidence**

Record commands, exit codes, test totals, Registry snapshot, fixture versions, hard-gate values, shadow-diff disposition, and `liveSmoke.status=not_run`. State explicitly that this proves governed READ context behavior, not live SAP correctness and not any SAP WRITE authorization.

Update the design status only after all checks pass; preserve the original problem statement and approved decisions. Do not update roadmap/runbook completion claims unless this change is also the declared workstream archive.

- [ ] **Step 7: Record Native evidence and archive through the workflow**

Use the exact evidence and next-step commands printed by the active Native change. Re-run any command whose evidence is stale for the current snapshot. Let the configured automatic archive mode perform the archive; inspect archived artifacts and global status afterward.

- [ ] **Step 8: Conditional final commit**

Only after explicit user authorization and successful Native archive:

```bash
git add agent/sap_nexus_agent/conversation_context.py agent/sap_nexus_agent/llm_intent.py agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/orchestrator.py agent/tests/test_intent.py agent/tests/test_llm_intent.py agent/tests/test_cli_context.py agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py frontend/src/runtime/durable/types.ts frontend/src/runtime/agent-runtime-adapter.ts docs/superpowers/specs/2026-08-06-governed-read-context-design.md docs/superpowers/reports/2026-08-06-governed-read-context-verify.md docs/comet/changes/sap-nexus-governed-read-context/verification.md
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: govern multi-turn read context"
```

## Acceptance Traceability

| Approved requirement | Primary task | Required evidence |
|---|---:|---|
| Typed Frame, Slot, Pending state | 1 | Python round-trip and invariant tests |
| LLM is advisory only | 2 | bad/malformed/model-only candidate tests |
| Deterministic evidence arbitration | 3 | reducer fixtures and replay equality |
| Exact three-turn failure is blocked | 3, 7, 8 | non-READY state and zero Gateway deltas |
| Non-READY means zero Gateway calls | 4, 6, 7, 8 | counting fake Gateway and release gate |
| `plant="工厂"` rejected before SAP | 2, 5 | Python semantic discard and Java `INVALID_PARAMETER` |
| Visibility and snapshot remain trusted | 4, 7, 8 | visibility/snapshot negative tests |
| Durable lease, CAS, turn idempotency | 6 | concurrent/restart/duplicate-turn tests |
| Persist before execute | 6, 7 | ordered protocol test and CAS-failure zero-call test |
| Unified READ pending state | 7 | binding/expiry/version mismatch tests |
| READ cannot create WRITE authority | 7, 8 | negative approval isolation tests and hard gate |
| Shadow then authoritative migration | 4, 7 | shadow diff plus authoritative E2E |
| Legacy migration never executes directly | 1, 6, 9 | stale conversion and no schema-v1 write tests |
| Hard gates are non-compensable | 8 | release evaluator failure injection tests |
| Live verification is separately authorized | 8, 9 | release/report `liveSmoke.status=not_run` |

## Definition of Done

- The exact user-reported sequence never calls Gateway on Turns 2 or 3 and recovers to the correct `{material: DEMOA2, plant: 1000}` only after explicit clarification.
- `false SELECT`, non-READY Gateway calls, wrong slot roles, visibility leaks, duplicate-turn Gateway calls, state overwrite after lease/CAS conflict, stale-frame execution, and READ-created WRITE authority are all zero in deterministic and recorded fixtures.
- All changed Python, TypeScript, Java, Registry/OpenSpec, and CallPlan checks pass with current Native evidence.
- Live LLM/SAP smoke remains `not_run` unless the user separately authorizes it.
- No implementation or documentation claim exceeds the verified offline/fake/recorded evidence.
- No commit, push, or SAP WRITE occurs without explicit authorization.

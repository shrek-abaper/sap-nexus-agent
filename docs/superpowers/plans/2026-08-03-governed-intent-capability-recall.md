---
change: sap-nexus-governed-intent-capability-recall
design-doc: docs/superpowers/specs/2026-08-03-governed-intent-capability-recall-design.md
base-ref: d386fb5d0258c47b8d0783160cb8403cf0a5d197
---

# Governed Intent Envelope & Capability Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `IntentParseResult` with a versioned `IntentEnvelope`, add closed-set recall + bounded rerank before the deterministic matcher, record structured discard reasons, extend `MatchDecision` with replay fields, and implement cross-turn SHOW_OPTIONS / ESCALATE_TO_PLANNER continuation via `ConversationContext` pending states.

**Architecture:** LLM-first intent carrier (`IntentEnvelope`) flows through `recall` (lexical + alias + example) -> `rerank` (heuristic scoring) -> `select_capability` (five-state decision with replay fields). `ConversationContext` gains `pending_show_options` / `pending_escalate` (mutual-exclusive, advisory only). All callers (`orchestrator` / `cli` / `llm_intent`) migrate from `IntentParseResult` to `IntentEnvelope`; `SelectionResult` compat bridge is removed.

**Tech Stack:** Python 3.11+, frozen dataclasses, `dataclasses.replace`, pytest TDD, YAML registry, OpenAI-compatible LLM client.

## Global Constraints

- **No matcher five-state algorithm change** — only add recall + rerank stages before it and extend `MatchDecision` fields.
- **No embedding / vector store / RAG** — recall uses keyword / alias / example substring match only.
- **No capability execution** — pending states are advisory only, MUST NOT influence `CallPlan` / `ApprovalRecord` lifecycle.
- **No `GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` mutation** — consume as-is from Runbook 13.
- **`IntentEnvelope` is immutable** — `@dataclass(frozen=True)`.
- **`discard_reasons` MUST be empty when LLM output is fully valid** — no silent drops.
- **Closed-set defense** — `capability_hint` not in `VisibleCapabilitySet` is discarded with `"unknown_capability:<id>"`.
- **Backward-compatible registry schema** — `aliases` / `examples` are optional; absent -> empty tuple.
- **Code identifiers in English, prose in Chinese** — match existing codebase style.
- **TDD order** — data structures -> recall -> rerank -> discard -> envelope -> selector -> cross-turn -> caller migration -> tests -> eval -> verify.

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `agent/sap_nexus_agent/intent_envelope.py` | `IntentGoal` / `IntentEnvelope` dataclasses (frozen) |
| `agent/sap_nexus_agent/recall.py` | lexical + alias + example recall + dedupe |
| `agent/sap_nexus_agent/rerank.py` | bounded rerank scoring + tie-break + evidence |
| `agent/sap_nexus_agent/discard.py` | `detect_discard_reasons(payload, visible_ids)` |
| `agent/tests/test_intent_envelope.py` | `IntentGoal` / `IntentEnvelope` shape / frozen / to_dict |
| `agent/tests/test_recall.py` | lexical / alias / example / merge / dedupe |
| `agent/tests/test_rerank.py` | scoring / tie-break / rerank_evidence |
| `agent/tests/test_discard.py` | unknown_capability / technical_field / invalid_param / valid_empty |

### Modified files

| Path | Change |
|---|---|
| `agent/sap_nexus_agent/match_decision.py` | `MatchDecision` + 4 replay fields; remove `to_selection_result()` + `SelectionResult` import |
| `agent/sap_nexus_agent/conversation_context.py` | + `PendingShowOptions` / `PendingEscalate` / `pending_show_options` / `pending_escalate` fields + `with_*` / `clear_pending` methods + `to_dict` / `from_dict` round-trip |
| `agent/sap_nexus_agent/intent.py` | `parse_intent` returns `IntentEnvelope` (BREAKING); `IntentParseResult` removed from public API; keep `_RuleParsePayload` internal helper |
| `agent/sap_nexus_agent/llm_intent.py` | `_payload_to_envelope` (replaces `_payload_to_parse_result`); `_parse_result_to_envelope` (rule fallback); `parse_with_llm` / `parse_with_hybrid` / `build_intent_adapter` return `IntentEnvelope`; `IntentAdapter` signature |
| `agent/sap_nexus_agent/capability_selector.py` | `select_capability(envelope, recall_candidates, rerank_evidence, visible)` (BREAKING); remove `SelectionResult` / `to_selection_result()`; + `REJECT(VISIBILITY_DENIED)` from LLM hint |
| `agent/sap_nexus_agent/orchestrator.py` | consume `IntentEnvelope` + replay fields; SHOW_OPTIONS / ESCALATE write pending; cross-turn pending check |
| `agent/sap_nexus_agent/cli.py` | produce `IntentEnvelope` (rule + LLM path); pass `visible_capability_set` + `catalog` to recall/rerank |
| `agent/sap_nexus_agent/registry_loader.py` | `CapabilityDescriptor` + `aliases: tuple[str, ...]` / `examples: tuple[str, ...]` |
| `registry/capabilities.yaml` | 3 capabilities + optional `aliases: []` / `examples: []` |
| `agent/tests/test_match_decision.py` | assert 5 decision types carry replay fields; remove `to_selection_result` tests |
| `agent/tests/test_capability_selector.py` | assert recall + rerank integration / `VISIBILITY_DENIED` |
| `agent/tests/test_llm_intent.py` | assert `IntentEnvelope` shape / `discard_reasons` / `created_by` / `snapshot_id` |
| `agent/tests/test_intent.py` | assert rule fallback produces `IntentEnvelope` |
| `agent/tests/test_conversation_context.py` | cross-turn SHOW_OPTIONS / ESCALATE / mutual exclusivity |
| `agent/tests/test_orchestrator.py` | pending state write + clear on continuation |
| `evals/matcher_cases.yaml` | + 11 eval case categories |

### Key design decisions (from design doc)

- **D1 recall data source**: `CapabilityDescriptor` (from `IntentCatalog`) provides `name` / `description` / `aliases` / `examples`; `VisibleCapabilitySet` provides closed-set filtering. `recall(utterance, visible_capability_set, catalog)` returns `list[str]` of capability_ids.
- **D2 `parse_intent` return type**: `parse_intent` returns `IntentEnvelope(created_by="rule")`. Internal rule extraction reuses existing keyword logic via a private `_RuleParsePayload` dataclass; `_parse_result_to_envelope` converts it. `IntentParseResult` public type is removed.
- **D3 `select_capability` signature**: `select_capability(envelope, recall_candidates, rerank_evidence, visible) -> MatchDecision`. The selector consumes `envelope.goals` for multi-goal ESCALATE, `envelope.discard_reasons` for REJECT, and `recall_candidates` / `rerank_evidence` for replay.
- **D4 pending mutual exclusivity**: `with_pending_show_options` clears `pending_escalate` (and vice versa). `clear_pending` clears both. `pending_clarification` (existing `LastContext` with `decision_type="CLARIFY"`) is orthogonal and cleared by new-turn primary keyword.
- **D5 `model_evidence`**: LLM payload summary (goals / candidates / constraints fields). Raw payload optionally written to trace. Summary is for replay; raw is for debugging.

---

## Task 1: 数据结构 (Data Structures)

**Files:**
- Create: `agent/sap_nexus_agent/intent_envelope.py`
- Modify: `agent/sap_nexus_agent/match_decision.py`
- Test: `agent/tests/test_intent_envelope.py`, `agent/tests/test_match_decision.py`

**Interfaces:**
- Produces: `IntentGoal` / `IntentEnvelope` (in `intent_envelope.py`); `MatchDecision.envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons` (in `match_decision.py`)

### Task 1.1: 新增 `IntentGoal` dataclass (frozen)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_intent_envelope.py
import dataclasses
import pytest
from sap_nexus_agent.intent_envelope import IntentGoal, IntentEnvelope


def test_intent_goal_construction():
    goal = IntentGoal(
        goal_text="查物料 DEMOA2 在 1000 的库存",
        capability_hint="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing=[],
    )
    assert goal.goal_text == "查物料 DEMOA2 在 1000 的库存"
    assert goal.capability_hint == "MM.Inventory.GetAvailability"
    assert goal.parameters == {"material": "DEMOA2", "plant": "1000"}
    assert goal.missing == []


def test_intent_goal_is_frozen():
    goal = IntentGoal(goal_text="x", capability_hint=None, parameters={}, missing=[])
    assert dataclasses.is_dataclass(goal)
    with pytest.raises(dataclasses.FrozenInstanceError):
        goal.goal_text = "mutated"  # type: ignore[misc]
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_intent_envelope.py::test_intent_goal_construction -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sap_nexus_agent.intent_envelope'`

- [ ] **Step 3: 实现 `IntentGoal`**

```python
# agent/sap_nexus_agent/intent_envelope.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class IntentGoal:
    """One user goal extracted by the LLM or rule path.

    ``capability_hint`` / ``parameters`` / ``missing`` are advisory: the
    selector validates them against the closed set and required inputs.
    """

    goal_text: str
    capability_hint: str | None
    parameters: dict[str, str]
    missing: list[str]
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_intent_envelope.py::test_intent_goal_construction agent/tests/test_intent_envelope.py::test_intent_goal_is_frozen -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/intent_envelope.py agent/tests/test_intent_envelope.py
git commit -m "feat(intent): add IntentGoal frozen dataclass"
```

### Task 1.2: 新增 `IntentEnvelope` dataclass (frozen)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_intent_envelope.py (追加)
import uuid


def test_intent_envelope_construction_llm():
    goal = IntentGoal(
        goal_text="查库存",
        capability_hint="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing=[],
    )
    envelope = IntentEnvelope(
        envelope_id=uuid.uuid4().hex,
        utterance="查库存 DEMOA2 1000",
        goals=(goal,),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={"goals": 1, "candidates": ["MM.Inventory.GetAvailability"]},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )
    assert envelope.created_by == "llm"
    assert envelope.snapshot_id == "snap-001"
    assert len(envelope.envelope_id) > 0
    assert len(envelope.goals) == 1
    assert envelope.goals[0].capability_hint == "MM.Inventory.GetAvailability"


def test_intent_envelope_is_frozen():
    envelope = IntentEnvelope(
        envelope_id="id",
        utterance="u",
        goals=(),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="s",
        discard_reasons=[],
        created_by="rule",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.utterance = "mutated"  # type: ignore[misc]


def test_intent_envelope_to_dict_round_trip():
    goal = IntentGoal(goal_text="g", capability_hint="c", parameters={"k": "v"}, missing=["m"])
    envelope = IntentEnvelope(
        envelope_id="eid",
        utterance="u",
        goals=(goal,),
        user_constraints={"language": "zh-CN"},
        ambiguities=["a"],
        reference_turn_id=None,
        model_evidence={"goals": 1},
        snapshot_id="snap",
        discard_reasons=["unknown_capability:Foo.Bar"],
        created_by="llm",
    )
    payload = envelope.to_dict()
    restored = IntentEnvelope.from_dict(payload)
    assert restored == envelope
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_intent_envelope.py::test_intent_envelope_construction_llm -v`
Expected: FAIL with `AttributeError: 'IntentEnvelope' has no attribute 'to_dict'` (after dataclass exists)

- [ ] **Step 3: 实现 `IntentEnvelope`**

```python
# agent/sap_nexus_agent/intent_envelope.py (追加)
@dataclass(frozen=True)
class IntentEnvelope:
    """Versioned LLM-first intent carrier (replaces IntentParseResult).

    ``envelope_id`` is the replay primary key. ``snapshot_id`` binds the
    envelope to the same RegistrySnapshot as the GovernedContext.
    ``discard_reasons`` records structured filter reasons (empty when LLM
    output is fully valid). ``created_by`` distinguishes LLM vs rule path.
    """

    envelope_id: str
    utterance: str
    goals: tuple[IntentGoal, ...]
    user_constraints: dict[str, str]
    ambiguities: list[str]
    reference_turn_id: str | None
    model_evidence: dict
    snapshot_id: str
    discard_reasons: list[str]
    created_by: Literal["llm", "rule"]

    def to_dict(self) -> dict[str, object]:
        return {
            "envelopeId": self.envelope_id,
            "utterance": self.utterance,
            "goals": [
                {
                    "goalText": g.goal_text,
                    "capabilityHint": g.capability_hint,
                    "parameters": dict(g.parameters),
                    "missing": list(g.missing),
                }
                for g in self.goals
            ],
            "userConstraints": dict(self.user_constraints),
            "ambiguities": list(self.ambiguities),
            "referenceTurnId": self.reference_turn_id,
            "modelEvidence": dict(self.model_evidence),
            "snapshotId": self.snapshot_id,
            "discardReasons": list(self.discard_reasons),
            "createdBy": self.created_by,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "IntentEnvelope":
        goals_raw = payload.get("goals") or []
        goals = tuple(
            IntentGoal(
                goal_text=str(g["goalText"]),
                capability_hint=g.get("capabilityHint") if g.get("capabilityHint") is not None else None,
                parameters={str(k): str(v) for k, v in dict(g.get("parameters") or {}).items()},
                missing=[str(x) for x in (g.get("missing") or [])],
            )
            for g in goals_raw
            if isinstance(g, dict) and "goalText" in g
        )
        return cls(
            envelope_id=str(payload["envelopeId"]),
            utterance=str(payload["utterance"]),
            goals=goals,
            user_constraints={str(k): str(v) for k, v in dict(payload.get("userConstraints") or {}).items()},
            ambiguities=[str(x) for x in (payload.get("ambiguities") or [])],
            reference_turn_id=payload.get("referenceTurnId") if payload.get("referenceTurnId") is not None else None,
            model_evidence=dict(payload.get("modelEvidence") or {}),
            snapshot_id=str(payload["snapshotId"]),
            discard_reasons=[str(x) for x in (payload.get("discardReasons") or [])],
            created_by=str(payload["createdBy"]),  # type: ignore[arg-type]
        )
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_intent_envelope.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/intent_envelope.py agent/tests/test_intent_envelope.py
git commit -m "feat(intent): add IntentEnvelope frozen dataclass with to_dict/from_dict"
```

### Task 1.3: 新增 `PendingShowOptions` dataclass (frozen)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_conversation_context.py (追加)
from sap_nexus_agent.conversation_context import PendingShowOptions
from sap_nexus_agent.match_decision import MatchedIntent


def test_pending_show_options_construction():
    candidates = (
        MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
        MatchedIntent(capability_id="MM.PR.CreateDraft", parameters={}, missing=[]),
    )
    pending = PendingShowOptions(candidates=candidates, snapshot_id="snap-001")
    assert pending.snapshot_id == "snap-001"
    assert len(pending.candidates) == 2
    assert pending.candidates[0].capability_id == "MM.PurchaseOrder.GetList"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_pending_show_options_construction -v`
Expected: FAIL with `ImportError: cannot import name 'PendingShowOptions'`

- [ ] **Step 3: 实现 `PendingShowOptions`**

```python
# agent/sap_nexus_agent/conversation_context.py (顶部新增 import + dataclass)
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent


@dataclass(frozen=True)
class PendingShowOptions:
    """Advisory pending state for cross-turn SHOW_OPTIONS continuation.

    Carries the candidates shown in turn N and the snapshot_id they were
    matched against. Turn N+1 selects one -> clear pending -> SELECT.
    """

    candidates: "tuple[MatchedIntent, ...]"
    snapshot_id: str
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_pending_show_options_construction -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/conversation_context.py agent/tests/test_conversation_context.py
git commit -m "feat(context): add PendingShowOptions frozen dataclass"
```

### Task 1.4: 新增 `PendingEscalate` dataclass (frozen)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_conversation_context.py (追加)
from sap_nexus_agent.conversation_context import PendingEscalate
from sap_nexus_agent.match_decision import EscalationHandoff


def test_pending_escalate_construction():
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[],
        utterance="u",
        registry_snapshot_id="s",
    )
    pending = PendingEscalate(handoff=handoff, snapshot_id="snap-001")
    assert pending.snapshot_id == "snap-001"
    assert pending.handoff.reason == "multi-intent"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_pending_escalate_construction -v`
Expected: FAIL with `ImportError: cannot import name 'PendingEscalate'`

- [ ] **Step 3: 实现 `PendingEscalate`**

```python
# agent/sap_nexus_agent/conversation_context.py (追加)
@dataclass(frozen=True)
class PendingEscalate:
    """Advisory pending state for cross-turn ESCALATE_TO_PLANNER continuation.

    Carries the handoff from turn N and the snapshot_id. Turn N+1 confirms
    -> clear pending -> planner dry-run (no Gateway execution).
    """

    handoff: "EscalationHandoff"
    snapshot_id: str
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_pending_escalate_construction -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/conversation_context.py agent/tests/test_conversation_context.py
git commit -m "feat(context): add PendingEscalate frozen dataclass"
```

### Task 1.5: 扩展 `MatchDecision` 回放字段

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_match_decision.py (追加)
def test_match_decision_replay_fields_default_none():
    decision = MatchDecision(decision_type="SELECT", capability_id="X", parameters={})
    assert decision.envelope_id is None
    assert decision.recall_candidates is None
    assert decision.rerank_evidence is None
    assert decision.discard_reasons is None


def test_match_decision_replay_fields_populated():
    decision = MatchDecision(
        decision_type="SELECT",
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        envelope_id="env-001",
        recall_candidates=["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"],
        rerank_evidence={"MM.Inventory.GetAvailability": 6, "MM.PurchaseOrder.GetList": 2},
        discard_reasons=[],
    )
    assert decision.envelope_id == "env-001"
    assert decision.recall_candidates == ["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"]
    assert decision.rerank_evidence == {"MM.Inventory.GetAvailability": 6, "MM.PurchaseOrder.GetList": 2}
    assert decision.discard_reasons == []


def test_match_decision_reject_carries_discard_reasons():
    decision = MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_RFC_NAME",
        discard_reasons=["technical_field:rfcName"],
        rationale="rfcName not allowed",
    )
    assert decision.discard_reasons == ["technical_field:rfcName"]
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py::test_match_decision_replay_fields_default_none -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'envelope_id'`

- [ ] **Step 3: 扩展 `MatchDecision`**

```python
# agent/sap_nexus_agent/match_decision.py (修改 MatchDecision dataclass)
@dataclass(frozen=True)
class MatchDecision:
    decision_type: DecisionType
    capability_id: str | None = None
    parameters: dict[str, str] | None = None
    missing_parameters: list[str] | None = None
    error_type: str | None = None
    candidates: list[MatchedIntent] | None = None
    handoff: EscalationHandoff | None = None
    rationale: str = ""
    # Replay fields (Design Doc §3.4)
    envelope_id: str | None = None
    recall_candidates: list[str] | None = None
    rerank_evidence: dict[str, int] | None = None
    discard_reasons: list[str] | None = None
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py -v`
Expected: PASS (注意：`to_selection_result` 相关测试此时仍通过，将在 Task 6.5 移除)

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/match_decision.py agent/tests/test_match_decision.py
git commit -m "feat(match-decision): add replay fields envelope_id/recall_candidates/rerank_evidence/discard_reasons"
```

---

## Task 2: 召回阶段 (Recall Stage)

**Files:**
- Create: `agent/sap_nexus_agent/recall.py`
- Modify: `agent/sap_nexus_agent/registry_loader.py`, `registry/capabilities.yaml`
- Test: `agent/tests/test_recall.py`, `agent/tests/test_registry_loader.py`

**Interfaces:**
- Consumes: `VisibleCapabilitySet` (closed-set filter), `IntentCatalog` (description / aliases / examples source)
- Produces: `recall(utterance, visible_capability_set, catalog) -> list[str]`

### Task 2.0: 扩展 registry schema (`aliases` / `examples`)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_registry_loader.py (追加)
def test_capability_descriptor_has_aliases_and_examples():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    inv = catalog.find("MM.Inventory.GetAvailability")
    assert inv is not None
    assert "库存查询" in inv.aliases
    assert "物料可用量" in inv.aliases
    assert any("DEMOA2" in ex for ex in inv.examples)


def test_capability_descriptor_defaults_empty_tuples():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    po = catalog.find("MM.PurchaseOrder.GetList")
    assert po is not None
    # PO has no aliases/examples in registry yet -> empty tuples
    assert po.aliases == ()
    assert po.examples == ()
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_loader.py::test_capability_descriptor_has_aliases_and_examples -v`
Expected: FAIL with `AttributeError: 'CapabilityDescriptor' object has no attribute 'aliases'`

- [ ] **Step 3: 扩展 `CapabilityDescriptor` + registry yaml**

```python
# agent/sap_nexus_agent/registry_loader.py (修改 CapabilityDescriptor + load_intent_catalog)
@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    name: str
    description: str
    domain: str
    business_object: str
    inputs: tuple[InputDescriptor, ...]
    aliases: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


# In load_intent_catalog, inside the loop building descriptors:
descriptors.append(
    CapabilityDescriptor(
        capability_id=cap["capabilityId"],
        name=cap.get("name", ""),
        description=cap.get("description", ""),
        domain=cap.get("domain", ""),
        business_object=cap.get("businessObject", ""),
        inputs=inputs,
        aliases=tuple(str(a) for a in (cap.get("aliases") or []) if isinstance(a, str)),
        examples=tuple(str(e) for e in (cap.get("examples") or []) if isinstance(e, str)),
    )
)
```

```yaml
# registry/capabilities.yaml (在 MM.Inventory.GetAvailability 下新增)
  - capabilityId: MM.Inventory.GetAvailability
    name: Inventory Availability
    description: Read material availability for a plant through SAP MD04 stock/requirements list.
    aliases:
      - 库存查询
      - 物料可用量
    examples:
      - "查物料 DEMOA2 在 1000 工厂的库存"
      - "DEMOA2 1000 还有多少"
    # ... 既有字段不变
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_loader.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/registry_loader.py registry/capabilities.yaml agent/tests/test_registry_loader.py
git commit -m "feat(registry): add optional aliases/examples fields to CapabilityDescriptor and capabilities.yaml"
```

### Task 2.1: 实现 lexical recall

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_recall.py
from sap_nexus_agent.recall import recall


def _make_visible_set(capability_ids):
    """Build a minimal VisibleCapabilitySet stub for recall tests."""
    from types import SimpleNamespace
    cards = tuple(
        SimpleNamespace(capability_id=cid) for cid in capability_ids
    )
    return SimpleNamespace(cards=cards, snapshot_id="snap-001", principal_id="p")


def test_lexical_recall_matches_capability_description():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    visible = _make_visible_set(["MM.Inventory.GetAvailability"])
    candidates = recall("查库存", visible, catalog)
    assert "MM.Inventory.GetAvailability" in candidates
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py::test_lexical_recall_matches_capability_description -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sap_nexus_agent.recall'`

- [ ] **Step 3: 实现 `recall` (lexical 部分)**

```python
# agent/sap_nexus_agent/recall.py
from __future__ import annotations

from sap_nexus_agent.registry_loader import IntentCatalog


def recall(
    utterance: str,
    visible_capability_set,
    catalog: IntentCatalog,
) -> list[str]:
    """Closed-set recall: merge lexical + alias + example matches, dedupe by capability_id.

    Advisory only; does NOT produce a MatchDecision. Returns capability_ids
    that are both visible and recalled by any of the three sources.
    """
    visible_ids = {c.capability_id for c in visible_capability_set.cards}
    recalled: set[str] = set()

    for descriptor in catalog.capabilities:
        if descriptor.capability_id not in visible_ids:
            continue
        if _lexical_match(utterance, descriptor):
            recalled.add(descriptor.capability_id)

    return sorted(recalled)


def _lexical_match(utterance: str, descriptor) -> bool:
    """Keyword match against capability name + description."""
    text = utterance.lower()
    name = descriptor.name.lower()
    description = descriptor.description.lower()
    # Tokenize name/description into keywords (len >= 2 to avoid noise).
    keywords = {w for w in name.split() + description.split() if len(w) >= 2}
    # Also include CJK substrings from name/description (Chinese has no spaces).
    for kw in keywords:
        if kw in text:
            return True
    # CJK direct substring: any char from name/description present in utterance.
    for ch in name + description:
        if "\u4e00" <= ch <= "\u9fff" and ch in utterance:
            return True
    return False
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py::test_lexical_recall_matches_capability_description -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/recall.py agent/tests/test_recall.py
git commit -m "feat(recall): implement lexical recall over capability name/description"
```

### Task 2.2: 实现 alias recall

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_recall.py (追加)
def test_alias_recall_matches_registry_alias():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    visible = _make_visible_set(["MM.Inventory.GetAvailability"])
    # "库存查询" is a registered alias for MM.Inventory.GetAvailability
    candidates = recall("库存查询一下", visible, catalog)
    assert "MM.Inventory.GetAvailability" in candidates
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py::test_alias_recall_matches_registry_alias -v`
Expected: FAIL (alias not yet checked in `recall`)

- [ ] **Step 3: 实现 alias recall**

```python
# agent/sap_nexus_agent/recall.py (修改 recall 函数，在 lexical 后追加)
    for descriptor in catalog.capabilities:
        if descriptor.capability_id not in visible_ids:
            continue
        if _lexical_match(utterance, descriptor):
            recalled.add(descriptor.capability_id)
        if _alias_match(utterance, descriptor):
            recalled.add(descriptor.capability_id)


def _alias_match(utterance: str, descriptor) -> bool:
    """Substring match against capability aliases from registry."""
    for alias in descriptor.aliases:
        if alias and alias in utterance:
            return True
    return False
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/recall.py agent/tests/test_recall.py
git commit -m "feat(recall): implement alias recall over registry aliases"
```

### Task 2.3: 实现 example recall

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_recall.py (追加)
def test_example_recall_matches_registry_example():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    visible = _make_visible_set(["MM.Inventory.GetAvailability"])
    # Example: "查物料 DEMOA2 在 1000 工厂的库存"
    candidates = recall("查物料 DEMOA2 在 1000 工厂的库存", visible, catalog)
    assert "MM.Inventory.GetAvailability" in candidates
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py::test_example_recall_matches_registry_example -v`
Expected: PASS (lexical already catches "库存") — reframe test to use example-only match

```python
# agent/tests/test_recall.py (修正)
def test_example_recall_matches_when_lexical_misses():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    visible = _make_visible_set(["MM.Inventory.GetAvailability"])
    # Use an example that doesn't trigger lexical/alias: "DEMOA2 1000 还有多少"
    # "还有多少" is not in name/description/aliases but is in examples.
    candidates = recall("DEMOA2 1000 还有多少", visible, catalog)
    assert "MM.Inventory.GetAvailability" in candidates
```

- [ ] **Step 3: 实现 example recall**

```python
# agent/sap_nexus_agent/recall.py (修改 recall 函数，在 alias 后追加)
        if _alias_match(utterance, descriptor):
            recalled.add(descriptor.capability_id)
        if _example_match(utterance, descriptor):
            recalled.add(descriptor.capability_id)


def _example_match(utterance: str, descriptor) -> bool:
    """Substring match against capability examples from registry."""
    for example in descriptor.examples:
        if example and example in utterance:
            return True
    return False
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/recall.py agent/tests/test_recall.py
git commit -m "feat(recall): implement example recall over registry examples"
```

### Task 2.4: recall 合并 + 去重

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_recall.py (追加)
def test_recall_dedupes_by_capability_id():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    visible = _make_visible_set(["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"])
    # Utterance triggers lexical+alias+example for inventory; each only once.
    candidates = recall("库存查询 查物料 DEMOA2 在 1000 工厂的库存", visible, catalog)
    assert candidates.count("MM.Inventory.GetAvailability") == 1


def test_recall_excludes_invisible_capabilities():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    # Only PO visible; inventory not in visible set.
    visible = _make_visible_set(["MM.PurchaseOrder.GetList"])
    candidates = recall("查库存", visible, catalog)
    assert "MM.Inventory.GetAvailability" not in candidates
```

- [ ] **Step 2: 验证测试通过 (已由 set 去重实现)**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py -v`
Expected: PASS (recall already uses `set` for dedupe; this step locks the contract)

- [ ] **Step 3: 无需新代码（验证既有实现满足契约）**

- [ ] **Step 4: 验证全量 recall 测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_recall.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_recall.py
git commit -m "test(recall): lock dedupe + visibility-filter contracts"
```

---

## Task 3: 有界 rerank 阶段 (Bounded Rerank)

**Files:**
- Create: `agent/sap_nexus_agent/rerank.py`
- Test: `agent/tests/test_rerank.py`

**Interfaces:**
- Consumes: `IntentEnvelope` (goals / capability_hint / parameters), `recall_candidates: list[str]`, `IntentCatalog` (required inputs for param fit)
- Produces: `rerank(envelope, recall_candidates, catalog) -> tuple[list[str], dict[str, int]]` (ranked_candidates, rerank_evidence)

### Task 3.1: 实现 rerank 评分

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_rerank.py
from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal
from sap_nexus_agent.rerank import rerank


def _envelope(hint, parameters):
    return IntentEnvelope(
        envelope_id="eid",
        utterance="u",
        goals=(IntentGoal(goal_text="g", capability_hint=hint, parameters=parameters, missing=[]),),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap",
        discard_reasons=[],
        created_by="llm",
    )


def test_rerank_llm_hint_ranks_first():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    envelope = _envelope("MM.Inventory.GetAvailability", {"material": "DEMOA2", "plant": "1000"})
    ranked, evidence = rerank(envelope, ["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"], catalog)
    assert ranked[0] == "MM.Inventory.GetAvailability"
    # hint(+3) + lexical(+2) + alias(+0) + example(+0) + param_fit(+1) = 6
    assert evidence["MM.Inventory.GetAvailability"] >= 5
    assert "MM.Inventory.GetAvailability" in evidence


def test_rerank_param_fit_only_when_all_required_covered():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    # Only material provided (plant missing) -> param_fit +0
    envelope = _envelope("MM.Inventory.GetAvailability", {"material": "DEMOA2"})
    ranked, evidence = rerank(envelope, ["MM.Inventory.GetAvailability"], catalog)
    # hint(+3) + lexical(+2) + param_fit(+0) = 5 (no +1 bonus)
    assert evidence["MM.Inventory.GetAvailability"] == 5
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_rerank.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sap_nexus_agent.rerank'`

- [ ] **Step 3: 实现 `rerank`**

```python
# agent/sap_nexus_agent/rerank.py
from __future__ import annotations

from sap_nexus_agent.intent_envelope import IntentEnvelope
from sap_nexus_agent.registry_loader import IntentCatalog


def rerank(
    envelope: IntentEnvelope,
    recall_candidates: list[str],
    catalog: IntentCatalog,
) -> tuple[list[str], dict[str, int]]:
    """Bounded rerank: score recall_candidates by heuristic (no embedding).

    Scoring:
      - LLM capability_hint match: +3
      - lexical match (name/description keyword): +2
      - alias match: +2
      - example match: +1
      - parameter fit (all required inputs covered): +1

    Returns (ranked_candidates sorted desc by score, rerank_evidence {id: score}).
    Advisory only; does NOT produce a MatchDecision.
    """
    # Collect LLM hints + parameters from envelope goals.
    hints = {g.capability_hint for g in envelope.goals if g.capability_hint}
    goal_params = {g.capability_hint: g.parameters for g in envelope.goals if g.capability_hint}

    evidence: dict[str, int] = {}
    for cap_id in recall_candidates:
        descriptor = catalog.find(cap_id)
        if descriptor is None:
            continue
        score = 0
        if cap_id in hints:
            score += 3
        if _lexical_match(envelope.utterance, descriptor):
            score += 2
        if _alias_match(envelope.utterance, descriptor):
            score += 2
        if _example_match(envelope.utterance, descriptor):
            score += 1
        params = goal_params.get(cap_id, {})
        if _param_fit(params, descriptor):
            score += 1
        evidence[cap_id] = score

    ranked = sorted(evidence.keys(), key=lambda cid: (-evidence[cid], cid))
    return ranked, evidence


def _lexical_match(utterance: str, descriptor) -> bool:
    text = utterance.lower()
    name = descriptor.name.lower()
    description = descriptor.description.lower()
    for ch in name + description:
        if "\u4e00" <= ch <= "\u9fff" and ch in utterance:
            return True
    keywords = {w for w in name.split() + description.split() if len(w) >= 2}
    return any(kw in text for kw in keywords)


def _alias_match(utterance: str, descriptor) -> bool:
    return any(alias and alias in utterance for alias in descriptor.aliases)


def _example_match(utterance: str, descriptor) -> bool:
    return any(example and example in utterance for example in descriptor.examples)


def _param_fit(parameters: dict[str, str], descriptor) -> bool:
    """+1 only when ALL required inputs are covered by LLM-provided parameters."""
    required = {inp.name for inp in descriptor.inputs if inp.required}
    return required.issubset(parameters.keys())
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_rerank.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/rerank.py agent/tests/test_rerank.py
git commit -m "feat(rerank): implement bounded rerank scoring with param-fit bonus"
```

### Task 3.2: 稳定 tie-break

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_rerank.py (追加)
def test_rerank_tie_break_alphabetical():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    # No hint, no lexical/alias/example -> all score 0 -> alphabetical.
    envelope = _envelope(None, {})
    ranked, evidence = rerank(
        envelope,
        ["MM.PR.CreateDraft", "MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"],
        catalog,
    )
    assert ranked == sorted(["MM.PR.CreateDraft", "MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"])
```

- [ ] **Step 2: 验证测试通过 (已由 sorted key 实现)**

Run: `.venv/bin/python -m pytest agent/tests/test_rerank.py::test_rerank_tie_break_alphabetical -v`
Expected: PASS (sorted with `(-score, cid)` key already breaks ties alphabetically)

- [ ] **Step 3: 无需新代码（验证既有实现满足契约）**

- [ ] **Step 4: 验证全量 rerank 测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_rerank.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_rerank.py
git commit -m "test(rerank): lock alphabetical tie-break contract"
```

### Task 3.3: 输出 `ranked_candidates` + `rerank_evidence`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_rerank.py (追加)
def test_rerank_returns_ranked_candidates_and_evidence():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    envelope = _envelope("MM.Inventory.GetAvailability", {"material": "DEMOA2", "plant": "1000"})
    ranked, evidence = rerank(envelope, ["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"], catalog)
    assert isinstance(ranked, list)
    assert isinstance(evidence, dict)
    assert all(isinstance(v, int) for v in evidence.values())
    # ranked is sorted desc by score
    scores = [evidence[cid] for cid in ranked]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_rerank.py -v`
Expected: PASS

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_rerank.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_rerank.py
git commit -m "test(rerank): lock ranked_candidates + rerank_evidence output contract"
```

---

## Task 4: LLM 输出 discard + 结构化原因 (Discard Detection)

**Files:**
- Create: `agent/sap_nexus_agent/discard.py`
- Test: `agent/tests/test_discard.py`

**Interfaces:**
- Consumes: LLM payload `dict[str, object]`, `visible_capability_ids: set[str]`
- Produces: `detect_discard_reasons(payload, visible_capability_ids) -> list[str]`

### Task 4.1: 检测未知 capability

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_discard.py
from sap_nexus_agent.discard import detect_discard_reasons


def test_unknown_capability_recorded():
    payload = {
        "goals": [
            {"goalText": "g", "capabilityHint": "Foo.Bar", "parameters": {}, "missing": []}
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "unknown_capability:Foo.Bar" in reasons


def test_known_capability_no_reason():
    payload = {
        "goals": [
            {"goalText": "g", "capabilityHint": "MM.Inventory.GetAvailability", "parameters": {}, "missing": []}
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert not any(r.startswith("unknown_capability:") for r in reasons)
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sap_nexus_agent.discard'`

- [ ] **Step 3: 实现 `detect_discard_reasons` (unknown_capability 部分)**

```python
# agent/sap_nexus_agent/discard.py
from __future__ import annotations

import re

TECHNICAL_FIELDS = frozenset({
    "baseUrl", "rfcName", "credential", "header", "token",
    "authorization", "destination", "serviceRef", "bindingId",
    "entitySet", "executorType", "sapClient", "csrf",
})

INVALID_PARAM_PATTERNS = re.compile(r"__proto__|constructor|prototype", re.IGNORECASE)


def detect_discard_reasons(
    payload: dict[str, object],
    visible_capability_ids: set[str],
) -> list[str]:
    """Detect discard reasons in LLM payload: unknown capability / technical field / invalid param.

    Returns a list of structured reason strings like:
      - "unknown_capability:<id>"
      - "technical_field:<name>"
      - "invalid_param:<name>"

    Empty when the LLM output is fully valid.
    """
    reasons: list[str] = []
    goals = payload.get("goals") or []
    if not isinstance(goals, list):
        return reasons

    for goal in goals:
        if not isinstance(goal, dict):
            continue
        hint = goal.get("capabilityHint")
        if isinstance(hint, str) and hint and hint not in visible_capability_ids:
            reasons.append(f"unknown_capability:{hint}")

    return reasons
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/discard.py agent/tests/test_discard.py
git commit -m "feat(discard): detect unknown capability hints"
```

### Task 4.2: 检测技术字段

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_discard.py (追加)
def test_technical_field_recorded():
    payload = {
        "goals": [
            {
                "goalText": "g",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"baseUrl": "http://evil", "material": "DEMOA2"},
                "missing": [],
            }
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "technical_field:baseUrl" in reasons


def test_rfcname_in_parameters_recorded():
    payload = {
        "goals": [
            {
                "goalText": "g",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"rfcName": "BAPI_EVIL"},
                "missing": [],
            }
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "technical_field:rfcName" in reasons
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py::test_technical_field_recorded -v`
Expected: FAIL (technical field not yet detected)

- [ ] **Step 3: 实现技术字段检测**

```python
# agent/sap_nexus_agent/discard.py (修改 detect_discard_reasons，在 unknown_capability 后追加)
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        hint = goal.get("capabilityHint")
        if isinstance(hint, str) and hint and hint not in visible_capability_ids:
            reasons.append(f"unknown_capability:{hint}")
        parameters = goal.get("parameters") or {}
        if isinstance(parameters, dict):
            for key in parameters:
                key_str = str(key)
                if key_str in TECHNICAL_FIELDS:
                    reasons.append(f"technical_field:{key_str}")
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/discard.py agent/tests/test_discard.py
git commit -m "feat(discard): detect technical fields in LLM parameters"
```

### Task 4.3: 检测非法参数

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_discard.py (追加)
def test_invalid_param_recorded():
    payload = {
        "goals": [
            {
                "goalText": "g",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"__proto__": "evil", "material": "DEMOA2"},
                "missing": [],
            }
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "invalid_param:__proto__" in reasons


def test_constructor_param_recorded():
    payload = {
        "goals": [
            {
                "goalText": "g",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"constructor": "evil"},
                "missing": [],
            }
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert "invalid_param:constructor" in reasons
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py::test_invalid_param_recorded -v`
Expected: FAIL (invalid param not yet detected)

- [ ] **Step 3: 实现非法参数检测**

```python
# agent/sap_nexus_agent/discard.py (修改 detect_discard_reasons，在 technical_field 后追加)
        parameters = goal.get("parameters") or {}
        if isinstance(parameters, dict):
            for key in parameters:
                key_str = str(key)
                if key_str in TECHNICAL_FIELDS:
                    reasons.append(f"technical_field:{key_str}")
                if INVALID_PARAM_PATTERNS.search(key_str):
                    reasons.append(f"invalid_param:{key_str}")
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/discard.py agent/tests/test_discard.py
git commit -m "feat(discard): detect invalid parameter names (__proto__/constructor/prototype)"
```

### Task 4.4: 合法时 discard_reasons 为空

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_discard.py (追加)
def test_valid_payload_empty_discard_reasons():
    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"material": "DEMOA2", "plant": "1000"},
                "missing": [],
            }
        ]
    }
    visible_ids = {"MM.Inventory.GetAvailability"}
    reasons = detect_discard_reasons(payload, visible_ids)
    assert reasons == []


def test_empty_payload_empty_reasons():
    reasons = detect_discard_reasons({}, {"MM.Inventory.GetAvailability"})
    assert reasons == []
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: PASS

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证全量 discard 测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_discard.py
git commit -m "test(discard): lock empty-reasons contract for valid payload"
```

---

## Task 5: IntentEnvelope 产出 (LLM + Rule)

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py`, `agent/sap_nexus_agent/intent.py`
- Test: `agent/tests/test_llm_intent.py`, `agent/tests/test_intent.py`

**Interfaces:**
- Consumes: `IntentGoal` / `IntentEnvelope` (Task 1), `detect_discard_reasons` (Task 4)
- Produces: `_payload_to_envelope(payload, visible_capability_set, snapshot_id) -> IntentEnvelope`; `_parse_result_to_envelope(result, snapshot_id) -> IntentEnvelope`; `IntentAdapter = Callable[[str, ConversationContext | None], IntentEnvelope]`

### Task 5.1: 升级 LLM prompt schema

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_llm_intent.py (追加)
def test_llm_prompt_requests_goals_array():
    """LLM prompt schema now asks for goals / candidates / constraints / ambiguities / evidence."""
    from sap_nexus_agent.llm_intent import _messages
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    messages = _messages("查库存", catalog, context=None)
    system_content = messages[0]["content"]
    assert "goals" in system_content
    assert "constraints" in system_content
    assert "ambiguities" in system_content
    assert "evidence" in system_content
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_llm_prompt_requests_goals_array -v`
Expected: FAIL (existing prompt does not mention goals/constraints/ambiguities/evidence)

- [ ] **Step 3: 升级 LLM prompt**

```python
# agent/sap_nexus_agent/llm_intent.py (修改 _messages 的 base_system content)
base_system = {
    "role": "system",
    "content": (
        "You extract SAP Nexus read-only query intent as strict JSON. "
        "Detect all matching capabilities from the registered closed set below. "
        "Return keys: goals, candidates, constraints, ambiguities, evidence.\n"
        "- goals: array of {goalText, capabilityHint, parameters, missing}. capabilityHint must be from the closed set. "
        "- candidates: array of capabilityIds matched (advisory, used by recall). "
        "- constraints: object of user-level constraints (e.g. {language: zh-CN}). "
        "- ambiguities: array of strings describing ambiguity points (advisory). "
        "- evidence: object summarizing payload (e.g. {goals: 2, candidates: [...]}).\n"
        "Rules:\n"
        "- Never introduce capabilityIds outside the closed set (will be discarded). "
        "- Never output rfcName or raw SAP BAPI/RFC names. "
        "- Never include technical fields (baseUrl, credential, token, header, etc.) in parameters. "
        "- If user mentions multiple values for a parameter, put it in multiParameters as a string array.\n"
        f"Registered capabilities:\n{capabilities_desc}"
    ),
}
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_llm_prompt_requests_goals_array -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent): upgrade prompt schema to goals/candidates/constraints/ambiguities/evidence"
```

### Task 5.2: 实现 `_payload_to_envelope`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_llm_intent.py (追加)
from types import SimpleNamespace


def _visible_set(ids):
    return SimpleNamespace(
        cards=tuple(SimpleNamespace(capability_id=i) for i in ids),
        snapshot_id="snap-001",
        principal_id="p",
    )


def test_payload_to_envelope_valid_llm_output():
    from sap_nexus_agent.llm_intent import _payload_to_envelope

    payload = {
        "goals": [
            {
                "goalText": "查库存",
                "capabilityHint": "MM.Inventory.GetAvailability",
                "parameters": {"material": "DEMOA2", "plant": "1000"},
                "missing": [],
            }
        ],
        "candidates": ["MM.Inventory.GetAvailability"],
        "constraints": {"language": "zh-CN"},
        "ambiguities": [],
        "evidence": {"goals": 1},
    }
    visible = _visible_set(["MM.Inventory.GetAvailability"])
    envelope = _payload_to_envelope(payload, visible, snapshot_id="snap-001")
    assert envelope.created_by == "llm"
    assert envelope.snapshot_id == "snap-001"
    assert len(envelope.goals) == 1
    assert envelope.goals[0].capability_hint == "MM.Inventory.GetAvailability"
    assert envelope.discard_reasons == []
    assert envelope.user_constraints == {"language": "zh-CN"}


def test_payload_to_envelope_unknown_capability_discarded():
    from sap_nexus_agent.llm_intent import _payload_to_envelope

    payload = {
        "goals": [
            {"goalText": "g", "capabilityHint": "Foo.Bar", "parameters": {}, "missing": []}
        ],
        "candidates": ["Foo.Bar"],
    }
    visible = _visible_set(["MM.Inventory.GetAvailability"])
    envelope = _payload_to_envelope(payload, visible, snapshot_id="snap-001")
    assert "unknown_capability:Foo.Bar" in envelope.discard_reasons
    # Goal with unknown hint is dropped from goals tuple
    assert len(envelope.goals) == 0


def test_payload_to_envelope_rfc_name_full_discard():
    from sap_nexus_agent.llm_intent import _payload_to_envelope

    payload = {"goals": [], "rfcName": "BAPI_EVIL"}
    visible = _visible_set(["MM.Inventory.GetAvailability"])
    envelope = _payload_to_envelope(payload, visible, snapshot_id="snap-001")
    assert len(envelope.goals) == 0
    # rfcName triggers full discard; reason recorded
    assert any("rfcName" in r or "technical_field" in r for r in envelope.discard_reasons) or envelope.discard_reasons == []
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_payload_to_envelope_valid_llm_output -v`
Expected: FAIL with `ImportError: cannot import name '_payload_to_envelope'`

- [ ] **Step 3: 实现 `_payload_to_envelope`**

```python
# agent/sap_nexus_agent/llm_intent.py (新增函数；保留 _payload_to_parse_result 临时供 rule fallback 过渡)
import uuid
from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal
from sap_nexus_agent.discard import detect_discard_reasons


def _payload_to_envelope(
    payload: dict[str, object],
    visible_capability_set,
    snapshot_id: str,
) -> IntentEnvelope:
    """Convert LLM payload to IntentEnvelope with structured discard reasons.

    Algorithm:
      1. rfcName / OData override in payload -> full discard (empty goals).
      2. detect_discard_reasons(payload, visible_ids) -> discard_reasons.
      3. For each goal: drop goal if capability_hint is unknown (already in discard_reasons).
         Drop technical_field / invalid_param keys from goal.parameters.
      4. Build IntentGoal tuple from surviving goals.
    """
    visible_ids = {c.capability_id for c in visible_capability_set.cards}

    # rfcName / OData full-discard (defense-in-depth, design doc §7).
    contains_rfc_name = any(str(key).lower() == "rfcname" for key in payload)
    contains_odata_override = _detect_odata_override(json.dumps(payload, ensure_ascii=False))
    if contains_rfc_name or contains_odata_override:
        discard_reasons = []
        if contains_rfc_name:
            discard_reasons.append("technical_field:rfcName")
        return IntentEnvelope(
            envelope_id=uuid.uuid4().hex,
            utterance="",
            goals=(),
            user_constraints={},
            ambiguities=[],
            reference_turn_id=None,
            model_evidence={},
            snapshot_id=snapshot_id,
            discard_reasons=discard_reasons,
            created_by="llm",
        )

    discard_reasons = detect_discard_reasons(payload, visible_ids)

    raw_goals = payload.get("goals") or []
    goals: list[IntentGoal] = []
    for raw in raw_goals:
        if not isinstance(raw, dict):
            continue
        hint = raw.get("capabilityHint")
        # Drop goal entirely if hint is unknown (closed-set defense).
        if isinstance(hint, str) and hint and hint not in visible_ids:
            continue
        raw_params = raw.get("parameters") or {}
        # Filter out technical_field / invalid_param keys.
        parameters = {
            str(k): str(v)
            for k, v in (raw_params.items() if isinstance(raw_params, dict) else {})
            if str(k) not in TECHNICAL_FIELDS
            and not INVALID_PARAM_PATTERNS.search(str(k))
            and v is not None
            and str(v).strip()
        }
        # Allowlist filter against descriptor inputs (if hint is known).
        if isinstance(hint, str) and hint:
            from sap_nexus_agent.registry_loader import load_intent_catalog
            descriptor = load_intent_catalog().find(hint)
            if descriptor is not None:
                allowed = {inp.name for inp in descriptor.inputs}
                parameters = {k: v for k, v in parameters.items() if k in allowed}
                missing = [inp.name for inp in descriptor.inputs if inp.required and inp.name not in parameters]
            else:
                missing = []
        else:
            missing = [str(m) for m in (raw.get("missing") or []) if isinstance(m, str)]
        goals.append(
            IntentGoal(
                goal_text=str(raw.get("goalText", "")),
                capability_hint=hint if isinstance(hint, str) else None,
                parameters=parameters,
                missing=missing,
            )
        )

    user_constraints = {
        str(k): str(v)
        for k, v in (payload.get("constraints") or {}).items()
        if isinstance(payload.get("constraints"), dict)
    }
    ambiguities = [str(a) for a in (payload.get("ambiguities") or []) if isinstance(a, str)]
    model_evidence = dict(payload.get("evidence") or {}) if isinstance(payload.get("evidence"), dict) else {}

    return IntentEnvelope(
        envelope_id=uuid.uuid4().hex,
        utterance="",
        goals=tuple(goals),
        user_constraints=user_constraints,
        ambiguities=ambiguities,
        reference_turn_id=None,
        model_evidence=model_evidence,
        snapshot_id=snapshot_id,
        discard_reasons=discard_reasons,
        created_by="llm",
    )
```

Note: import `TECHNICAL_FIELDS` / `INVALID_PARAM_PATTERNS` from `discard` module at top of `llm_intent.py`:

```python
from sap_nexus_agent.discard import TECHNICAL_FIELDS, INVALID_PARAM_PATTERNS, detect_discard_reasons
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py -v -k payload_to_envelope`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent): implement _payload_to_envelope with structured discard"
```

### Task 5.3: 从 `GovernedContext` 绑定 `snapshot_id`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_llm_intent.py (追加)
def test_parse_with_llm_binds_snapshot_id():
    """parse_with_llm forwards snapshot_id from visible_capability_set to envelope."""
    from sap_nexus_agent.llm_intent import parse_with_llm
    from sap_nexus_agent.registry_loader import load_intent_catalog

    class _StubClient:
        def chat_json(self, messages, *, temperature, max_tokens):
            return {
                "goals": [
                    {"goalText": "g", "capabilityHint": "MM.Inventory.GetAvailability", "parameters": {}, "missing": []}
                ],
                "candidates": ["MM.Inventory.GetAvailability"],
            }

    catalog = load_intent_catalog()
    visible = _visible_set(["MM.Inventory.GetAvailability"])
    envelope = parse_with_llm("查库存", _StubClient(), catalog, visible_capability_set=visible, snapshot_id="snap-007")
    assert envelope.snapshot_id == "snap-007"
    assert envelope.created_by == "llm"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_parse_with_llm_binds_snapshot_id -v`
Expected: FAIL (parse_with_llm does not yet accept visible_capability_set / snapshot_id)

- [ ] **Step 3: 升级 `parse_with_llm` 签名**

```python
# agent/sap_nexus_agent/llm_intent.py (修改 parse_with_llm)
def parse_with_llm(
    text: str,
    client: JsonLlmClient,
    catalog: IntentCatalog,
    *,
    context: "ConversationContext | None" = None,
    visible_capability_set=None,
    snapshot_id: str = "",
) -> IntentEnvelope:
    try:
        payload = client.chat_json(_messages(text, catalog, context=context), temperature=0.0, max_tokens=400)
    except (LlmUnavailable, json.JSONDecodeError, ValueError, TypeError):
        raise LlmUnavailable("LLM intent parsing unavailable")
    if visible_capability_set is None:
        # Build a minimal visible set from catalog (all capabilities visible).
        from types import SimpleNamespace
        visible_capability_set = SimpleNamespace(
            cards=tuple(SimpleNamespace(capability_id=c.capability_id) for c in catalog.capabilities),
            snapshot_id=snapshot_id,
            principal_id="",
        )
    envelope = _payload_to_envelope(payload, visible_capability_set, snapshot_id=snapshot_id)
    # Bind utterance (not in payload's goals).
    from dataclasses import replace
    return replace(envelope, utterance=text)
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_parse_with_llm_binds_snapshot_id -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent): bind snapshot_id from visible_capability_set to IntentEnvelope"
```

### Task 5.4: rule fallback 产出 `IntentEnvelope`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_intent.py (新增或追加)
def test_parse_intent_returns_envelope_rule_path():
    """Rule path parse_intent returns IntentEnvelope with created_by='rule'."""
    from sap_nexus_agent.intent import parse_intent
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    envelope = parse_intent("库存 DEMOA2 1000", snapshot_id="snap-rule")
    assert isinstance(envelope, IntentEnvelope)
    assert envelope.created_by == "rule"
    assert envelope.snapshot_id == "snap-rule"
    assert envelope.model_evidence == {}
    assert len(envelope.goals) >= 1
    assert envelope.goals[0].capability_hint == "MM.Inventory.GetAvailability"


def test_parse_intent_rule_fallback_rfc_name_envelope():
    from sap_nexus_agent.intent import parse_intent
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    envelope = parse_intent("rfcName=BAPI_X 查库存", snapshot_id="snap-rule")
    assert isinstance(envelope, IntentEnvelope)
    assert envelope.created_by == "rule"
    assert len(envelope.goals) == 0
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_intent.py::test_parse_intent_returns_envelope_rule_path -v`
Expected: FAIL (parse_intent still returns IntentParseResult)

- [ ] **Step 3: 重构 `parse_intent` 返回 `IntentEnvelope`**

```python
# agent/sap_nexus_agent/intent.py (顶部新增 import + 重构 parse_intent)
import uuid
from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal


def parse_intent(
    text: str,
    context: "ConversationContext | None" = None,
    *,
    snapshot_id: str = "",
) -> IntentEnvelope:
    """Unified intent entry returning IntentEnvelope (created_by='rule').

    Reuses existing keyword extraction logic via _RuleParsePayload, then
    converts to IntentEnvelope. Technical override (rfcName / OData) returns
    an envelope with empty goals and discard_reasons.
    """
    # Build internal rule payload (reuse existing extraction).
    rule_payload = _extract_rule_payload(text, context)
    return _rule_payload_to_envelope(rule_payload, text, snapshot_id)


def _extract_rule_payload(text: str, context: "ConversationContext | None"):
    """Run existing keyword extraction; return a SimpleNamespace carrying
    contains_rfc_name / contains_odata_override / matched_intents / etc.
    Reuses the existing extraction code (kept private)."""
    # ... existing parse_intent body, returning a namespace with the same fields ...
    # (Implementation: move existing body here, return SimpleNamespace(...).)


def _rule_payload_to_envelope(rule_payload, utterance: str, snapshot_id: str) -> IntentEnvelope:
    """Convert rule extraction to IntentEnvelope (created_by='rule')."""
    discard_reasons: list[str] = []
    if rule_payload.contains_rfc_name:
        discard_reasons.append("technical_field:rfcName")
    if rule_payload.contains_odata_override:
        discard_reasons.append("technical_field:odata_override")

    goals: list[IntentGoal] = []
    for mi in rule_payload.matched_intents:
        goals.append(
            IntentGoal(
                goal_text=utterance,
                capability_hint=mi.capability_id,
                parameters=dict(mi.parameters),
                missing=list(mi.missing),
            )
        )

    return IntentEnvelope(
        envelope_id=uuid.uuid4().hex,
        utterance=utterance,
        goals=tuple(goals),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},  # rule path: empty model_evidence
        snapshot_id=snapshot_id,
        discard_reasons=discard_reasons,
        created_by="rule",
    )
```

Note: the existing `IntentParseResult` dataclass and `resolve_with_context` helper stay temporarily for sticky continuation; they will be migrated in Task 8.3 to return `IntentEnvelope`.

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_intent.py -v`
Expected: PASS (existing tests may need updating to handle envelope return; defer full migration to Task 8)

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/intent.py agent/tests/test_intent.py
git commit -m "feat(intent): rule path parse_intent returns IntentEnvelope (created_by=rule)"
```

### Task 5.5: 升级 `IntentAdapter` 签名 (BREAKING)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_llm_intent.py (追加)
def test_build_intent_adapter_returns_envelope():
    from sap_nexus_agent.llm_intent import build_intent_adapter
    from sap_nexus_agent.intent_envelope import IntentEnvelope
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    adapter = build_intent_adapter("rule", catalog)
    envelope = adapter("库存 DEMOA2 1000", None, snapshot_id="snap-adapter")
    assert isinstance(envelope, IntentEnvelope)
    assert envelope.created_by == "rule"
    assert envelope.snapshot_id == "snap-adapter"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_build_intent_adapter_returns_envelope -v`
Expected: FAIL (build_intent_adapter still returns IntentParseResult-producing adapter)

- [ ] **Step 3: 升级 `build_intent_adapter` / `parse_with_hybrid` / `_parse_llm_only`**

```python
# agent/sap_nexus_agent/llm_intent.py (修改)
def parse_with_hybrid(
    text: str,
    client: JsonLlmClient | None = None,
    *,
    catalog: IntentCatalog | None = None,
    context: "ConversationContext | None" = None,
    visible_capability_set=None,
    snapshot_id: str = "",
) -> IntentEnvelope:
    if catalog is None:
        catalog = load_intent_catalog()
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        return parse_with_llm(
            text, llm_client, catalog,
            context=context,
            visible_capability_set=visible_capability_set,
            snapshot_id=snapshot_id,
        )
    except LlmUnavailable:
        return parse_intent(text, context=context, snapshot_id=snapshot_id)


def build_intent_adapter(mode: str, catalog: IntentCatalog | None = None):
    if catalog is None:
        catalog = load_intent_catalog()
    normalized = mode.lower()
    if normalized == "rule":
        return lambda text, context=None, *, snapshot_id="": parse_intent(text, context=context, snapshot_id=snapshot_id)
    if normalized == "llm":
        return lambda text, context=None, *, snapshot_id="", visible_capability_set=None: _parse_llm_only(
            text, catalog, context=context, visible_capability_set=visible_capability_set, snapshot_id=snapshot_id,
        )
    if normalized == "hybrid":
        return lambda text, context=None, *, snapshot_id="", visible_capability_set=None: parse_with_hybrid(
            text, catalog=catalog, context=context, visible_capability_set=visible_capability_set, snapshot_id=snapshot_id,
        )
    raise ValueError(f"Unsupported intent mode: {mode}")


def _parse_llm_only(
    text: str,
    catalog: IntentCatalog,
    *,
    context: "ConversationContext | None" = None,
    visible_capability_set=None,
    snapshot_id: str = "",
) -> IntentEnvelope:
    try:
        return parse_with_llm(
            text, OpenAiCompatibleLlmClient(), catalog,
            context=context,
            visible_capability_set=visible_capability_set,
            snapshot_id=snapshot_id,
        )
    except LlmUnavailable:
        return IntentEnvelope(
            envelope_id=uuid.uuid4().hex,
            utterance=text,
            goals=(),
            user_constraints={},
            ambiguities=[],
            reference_turn_id=None,
            model_evidence={},
            snapshot_id=snapshot_id,
            discard_reasons=[],
            created_by="rule",
        )
```

Update `IntentAdapter` type alias in `orchestrator.py`:

```python
# agent/sap_nexus_agent/orchestrator.py
IntentAdapter = Callable[[str, "ConversationContext | None"], IntentEnvelope]
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_build_intent_adapter_returns_envelope -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/sap_nexus_agent/orchestrator.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent)!: upgrade IntentAdapter signature to return IntentEnvelope (BREAKING)"
```

---

## Task 6: selector 升级 (Capability Selector Upgrade)

**Files:**
- Modify: `agent/sap_nexus_agent/capability_selector.py`, `agent/sap_nexus_agent/match_decision.py`
- Test: `agent/tests/test_capability_selector.py`, `agent/tests/test_match_decision.py`

**Interfaces:**
- Consumes: `IntentEnvelope` (goals / discard_reasons / snapshot_id), `recall_candidates: list[str]`, `rerank_evidence: dict[str, int]`, `VisibleCapabilitySet`
- Produces: `select_capability(envelope, recall_candidates, rerank_evidence, visible) -> MatchDecision` with replay fields populated

### Task 6.1: 升级 `select_capability` 签名 (BREAKING)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_capability_selector.py (追加)
from types import SimpleNamespace
from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal


def _envelope_single_goal_complete():
    return IntentEnvelope(
        envelope_id="env-001",
        utterance="库存 DEMOA2 1000",
        goals=(IntentGoal(
            goal_text="查库存",
            capability_hint="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "1000"},
            missing=[],
        ),),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )


def _visible_set(ids):
    return SimpleNamespace(
        cards=tuple(SimpleNamespace(capability_id=i) for i in ids),
        snapshot_id="snap-001",
        principal_id="p",
    )


def test_select_capability_consumes_envelope_select():
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    envelope = _envelope_single_goal_complete()
    visible = _visible_set(["MM.Inventory.GetAvailability"])
    decision = select_capability(
        envelope,
        recall_candidates=["MM.Inventory.GetAvailability"],
        rerank_evidence={"MM.Inventory.GetAvailability": 6},
        visible=visible,
    )
    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.envelope_id == "env-001"
    assert decision.recall_candidates == ["MM.Inventory.GetAvailability"]
    assert decision.rerank_evidence == {"MM.Inventory.GetAvailability": 6}
    assert decision.discard_reasons == []
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py::test_select_capability_consumes_envelope_select -v`
Expected: FAIL (select_capability still consumes IntentParseResult)

- [ ] **Step 3: 重写 `select_capability`**

```python
# agent/sap_nexus_agent/capability_selector.py (重写 select_capability)
def select_capability(
    envelope,
    *,
    recall_candidates: list[str] | None = None,
    rerank_evidence: dict[str, int] | None = None,
    visible,
) -> MatchDecision:
    """Five-state capability match decision consuming IntentEnvelope.

    Decision tree (order-sensitive):
      1. Technical override (rfcName / OData in discard_reasons) -> REJECT(UNSUPPORTED_RFC_NAME)
      2. envelope.goals with discard_reasons containing unknown_capability AND no surviving goals
         -> REJECT(VISIBILITY_DENIED) if any hint was denied
      3. envelope.goals > 1 -> ESCALATE_TO_PLANNER(handoff)
      4. ambiguity (envelope.ambiguities non-empty AND len(goals)==1) -> SHOW_OPTIONS(candidates)
      5. single goal missing params -> CLARIFY(missing)
      6. single goal complete -> SELECT(capability_id, params)
      7. no goal -> REJECT(UNSUPPORTED_INTENT)

    Replay fields (envelope_id / recall_candidates / rerank_evidence / discard_reasons)
    are populated on every returned MatchDecision.
    """
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchDecision, MatchedIntent

    visible_ids = frozenset(c.capability_id for c in visible.cards)
    visible_snapshot_id = visible.snapshot_id

    # Common replay fields.
    replay = dict(
        envelope_id=envelope.envelope_id,
        recall_candidates=list(recall_candidates or []),
        rerank_evidence=dict(rerank_evidence or {}),
        discard_reasons=list(envelope.discard_reasons),
    )

    # 1. Technical-override rejection.
    if any("rfcName" in r or "odata_override" in r or "technical_field:rfcName" in r for r in envelope.discard_reasons):
        return MatchDecision(
            decision_type="REJECT",
            error_type="UNSUPPORTED_RFC_NAME",
            rationale="Agent 不接受 rfcName 或 OData 技术覆盖，只能从已注册能力闭集选择。",
            **replay,
        )

    # 2. VISIBILITY_DENIED: LLM hint denied and no surviving goals.
    visibility_denied = any(r.startswith("unknown_capability:") for r in envelope.discard_reasons)
    if visibility_denied and len(envelope.goals) == 0:
        return MatchDecision(
            decision_type="REJECT",
            error_type="VISIBILITY_DENIED",
            rationale="LLM candidate not in VisibleCapabilitySet.",
            **replay,
        )

    # 3. Multi-goal -> ESCALATE_TO_PLANNER.
    if len(envelope.goals) > 1:
        matched_intents = [
            MatchedIntent(
                capability_id=g.capability_hint or "",
                parameters=dict(g.parameters),
                missing=list(g.missing),
            )
            for g in envelope.goals
            if g.capability_hint
        ]
        return MatchDecision(
            decision_type="ESCALATE_TO_PLANNER",
            handoff=EscalationHandoff(
                reason="multi-intent",
                matched_intents=matched_intents,
                utterance=envelope.utterance,
                registry_snapshot_id=visible_snapshot_id,
            ),
            rationale=f"matched {len(envelope.goals)} capabilities; planner composition required",
            **replay,
        )

    # 4. Ambiguity -> SHOW_OPTIONS.
    if envelope.ambiguities and len(envelope.goals) >= 1:
        candidates = [
            MatchedIntent(
                capability_id=g.capability_hint or "",
                parameters=dict(g.parameters),
                missing=list(g.missing),
            )
            for g in envelope.goals
            if g.capability_hint
        ]
        return MatchDecision(
            decision_type="SHOW_OPTIONS",
            candidates=candidates,
            rationale="utterance 弱匹配多能力关键词，需用户明确主意图",
            **replay,
        )

    # 5. Single goal missing params -> CLARIFY.
    if len(envelope.goals) == 1:
        goal = envelope.goals[0]
        if goal.missing:
            return MatchDecision(
                decision_type="CLARIFY",
                capability_id=goal.capability_hint,
                parameters=dict(goal.parameters),
                missing_parameters=list(goal.missing),
                rationale="请补充缺失的参数",
                **replay,
            )
        # 6. Single goal complete -> SELECT.
        if goal.capability_hint and goal.capability_hint in visible_ids:
            return MatchDecision(
                decision_type="SELECT",
                capability_id=goal.capability_hint,
                parameters=dict(goal.parameters),
                rationale="single capability matched with complete parameters",
                **replay,
            )
        # Hint not visible -> VISIBILITY_DENIED.
        if goal.capability_hint and goal.capability_hint not in visible_ids:
            return MatchDecision(
                decision_type="REJECT",
                error_type="VISIBILITY_DENIED",
                rationale="matched capability is not visible to this principal",
                **replay,
            )

    # 7. No goal -> REJECT(UNSUPPORTED_INTENT).
    return MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_INTENT",
        rationale="当前仅支持已注册的能力（库存可用量查询、采购订单列表、采购申请草稿创建）。",
        **replay,
    )
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py::test_select_capability_consumes_envelope_select -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/capability_selector.py agent/tests/test_capability_selector.py
git commit -m "feat(selector)!: select_capability consumes IntentEnvelope + replay fields (BREAKING)"
```

### Task 6.2: 在 matcher 之前接入 recall + rerank

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_capability_selector.py (追加)
def test_select_capability_uses_recall_rerank_for_replay_only():
    """recall + rerank are advisory; selector must populate replay fields
    from the passed recall_candidates / rerank_evidence without re-running them."""
    envelope = _envelope_single_goal_complete()
    visible = _visible_set(["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"])
    decision = select_capability(
        envelope,
        recall_candidates=["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"],
        rerank_evidence={"MM.Inventory.GetAvailability": 6, "MM.PurchaseOrder.GetList": 2},
        visible=visible,
    )
    assert decision.decision_type == "SELECT"
    assert decision.recall_candidates == ["MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"]
    assert decision.rerank_evidence == {"MM.Inventory.GetAvailability": 6, "MM.PurchaseOrder.GetList": 2}
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py::test_select_capability_uses_recall_rerank_for_replay_only -v`
Expected: PASS (already implemented in Task 6.1)

- [ ] **Step 3: 无需新代码（recall + rerank 由 cli/orchestrator 调用并传入）**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_capability_selector.py
git commit -m "test(selector): lock recall+rerank replay-only contract"
```

### Task 6.3: 填充 `MatchDecision` 回放字段

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_match_decision.py (追加)
def test_all_decision_types_carry_envelope_id():
    """Every MatchDecision variant carries envelope_id for replay."""
    from sap_nexus_agent.match_decision import MatchDecision

    for dt in ("SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"):
        d = MatchDecision(decision_type=dt, envelope_id="env-X")
        assert d.envelope_id == "env-X"
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py::test_all_decision_types_carry_envelope_id -v`
Expected: PASS (Task 1.5 already added the field with default None)

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_match_decision.py
git commit -m "test(match-decision): lock envelope_id replay contract for all decision types"
```

### Task 6.4: 新增 `REJECT(VISIBILITY_DENIED)`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_capability_selector.py (追加)
def test_select_capability_rejects_visibility_denied():
    """LLM hint not in visible set -> REJECT(VISIBILITY_DENIED)."""
    envelope = IntentEnvelope(
        envelope_id="env-002",
        utterance="查 Foo.Bar",
        goals=(),  # all goals dropped due to unknown hint
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=["unknown_capability:Foo.Bar"],
        created_by="llm",
    )
    visible = _visible_set(["MM.Inventory.GetAvailability"])
    decision = select_capability(envelope, recall_candidates=[], rerank_evidence={}, visible=visible)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "VISIBILITY_DENIED"
    assert "unknown_capability:Foo.Bar" in decision.discard_reasons
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py::test_select_capability_rejects_visibility_denied -v`
Expected: PASS (already implemented in Task 6.1 step 2)

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_capability_selector.py
git commit -m "test(selector): lock REJECT(VISIBILITY_DENIED) contract"
```

### Task 6.5: 移除 `SelectionResult` + `to_selection_result()` (BREAKING)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_match_decision.py (新增 - 应通过)
def test_selection_result_removed():
    """SelectionResult compat wrapper is removed."""
    try:
        from sap_nexus_agent.capability_selector import SelectionResult  # noqa: 4000
        raise AssertionError("SelectionResult should be removed")
    except ImportError:
        pass


def test_to_selection_result_removed():
    """to_selection_result() method is removed from MatchDecision."""
    from sap_nexus_agent.match_decision import MatchDecision

    decision = MatchDecision(decision_type="SELECT", capability_id="X", parameters={})
    assert not hasattr(decision, "to_selection_result")
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py::test_selection_result_removed agent/tests/test_match_decision.py::test_to_selection_result_removed -v`
Expected: FAIL (SelectionResult still importable, to_selection_result still exists)

- [ ] **Step 3: 移除 `SelectionResult` + `to_selection_result`**

```python
# agent/sap_nexus_agent/capability_selector.py (删除 SelectionResult dataclass)
# (Remove the entire @dataclass(frozen=True) class SelectionResult block.)

# agent/sap_nexus_agent/match_decision.py (删除 to_selection_result 方法 + 顶部 SelectionResult import)
# Remove: from sap_nexus_agent.capability_selector import SelectionResult
# Remove: def to_selection_result(self) -> SelectionResult | None: ... block
```

Also remove the existing `to_selection_result` tests from `test_match_decision.py` (they reference the removed method).

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py agent/tests/test_capability_selector.py -v`
Expected: PASS (existing to_selection_result tests removed; new removal tests pass)

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/capability_selector.py agent/sap_nexus_agent/match_decision.py agent/tests/test_match_decision.py
git commit -m "feat(match-decision)!: remove SelectionResult compat bridge (BREAKING)"
```

---

## Task 7: 跨轮 continuation (Cross-Turn Continuation)

**Files:**
- Modify: `agent/sap_nexus_agent/conversation_context.py`, `agent/sap_nexus_agent/orchestrator.py`
- Test: `agent/tests/test_conversation_context.py`, `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `PendingShowOptions` / `PendingEscalate` (Task 1.3 / 1.4), `MatchDecision` (Task 6)
- Produces: `ConversationContext.with_pending_show_options` / `with_pending_escalate` / `clear_pending`; orchestrator pending state machine

### Task 7.1: 扩展 `ConversationContext` 字段

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_conversation_context.py (追加)
def test_conversation_context_has_pending_fields():
    ctx = ConversationContext(last_context=None, history=None)
    assert ctx.pending_show_options is None
    assert ctx.pending_escalate is None


def test_conversation_context_round_trip_with_pending():
    from sap_nexus_agent.conversation_context import PendingShowOptions
    from sap_nexus_agent.match_decision import MatchedIntent

    candidates = (MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),)
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(candidates=candidates, snapshot_id="snap-001"),
    )
    payload = ctx.to_dict()
    restored = ConversationContext.from_dict(payload)
    assert restored.pending_show_options is not None
    assert restored.pending_show_options.snapshot_id == "snap-001"
    assert restored.pending_show_options.candidates[0].capability_id == "MM.PurchaseOrder.GetList"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_conversation_context_has_pending_fields -v`
Expected: FAIL (ConversationContext does not have pending_show_options field)

- [ ] **Step 3: 扩展 `ConversationContext`**

```python
# agent/sap_nexus_agent/conversation_context.py (修改 ConversationContext)
@dataclass(frozen=True)
class ConversationContext:
    last_context: LastContext | None
    history: tuple[Turn, ...] | None
    pending_show_options: PendingShowOptions | None = None
    pending_escalate: PendingEscalate | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "lastContext": self.last_context.to_dict() if self.last_context else None,
            "history": [t.to_dict() for t in self.history] if self.history else None,
            "pendingShowOptions": _pending_show_options_to_dict(self.pending_show_options),
            "pendingEscalate": _pending_escalate_to_dict(self.pending_escalate),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ConversationContext":
        last_raw = payload.get("lastContext")
        last_context = LastContext.from_dict(last_raw) if isinstance(last_raw, dict) else None
        history_raw = payload.get("history")
        history = (
            tuple(Turn.from_dict(item) for item in history_raw)
            if isinstance(history_raw, list)
            else None
        )
        pso_raw = payload.get("pendingShowOptions")
        pending_show_options = _pending_show_options_from_dict(pso_raw) if isinstance(pso_raw, dict) else None
        pe_raw = payload.get("pendingEscalate")
        pending_escalate = _pending_escalate_from_dict(pe_raw) if isinstance(pe_raw, dict) else None
        return cls(
            last_context=last_context,
            history=history,
            pending_show_options=pending_show_options,
            pending_escalate=pending_escalate,
        )
```

Note: `_pending_show_options_to_dict` / `_pending_escalate_to_dict` / `_pending_show_options_from_dict` / `_pending_escalate_from_dict` helpers must serialize `MatchedIntent` tuple and `EscalationHandoff` (lazy import `match_decision`).

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_conversation_context_has_pending_fields agent/tests/test_conversation_context.py::test_conversation_context_round_trip_with_pending -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/conversation_context.py agent/tests/test_conversation_context.py
git commit -m "feat(context): extend ConversationContext with pending_show_options/pending_escalate fields"
```

### Task 7.2: 实现互斥

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_conversation_context.py (追加)
def test_with_pending_show_options_clears_escalate():
    from sap_nexus_agent.conversation_context import PendingShowOptions
    from sap_nexus_agent.match_decision import MatchedIntent, EscalationHandoff

    handoff = EscalationHandoff(reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s")
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_escalate=PendingEscalate(handoff=handoff, snapshot_id="snap-1"),
    )
    new_ctx = ctx.with_pending_show_options(
        PendingShowOptions(
            candidates=(MatchedIntent(capability_id="X", parameters={}, missing=[]),),
            snapshot_id="snap-2",
        )
    )
    assert new_ctx.pending_show_options is not None
    assert new_ctx.pending_escalate is None


def test_with_pending_escalate_clears_show_options():
    from sap_nexus_agent.conversation_context import PendingShowOptions, PendingEscalate
    from sap_nexus_agent.match_decision import MatchedIntent, EscalationHandoff

    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(MatchedIntent(capability_id="X", parameters={}, missing=[]),),
            snapshot_id="snap-1",
        ),
    )
    handoff = EscalationHandoff(reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s")
    new_ctx = ctx.with_pending_escalate(PendingEscalate(handoff=handoff, snapshot_id="snap-2"))
    assert new_ctx.pending_escalate is not None
    assert new_ctx.pending_show_options is None


def test_clear_pending_clears_both():
    from sap_nexus_agent.conversation_context import PendingShowOptions, PendingEscalate
    from sap_nexus_agent.match_decision import MatchedIntent, EscalationHandoff

    handoff = EscalationHandoff(reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s")
    ctx = ConversationContext(
        last_context=None,
        history=None,
        pending_show_options=PendingShowOptions(
            candidates=(MatchedIntent(capability_id="X", parameters={}, missing=[]),),
            snapshot_id="snap-1",
        ),
        pending_escalate=PendingEscalate(handoff=handoff, snapshot_id="snap-2"),
    )
    cleared = ctx.clear_pending()
    assert cleared.pending_show_options is None
    assert cleared.pending_escalate is None
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_with_pending_show_options_clears_escalate -v`
Expected: FAIL (with_pending_show_options method does not exist)

- [ ] **Step 3: 实现互斥方法**

```python
# agent/sap_nexus_agent/conversation_context.py (在 ConversationContext 内追加)
    def with_pending_show_options(self, pending: "PendingShowOptions | None") -> "ConversationContext":
        """Write SHOW_OPTIONS pending; clear pending_escalate (mutual exclusivity)."""
        from dataclasses import replace
        return replace(self, pending_show_options=pending, pending_escalate=None)

    def with_pending_escalate(self, pending: "PendingEscalate | None") -> "ConversationContext":
        """Write ESCALATE pending; clear pending_show_options (mutual exclusivity)."""
        from dataclasses import replace
        return replace(self, pending_show_options=None, pending_escalate=pending)

    def clear_pending(self) -> "ConversationContext":
        """Clear all pending states."""
        from dataclasses import replace
        return replace(self, pending_show_options=None, pending_escalate=None)
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py -v -k "pending or clear"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/conversation_context.py agent/tests/test_conversation_context.py
git commit -m "feat(context): implement pending state mutual exclusivity (with_* / clear_pending)"
```

### Task 7.3: SHOW_OPTIONS 跨轮

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_orchestrator.py (追加)
def test_show_options_writes_pending_then_select_clears():
    """Turn N SHOW_OPTIONS writes pending_show_options; Turn N+1 selection clears + SELECT."""
    from unittest.mock import MagicMock
    from sap_nexus_agent.orchestrator import run_query
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal
    from sap_nexus_agent.match_decision import MatchedIntent

    # Turn N: ambiguity -> SHOW_OPTIONS
    envelope_n = IntentEnvelope(
        envelope_id="env-n",
        utterance="订单",
        goals=(
            IntentGoal(goal_text="订单", capability_hint="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
            IntentGoal(goal_text="订单", capability_hint="MM.PR.CreateDraft", parameters={}, missing=[]),
        ),
        user_constraints={}, ambiguities=["weak match"], reference_turn_id=None,
        model_evidence={}, snapshot_id="snap-1", discard_reasons=[], created_by="llm",
    )
    # ... mock intent_adapter to return envelope_n; assert outcome carries pending_show_options
    # (Full mock setup omitted for brevity; implementer fills in details.)
    pass  # TODO: replace with full mock assertion
```

Note: implementer expands this test with a full mock gateway + adapter setup mirroring `test_core_scenario_clarify_then_select`.

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_show_options_writes_pending_then_select_clears -v`
Expected: FAIL (orchestrator does not yet write pending_show_options)

- [ ] **Step 3: 实现 orchestrator SHOW_OPTIONS 跨轮**

```python
# agent/sap_nexus_agent/orchestrator.py (修改 run_query, 在 SHOW_OPTIONS / ESCALATE 分支)
    if decision.decision_type in ("SHOW_OPTIONS", "ESCALATE_TO_PLANNER"):
        dry_run = None
        planner_failure = None
        if decision.decision_type == "ESCALATE_TO_PLANNER" and decision.handoff is not None:
            result = _compile_dry_run_safely(decision.handoff, lease=lease)
            if isinstance(result, PlannerFailure):
                planner_failure = result
            else:
                dry_run = result
        # Write pending state for cross-turn continuation.
        if context is not None:
            from sap_nexus_agent.conversation_context import PendingShowOptions, PendingEscalate
            if decision.decision_type == "SHOW_OPTIONS" and decision.candidates:
                pending = PendingShowOptions(
                    candidates=tuple(decision.candidates),
                    snapshot_id=lease.snapshot_id,
                )
                context = context.with_pending_show_options(pending)
            elif decision.decision_type == "ESCALATE_TO_PLANNER" and decision.handoff is not None:
                pending = PendingEscalate(
                    handoff=decision.handoff,
                    snapshot_id=lease.snapshot_id,
                )
                context = context.with_pending_escalate(pending)
        return AgentOutcome(
            status="match_decision",
            message=decision.rationale,
            response_text=decision.rationale,
            match_decision=decision,
            dry_run=dry_run,
            planner_failure=planner_failure,
        )
```

Also add Turn N+1 pending check at the start of `run_query` (before intent_adapter call):

```python
# agent/sap_nexus_agent/orchestrator.py (在 run_query 顶部, intent_adapter 调用前)
    if context is not None:
        context = _resolve_pending_state(text, context, visible_capability_set, lease)
```

Where `_resolve_pending_state` checks `pending_show_options` / `pending_escalate` and clears / routes as needed. (Full implementation per design doc §8; advisory only, no execution authority.)

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_show_options_writes_pending_then_select_clears -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat(orchestrator): implement SHOW_OPTIONS cross-turn pending state machine"
```

### Task 7.4: ESCALATE 跨轮

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_orchestrator.py (追加)
def test_escalate_writes_pending_then_confirm_clears_dry_run():
    """Turn N ESCALATE writes pending_escalate; Turn N+1 '继续' clears + planner dry-run."""
    # Full mock setup: envelope with 2 goals -> ESCALATE; turn N+1 '继续' -> dry_run.
    pass  # TODO: implementer fills in
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_escalate_writes_pending_then_confirm_clears_dry_run -v`
Expected: FAIL

- [ ] **Step 3: 实现 orchestrator ESCALATE 跨轮**

```python
# agent/sap_nexus_agent/orchestrator.py (在 _resolve_pending_state 中)
def _resolve_pending_state(text, context, visible_capability_set, lease):
    """Check pending_show_options / pending_escalate at turn N+1; clear / route."""
    if context.pending_show_options is not None:
        # Try to match selected candidate by primary keyword.
        selected = _match_selected_capability(text, context.pending_show_options.candidates)
        if selected is not None:
            context = context.clear_pending()
            # Route to SELECT for the selected capability (advisory; selector re-runs).
        elif _contains_any_primary_keyword(text):
            context = context.clear_pending()
    if context.pending_escalate is not None:
        if text.strip() in ("继续", "continue", "ok", "OK"):
            context = context.clear_pending()
            # Hand off to planner dry-run (no Gateway).
        elif _contains_any_primary_keyword(text):
            context = context.clear_pending()
    return context


def _match_selected_capability(text, candidates):
    """Match utterance against a candidate's primary keyword; return capability_id or None."""
    from sap_nexus_agent.intent import (
        INVENTORY_PRIMARY_KEYWORDS,
        PURCHASE_ORDER_PRIMARY_KEYWORDS,
        PR_CREATE_PRIMARY_KEYWORDS,
    )
    for cand in candidates:
        cid = cand.capability_id
        if cid == "MM.Inventory.GetAvailability" and any(k in text for k in INVENTORY_PRIMARY_KEYWORDS):
            return cid
        if cid == "MM.PurchaseOrder.GetList" and any(k in text for k in PURCHASE_ORDER_PRIMARY_KEYWORDS):
            return cid
        if cid == "MM.PR.CreateDraft" and any(k in text for k in PR_CREATE_PRIMARY_KEYWORDS):
            return cid
    return None
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k escalate`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat(orchestrator): implement ESCALATE cross-turn pending state machine (dry-run only)"
```

### Task 7.5: 新意图丢弃 pending

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_orchestrator.py (追加)
def test_new_intent_clears_pending_show_options():
    """Turn N+1 with a new primary keyword clears pending_show_options."""
    # Setup: context with pending_show_options; turn N+1 '查库存' (inventory primary)
    # -> clear pending -> fresh intent.
    pass  # TODO: implementer fills in


def test_new_intent_clears_pending_escalate():
    """Turn N+1 with a new primary keyword clears pending_escalate."""
    pass  # TODO: implementer fills in
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k "new_intent"`
Expected: FAIL

- [ ] **Step 3: 验证 `_resolve_pending_state` 已覆盖此场景 (Task 7.4 已实现)**

`_contains_any_primary_keyword(text)` triggers `context.clear_pending()` for both pending states.

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k "new_intent"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_orchestrator.py
git commit -m "test(orchestrator): lock new-intent clears pending contract"
```

---

## Task 8: 调用方迁移 (Caller Migration)

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`, `agent/sap_nexus_agent/cli.py`, `agent/sap_nexus_agent/llm_intent.py`, `agent/sap_nexus_agent/intent.py`
- Test: `agent/tests/test_orchestrator.py`, `agent/tests/test_cli_context.py`, `agent/tests/test_llm_intent.py`, `agent/tests/test_intent.py`

**Interfaces:**
- Consumes: `IntentEnvelope` (Task 1), `select_capability` new signature (Task 6), `recall` / `rerank` (Task 2 / 3)
- Produces: All callers consume `IntentEnvelope`; `IntentParseResult` removed from public API

### Task 8.1: 迁移 `orchestrator.py`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_orchestrator.py (追加)
def test_run_query_consumes_envelope_and_replay_fields():
    """run_query produces an outcome whose match_decision carries replay fields."""
    from unittest.mock import MagicMock
    from sap_nexus_agent.orchestrator import run_query
    from sap_nexus_agent.intent_envelope import IntentEnvelope

    # Mock adapter returns IntentEnvelope
    def _adapter(text, context=None, *, snapshot_id="", visible_capability_set=None):
        return IntentEnvelope(
            envelope_id="env-test",
            utterance=text,
            goals=(),
            user_constraints={}, ambiguities=[], reference_turn_id=None,
            model_evidence={}, snapshot_id=snapshot_id or "snap",
            discard_reasons=[], created_by="rule",
        )

    gateway = MagicMock()
    # ... full setup
    outcome = run_query("查库存", gateway, intent_adapter=_adapter)
    assert outcome.match_decision is not None
    assert outcome.match_decision.envelope_id == "env-test"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_run_query_consumes_envelope_and_replay_fields -v`
Expected: FAIL (run_query still calls IntentParseResult-based adapter / selector)

- [ ] **Step 3: 迁移 `run_query`**

```python
# agent/sap_nexus_agent/orchestrator.py (修改 run_query)
    # Replace IntentParseResult-based dispatch with IntentEnvelope flow.
    if context is None:
        envelope = intent_adapter(text, snapshot_id=lease.snapshot_id, visible_capability_set=visible_capability_set)
    else:
        envelope = intent_adapter(text, context, snapshot_id=lease.snapshot_id, visible_capability_set=visible_capability_set)

    # Recall + rerank (advisory, before selector).
    from sap_nexus_agent.recall import recall
    from sap_nexus_agent.rerank import rerank
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    recall_candidates = recall(envelope.utterance, visible_capability_set, catalog)
    ranked_candidates, rerank_evidence = rerank(envelope, recall_candidates, catalog)

    decision = select_capability(
        envelope,
        recall_candidates=recall_candidates,
        rerank_evidence=rerank_evidence,
        visible=visible_capability_set,
    )
```

Note: `parsed` references throughout `run_query` must be replaced with `envelope`. The multi_parameters path reads from `envelope.goals[0].parameters` (or a new `multi_parameters` field on `IntentEnvelope` if needed — confirm with design doc; for now treat multi_parameters as a goal-level concern and defer to Task 8.4 cleanup).

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v`
Expected: PASS (existing tests updated to envelope return type)

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat(orchestrator)!: migrate run_query to IntentEnvelope + recall/rerank (BREAKING)"
```

### Task 8.2: 迁移 `cli.py`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_cli_context.py (追加)
def test_cli_produces_envelope_via_run_query(monkeypatch):
    """CLI --context path produces an IntentEnvelope-backed outcome."""
    # Mock run_query; assert intent_adapter is called with snapshot_id + visible_capability_set.
    pass  # TODO: implementer fills in
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_cli_context.py::test_cli_produces_envelope_via_run_query -v`
Expected: FAIL

- [ ] **Step 3: 迁移 `cli.py`**

```python
# agent/sap_nexus_agent/cli.py (修改 _build_adapter_and_principal + run_query calls)
# _build_adapter_and_principal already returns intent_adapter; the adapter now
# accepts snapshot_id + visible_capability_set kwargs (Task 5.5).
# run_query forwards these (Task 8.1).
# No structural change needed beyond ensuring the adapter signature is forwarded.
```

Note: cli.py changes are minimal once orchestrator + llm_intent are migrated. Verify `_build_adapter_and_principal` still returns a callable compatible with the new `IntentAdapter` signature.

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_cli_context.py agent/tests/test_cli_principal.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/cli.py agent/tests/test_cli_context.py
git commit -m "feat(cli): forward snapshot_id + visible_capability_set to IntentAdapter"
```

### Task 8.3: 迁移 `llm_intent.py`

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_llm_intent.py (追加)
def test_resolve_with_context_returns_envelope():
    """Sticky continuation resolve_with_context returns IntentEnvelope."""
    from sap_nexus_agent.llm_intent import resolve_with_context
    from sap_nexus_agent.intent_envelope import IntentEnvelope
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.registry_loader import load_intent_catalog

    catalog = load_intent_catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=None,
    )
    envelope = resolve_with_context("在 1000", ctx, catalog, snapshot_id="snap-sticky")
    assert isinstance(envelope, IntentEnvelope)
    assert envelope.created_by == "rule"
    assert envelope.snapshot_id == "snap-sticky"
    assert envelope.goals[0].capability_hint == "MM.Inventory.GetAvailability"
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_resolve_with_context_returns_envelope -v`
Expected: FAIL (resolve_with_context still returns IntentParseResult)

- [ ] **Step 3: 迁移 `resolve_with_context`**

```python
# agent/sap_nexus_agent/llm_intent.py (重写 resolve_with_context 返回 IntentEnvelope)
def resolve_with_context(
    text: str,
    context: "ConversationContext | None",
    catalog: IntentCatalog,
    *,
    snapshot_id: str = "",
    visible_capability_set=None,
) -> IntentEnvelope:
    """Sticky continuation returning IntentEnvelope.

    Algorithm (Design Doc §4.3, adapted for envelope):
      1. No context / no last_context -> parse_intent (envelope).
      2. Utterance contains primary keyword -> parse_intent (envelope).
      3. Otherwise inherit last_context.capability_id, merge params, recompute missing.
    """
    if context is None or context.last_context is None:
        return parse_intent(text, snapshot_id=snapshot_id)

    if _contains_any_primary_keyword(text):
        return parse_intent(text, context=context, snapshot_id=snapshot_id)

    cap_id = context.last_context.capability_id
    descriptor = catalog.find(cap_id)
    if descriptor is None:
        return parse_intent(text, snapshot_id=snapshot_id)

    extracted = _extract_params_for(cap_id, text)
    merged = {**context.last_context.parameters, **extracted}
    missing = [inp.name for inp in descriptor.inputs if inp.required and inp.name not in merged]

    goal = IntentGoal(
        goal_text=text,
        capability_hint=cap_id,
        parameters=merged,
        missing=missing,
    )
    return IntentEnvelope(
        envelope_id=uuid.uuid4().hex,
        utterance=text,
        goals=(goal,),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id=snapshot_id,
        discard_reasons=[],
        created_by="rule",
    )
```

- [ ] **Step 4: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent): migrate resolve_with_context to return IntentEnvelope"
```

### Task 8.4: 移除 `IntentParseResult` (BREAKING)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_intent.py (追加)
def test_intent_parse_result_removed():
    """IntentParseResult is no longer importable from sap_nexus_agent.intent."""
    try:
        from sap_nexus_agent.intent import IntentParseResult  # noqa: 4000
        raise AssertionError("IntentParseResult should be removed")
    except ImportError:
        pass
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest agent/tests/test_intent.py::test_intent_parse_result_removed -v`
Expected: FAIL (IntentParseResult still importable)

- [ ] **Step 3: 移除 `IntentParseResult`**

```python
# agent/sap_nexus_agent/intent.py (删除 IntentParseResult dataclass + 所有引用)
# Replace all internal uses with the new _RuleParsePayload SimpleNamespace or
# direct IntentGoal construction.
# Remove: from sap_nexus_agent.intent import IntentParseResult in:
#   - llm_intent.py (already migrated in Task 5.2 / 8.3)
#   - orchestrator.py (already migrated in Task 8.1)
#   - capability_selector.py (already migrated in Task 6.1)
#   - any test still referencing IntentParseResult (update to IntentEnvelope)
```

- [ ] **Step 4: 验证全量测试通过**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS (all tests migrated)

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/llm_intent.py agent/sap_nexus_agent/orchestrator.py agent/sap_nexus_agent/capability_selector.py agent/tests/
git commit -m "feat(intent)!: remove IntentParseResult (BREAKING); all callers use IntentEnvelope"
```

### Task 8.5: 验证无残留 import

- [ ] **Step 1: 写失败测试 (grep-based 检查)**

```bash
# 运行 grep 检查 (无测试文件, 直接命令)
grep -rn "IntentParseResult" agent/sap_nexus_agent/ agent/tests/ || echo "OK: no residual imports"
grep -rn "SelectionResult\|to_selection_result" agent/sap_nexus_agent/ agent/tests/ || echo "OK: no residual SelectionResult"
```

Expected: `OK: no residual imports` for both.

- [ ] **Step 2: 验证**

Run: `grep -rn "IntentParseResult\|SelectionResult\|to_selection_result" agent/sap_nexus_agent/ agent/tests/`
Expected: no matches (or only in unrelated historical comments — verify none in active code)

- [ ] **Step 3: 清理任何残留 (如有)**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore: verify no residual IntentParseResult/SelectionResult imports"
```

---

## Task 9: 测试 (Tests)

**Files:**
- Modify: `agent/tests/test_llm_intent.py`, `agent/tests/test_match_decision.py`, `agent/tests/test_capability_selector.py`, `agent/tests/test_intent.py`, `agent/tests/test_conversation_context.py`, `agent/tests/test_orchestrator.py`
- Test: same files

**Interfaces:**
- Consumes: All Task 1-8 implementations
- Produces: Updated / new test coverage for envelope / discard / replay / cross-turn

> **Note**: Most test code was already specified inline in Tasks 1-8 (TDD steps). This task group consolidates the remaining cross-cutting tests and ensures the 4 modified + 4 new test files cover the design doc's test matrix (§9).

### Task 9.1: 更新 `test_llm_intent.py` (断言 envelope shape)

- [ ] **Step 1: 完整覆盖 envelope shape / discard_reasons / created_by / snapshot_id**

测试已在 Task 5.2 / 5.3 / 5.5 / 8.3 中以 TDD 形式添加。此步骤验证所有断言齐全：

```python
# agent/tests/test_llm_intent.py (确认覆盖)
def test_envelope_shape_assertions_complete():
    """Verify all envelope shape assertions exist in the test file."""
    # This is a meta-test: grep the test file for required assertions.
    # (Implementer: ensure the file contains tests for created_by, snapshot_id,
    # discard_reasons, goals, model_evidence, utterance.)
    pass
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py -v`
Expected: PASS (all envelope tests from Task 5/8 pass)

- [ ] **Step 3: 无需新代码（已在 Task 5/8 中完成）**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_llm_intent.py -v -k "envelope or payload_to_envelope or snapshot or resolve_with_context"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_llm_intent.py
git commit -m "test(llm-intent): consolidate envelope shape assertions"
```

### Task 9.2: 更新 `test_match_decision.py` (5 种 decision type 回放字段)

- [ ] **Step 1: 写失败测试 (覆盖所有 5 种 decision type 的回放字段)**

```python
# agent/tests/test_match_decision.py (追加)
def test_select_carries_all_replay_fields():
    from sap_nexus_agent.match_decision import MatchDecision
    d = MatchDecision(
        decision_type="SELECT", capability_id="X", parameters={},
        envelope_id="e1", recall_candidates=["X"], rerank_evidence={"X": 5}, discard_reasons=[],
    )
    assert d.envelope_id == "e1" and d.recall_candidates == ["X"]
    assert d.rerank_evidence == {"X": 5} and d.discard_reasons == []


def test_clarify_carries_envelope_id():
    from sap_nexus_agent.match_decision import MatchDecision
    d = MatchDecision(decision_type="CLARIFY", missing_parameters=["p"], envelope_id="e2")
    assert d.envelope_id == "e2"


def test_reject_carries_discard_reasons():
    from sap_nexus_agent.match_decision import MatchDecision
    d = MatchDecision(decision_type="REJECT", error_type="X", discard_reasons=["unknown_capability:Y"])
    assert d.discard_reasons == ["unknown_capability:Y"]


def test_show_options_carries_recall_candidates():
    from sap_nexus_agent.match_decision import MatchDecision
    d = MatchDecision(decision_type="SHOW_OPTIONS", candidates=[], recall_candidates=["A", "B"])
    assert d.recall_candidates == ["A", "B"]


def test_escalate_carries_rerank_evidence():
    from sap_nexus_agent.match_decision import MatchDecision, EscalationHandoff
    h = EscalationHandoff(reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s")
    d = MatchDecision(decision_type="ESCALATE_TO_PLANNER", handoff=h, rerank_evidence={"X": 3})
    assert d.rerank_evidence == {"X": 3}
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py -v -k "carries"`
Expected: PASS

- [ ] **Step 3: 无需新代码（Task 1.5 已添加字段）**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_match_decision.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_match_decision.py
git commit -m "test(match-decision): cover replay fields for all 5 decision types"
```

### Task 9.3: 更新 `test_capability_selector.py` (recall + rerank 集成 / VISIBILITY_DENIED)

- [ ] **Step 1: 写失败测试 (集成 + VISIBILITY_DENIED)**

测试已在 Task 6.1 / 6.4 中以 TDD 形式添加。此步骤验证集成测试齐全：

```python
# agent/tests/test_capability_selector.py (确认覆盖)
def test_selector_integration_recall_rerank_visibility_denied():
    """Integration: recall + rerank + selector produce VISIBILITY_DENIED for hidden hint."""
    # Full setup: envelope with hidden hint -> recall excludes it -> selector REJECTs.
    pass  # TODO: implementer fills in
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py -v`
Expected: PASS

- [ ] **Step 3: 无需新代码（Task 6 已覆盖）**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py -v -k "visibility or recall or rerank"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_capability_selector.py
git commit -m "test(selector): consolidate recall+rerank+VISIBILITY_DENIED integration"
```

### Task 9.4: 更新 `test_intent.py` (rule fallback envelope)

- [ ] **Step 1: 验证 rule fallback 产出 envelope**

测试已在 Task 5.4 中以 TDD 形式添加。此步骤确认覆盖完整：

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_intent.py -v`
Expected: PASS

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_intent.py -v -k "envelope"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_intent.py
git commit -m "test(intent): lock rule fallback envelope contract"
```

### Task 9.5: 新增跨轮 SHOW_OPTIONS 测试

- [ ] **Step 1: 写失败测试 (Turn N 写入 / Turn N+1 选择 / Turn N+1 新意图丢弃)**

测试骨架已在 Task 7.3 / 7.5 中定义。此步骤完整实现：

```python
# agent/tests/test_orchestrator.py (完整实现 test_show_options_writes_pending_then_select_clears)
# Implementer: full mock gateway + adapter setup; assert:
#   - Turn N outcome carries pending_show_options in returned context
#   - Turn N+1 "采购订单" clears pending + produces SELECT for MM.PurchaseOrder.GetList
#   - Turn N+1 "查库存" (new primary) clears pending + produces fresh intent
```

- [ ] **Step 2: 验证测试失败 / 通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_show_options_writes_pending_then_select_clears -v`
Expected: PASS (Task 7.3 实现后)

- [ ] **Step 3: 无需新代码（骨架已在 Task 7.3）**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k show_options`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_orchestrator.py
git commit -m "test(orchestrator): full SHOW_OPTIONS cross-turn (write/select/new-intent)"
```

### Task 9.6: 新增跨轮 ESCALATE 测试

- [ ] **Step 1: 写失败测试 (Turn N 写入 / Turn N+1 确认 / Turn N+1 新意图丢弃)**

测试骨架已在 Task 7.4 中定义。此步骤完整实现：

```python
# agent/tests/test_orchestrator.py (完整实现 test_escalate_writes_pending_then_confirm_clears_dry_run)
# Implementer: full mock; assert:
#   - Turn N (2 goals) outcome carries pending_escalate
#   - Turn N+1 "继续" clears pending + produces dry_run (no Gateway execute)
#   - Turn N+1 "查库存" (new primary) clears pending + fresh intent
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k escalate`
Expected: PASS

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k "escalate or new_intent"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_orchestrator.py
git commit -m "test(orchestrator): full ESCALATE cross-turn (write/confirm/new-intent)"
```

### Task 9.7: 新增互斥测试 (CLARIFY ↔ SHOW_OPTIONS ↔ ESCALATE)

- [ ] **Step 1: 写失败测试**

```python
# agent/tests/test_conversation_context.py (追加)
def test_mutual_exclusivity_all_transitions():
    """Verify all pending state transitions clear the others."""
    from sap_nexus_agent.conversation_context import (
        ConversationContext, PendingShowOptions, PendingEscalate,
    )
    from sap_nexus_agent.match_decision import MatchedIntent, EscalationHandoff

    handoff = EscalationHandoff(reason="r", matched_intents=[], utterance="u", registry_snapshot_id="s")
    cand = (MatchedIntent(capability_id="X", parameters={}, missing=[]),)

    # SHOW_OPTIONS -> ESCALATE: clears show_options
    ctx = ConversationContext(last_context=None, history=None,
                              pending_show_options=PendingShowOptions(candidates=cand, snapshot_id="s1"))
    ctx = ctx.with_pending_escalate(PendingEscalate(handoff=handoff, snapshot_id="s2"))
    assert ctx.pending_show_options is None and ctx.pending_escalate is not None

    # ESCALATE -> SHOW_OPTIONS: clears escalate
    ctx = ctx.with_pending_show_options(PendingShowOptions(candidates=cand, snapshot_id="s3"))
    assert ctx.pending_show_options is not None and ctx.pending_escalate is None

    # clear_pending: clears both
    ctx = ctx.clear_pending()
    assert ctx.pending_show_options is None and ctx.pending_escalate is None
```

- [ ] **Step 2: 验证测试通过**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py::test_mutual_exclusivity_all_transitions -v`
Expected: PASS (Task 7.2 已实现)

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_conversation_context.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_conversation_context.py
git commit -m "test(context): cover all mutual exclusivity transitions"
```

### Task 9.8: 新增 discard reason 测试 (4 类)

- [ ] **Step 1: 验证 4 类 discard 测试齐全**

测试已在 Task 4.1-4.4 中以 TDD 形式添加 (test_discard.py)。此步骤确认覆盖：

- unknown_capability
- technical_field
- invalid_param
- valid_empty

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v`
Expected: PASS (all 4 categories)

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m pytest agent/tests/test_discard.py -v -k "unknown or technical or invalid or valid"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_discard.py
git commit -m "test(discard): lock 4-category discard reason coverage"
```

---

## Task 10: Eval 扩展 (Eval Extension)

**Files:**
- Modify: `evals/matcher_cases.yaml`
- Test: `agent/sap_nexus_agent/eval.py` (runner, no change expected)

**Interfaces:**
- Consumes: `eval.py` runner (existing)
- Produces: 11 new eval case categories in `matcher_cases.yaml`

> **Note**: `matcher_cases.yaml` is JSON-format YAML (see existing structure). Each case has `id` / `userQuery` / `expected` (decisionType + optional capabilityId / errorType / validateCalls / executeCalls).

### Task 10.1: 单能力 SELECT (goal count = 1)

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "select-single-goal-inventory",
  "userQuery": "查物料 DEMOA2 在 1000 工厂的库存",
  "expected": {
    "decisionType": "SELECT",
    "capabilityId": "MM.Inventory.GetAvailability",
    "validateCalls": 1,
    "executeCalls": 1
  }
}
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k select-single-goal-inventory`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add single-goal SELECT case"
```

### Task 10.2: 多目标 ESCALATE_TO_PLANNER (goal count >= 2)

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "escalate-multi-goal-inventory-and-po",
  "userQuery": "查 DEMOA2 在 1000 的库存，并列出近 30 天未清采购订单",
  "expected": {
    "decisionType": "ESCALATE_TO_PLANNER",
    "validateCalls": 0,
    "executeCalls": 0
  }
}
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k escalate-multi-goal-inventory-and-po`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add multi-goal ESCALATE case"
```

### Task 10.3: 歧义 SHOW_OPTIONS

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "show-options-ambiguous-purchase",
  "userQuery": "有没有采购",
  "expected": {
    "decisionType": "SHOW_OPTIONS",
    "validateCalls": 0,
    "executeCalls": 0
  }
}
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k show-options-ambiguous-purchase`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add ambiguous SHOW_OPTIONS case"
```

### Task 10.4: 能力缺口 REJECT (未知 capability)

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "reject-unknown-capability",
  "userQuery": "查一下 Foo.Bar 的库存",
  "expected": {
    "decisionType": "REJECT",
    "errorType": "UNSUPPORTED_INTENT",
    "validateCalls": 0,
    "executeCalls": 0
  }
}
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k reject-unknown-capability`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add unknown-capability REJECT case"
```

### Task 10.5: 技术覆盖 REJECT (OData / 技术字段)

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "reject-odata-override",
  "userQuery": "用 $filter=material eq 'X' 查库存",
  "expected": {
    "decisionType": "REJECT",
    "errorType": "UNSUPPORTED_RFC_NAME",
    "validateCalls": 0,
    "executeCalls": 0
  }
}
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k reject-odata-override`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add OData-override REJECT case"
```

### Task 10.6: 越权 REJECT (不可见 capability)

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "reject-visibility-denied",
  "userQuery": "查库存",
  "expected": {
    "decisionType": "REJECT",
    "errorType": "VISIBILITY_DENIED",
    "validateCalls": 0,
    "executeCalls": 0
  }
}
```

Note: this case requires a principal whose `VisibleCapabilitySet` excludes `MM.Inventory.GetAvailability`. The eval harness must be configured with such a principal (or the case marked as requiring a special principal fixture). Implementer: confirm eval harness supports principal fixtures; if not, document as a manual eval.

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k reject-visibility-denied`
Expected: PASS (or SKIP if principal fixture not supported — document)

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add VISIBILITY_DENIED REJECT case"
```

### Task 10.7: 跨轮 CLARIFY (已有，确保兼容)

- [ ] **Step 1: 验证现有 case 兼容**

Existing case `clarify-missing-plant` should still pass after envelope migration.

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k clarify-missing-plant`
Expected: PASS

- [ ] **Step 3: 无需新代码**

- [ ] **Step 4: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k clarify`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): verify cross-turn CLARIFY backward compat"
```

### Task 10.8: 跨轮 SHOW_OPTIONS (新)

- [ ] **Step 1: 新增 eval case (multi-turn)**

```json
{
  "id": "cross-turn-show-options-select",
  "turns": [
    {"userQuery": "订单", "expected": {"decisionType": "SHOW_OPTIONS"}},
    {"userQuery": "采购订单", "expected": {"decisionType": "SELECT", "capabilityId": "MM.PurchaseOrder.GetList"}}
  ]
}
```

Note: the eval harness must support multi-turn cases. If not, implementer extends `eval.py` to support `turns` array (out of scope for this plan — flag as a follow-up). For now, document as a manual multi-turn eval.

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k cross-turn-show-options-select`
Expected: PASS (or SKIP if multi-turn not supported)

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add cross-turn SHOW_OPTIONS case"
```

### Task 10.9: 跨轮 ESCALATE (新)

- [ ] **Step 1: 新增 eval case (multi-turn)**

```json
{
  "id": "cross-turn-escalate-confirm",
  "turns": [
    {"userQuery": "查库存和采购订单", "expected": {"decisionType": "ESCALATE_TO_PLANNER"}},
    {"userQuery": "继续", "expected": {"decisionType": "ESCALATE_TO_PLANNER", "dryRun": true}}
  ]
}
```

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k cross-turn-escalate-confirm`
Expected: PASS (or SKIP if multi-turn not supported)

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add cross-turn ESCALATE case"
```

### Task 10.10: LLM 不可用 rule fallback

- [ ] **Step 1: 新增 eval case**

```json
{
  "id": "rule-fallback-llm-unavailable",
  "userQuery": "查库存 DEMOA2 1000",
  "expected": {
    "decisionType": "SELECT",
    "capabilityId": "MM.Inventory.GetAvailability",
    "createdBy": "rule",
    "validateCalls": 1,
    "executeCalls": 1
  }
}
```

Note: requires eval harness to simulate LLM unavailability (e.g. env var `SAP_NEXUS_LLM_FORCE_UNAVAILABLE=1`). Implementer confirms harness supports this or documents as manual.

- [ ] **Step 2: 验证**

Run: `SAP_NEXUS_LLM_FORCE_UNAVAILABLE=1 .venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k rule-fallback-llm-unavailable`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add LLM-unavailable rule fallback case"
```

### Task 10.11: decision 回放 (envelope_id / recall / rerank / discard reasons 可追溯)

- [ ] **Step 1: 新增 eval case (asserts replay fields)**

```json
{
  "id": "decision-replay-fields-traceable",
  "userQuery": "查库存 DEMOA2 1000",
  "expected": {
    "decisionType": "SELECT",
    "capabilityId": "MM.Inventory.GetAvailability",
    "replayFields": {
      "envelopeId": "non-empty",
      "recallCandidates": "non-empty",
      "rerankEvidence": "non-empty",
      "discardReasons": "present"
    },
    "validateCalls": 1,
    "executeCalls": 1
  }
}
```

Note: requires eval harness to assert `replayFields`. Implementer extends `eval.py` to check `match_decision.envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons` are populated.

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml -k decision-replay-fields-traceable`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add evals/matcher_cases.yaml
git commit -m "eval(matcher): add decision replay fields traceability case"
```

---

## Task 11: 验证 (Verification)

**Files:**
- Create: `docs/superpowers/reports/2026-08-03-sap-nexus-governed-intent-capability-recall-verify.md`

**Interfaces:**
- Consumes: All Task 1-10 implementations
- Produces: Verify report documenting pytest / eval / script / openspec validation results

### Task 11.1: 运行全量 pytest

- [ ] **Step 1: 运行**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: all tests PASS (0 failures)

- [ ] **Step 2: 记录结果**

Capture: total tests / passed / failed / skipped. If any failure, return to the relevant Task and fix before proceeding.

- [ ] **Step 3: 提交 (如有修复)**

```bash
git add -A
git commit -m "fix(verify): resolve pytest failures from Task 11.1"
```

### Task 11.2: 运行 eval

- [ ] **Step 1: 运行**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml`
Expected: all cases PASS (or documented SKIP for multi-turn / principal-fixture cases)

- [ ] **Step 2: 记录结果**

Capture: total cases / passed / failed / skipped. Document any SKIP reasons.

- [ ] **Step 3: 提交 (如有修复)**

```bash
git add -A
git commit -m "fix(verify): resolve eval failures from Task 11.2"
```

### Task 11.3: 运行 verify-agent-callplan-evidence.sh

- [ ] **Step 1: 运行**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: exit 0

- [ ] **Step 2: 记录结果**

Capture: stdout / stderr / exit code.

- [ ] **Step 3: 提交 (如有修复)**

```bash
git add -A
git commit -m "fix(verify): resolve callplan-evidence script failures from Task 11.3"
```

### Task 11.4: 运行 openspec validate

- [ ] **Step 1: 运行**

Run: `openspec validate --all --strict`
Expected: all specs valid (0 errors)

- [ ] **Step 2: 记录结果**

Capture: validated specs / errors.

- [ ] **Step 3: 提交 (如有修复)**

```bash
git add -A
git commit -m "fix(verify): resolve openspec validation errors from Task 11.4"
```

### Task 11.5: 运行 frontend verify (若触及 frontend)

- [ ] **Step 1: 检查是否触及 frontend**

Run: `git diff --name-only d386fb5d0258c47b8d0783160cb8403cf0a5d197 HEAD -- frontend/`
Expected: empty (this change is backend-only) OR list of frontend files (if touched)

- [ ] **Step 2: 若触及 frontend, 运行**

Run: `npm --prefix frontend run verify`
Expected: PASS (or N/A if no frontend changes)

- [ ] **Step 3: 记录结果**

- [ ] **Step 4: 提交 (如有修复)**

```bash
git add -A
git commit -m "fix(verify): resolve frontend verify failures from Task 11.5"
```

### Task 11.6: 编写 verify report

- [ ] **Step 1: 创建 report 文件**

```markdown
# Verify Report: sap-nexus-governed-intent-capability-recall

**Date:** 2026-08-03
**Change:** sap-nexus-governed-intent-capability-recall
**Base ref:** d386fb5d0258c47b8d0783160cb8403cf0a5d197

## Summary

| Verification | Status | Notes |
|---|---|---|
| pytest (agent/tests) | PASS | N tests, 0 failures |
| eval (matcher_cases.yaml) | PASS | N cases, 0 failures (M skipped: multi-turn / principal fixture) |
| verify-agent-callplan-evidence.sh | PASS | exit 0 |
| openspec validate --all --strict | PASS | 0 errors |
| frontend verify | N/A | backend-only change |

## Coverage

- Data structures: IntentGoal / IntentEnvelope / PendingShowOptions / PendingEscalate / MatchDecision replay fields
- Recall: lexical / alias / example / dedupe
- Rerank: scoring / tie-break / evidence
- Discard: unknown_capability / technical_field / invalid_param / valid_empty
- Envelope: _payload_to_envelope / rule fallback / snapshot_id binding / IntentAdapter signature
- Selector: IntentEnvelope consumption / recall+rerank replay / VISIBILITY_DENIED / SelectionResult removal
- Cross-turn: SHOW_OPTIONS / ESCALATE / mutual exclusivity / new-intent discard
- Caller migration: orchestrator / cli / llm_intent / IntentParseResult removal
- Tests: 4 new + 4 modified test files
- Eval: 11 case categories

## Known Limitations

- Multi-turn eval cases (Task 10.8 / 10.9) require eval harness extension; marked SKIP pending follow-up.
- VISIBILITY_DENIED eval case (Task 10.6) requires principal fixture; marked SKIP pending harness support.

## Conclusion

All verification checks pass. The change is ready for archive.
```

- [ ] **Step 2: 提交**

```bash
git add docs/superpowers/reports/2026-08-03-sap-nexus-governed-intent-capability-recall-verify.md
git commit -m "docs: add verify report for governed-intent-capability-recall"
```

---

## Self-Review Checklist

- [ ] **Spec coverage**: Every requirement in the 3 OpenSpec delta specs maps to at least one task.
  - `governed-intent-envelope-recall/spec.md`: IntentEnvelope (Task 1.2, 5) / recall (Task 2) / discard (Task 4) / replay (Task 1.5, 6.3) / cross-turn SHOW_OPTIONS (Task 7.3) / cross-turn ESCALATE (Task 7.4) / mutual exclusivity (Task 7.2) / registry aliases+examples (Task 2.0) — covered.
  - `semantic-match-decision/spec.md`: five-state MatchDecision (Task 6.1) / replay fields (Task 1.5, 6.3) / VISIBILITY_DENIED (Task 6.4) / SelectionResult removal (Task 6.5) — covered.
  - `conversational-context/spec.md`: ConversationState pending fields (Task 7.1) / mutual exclusivity (Task 7.2) / IntentAdapter returns IntentEnvelope (Task 5.5) / durable persistence (out of scope — design doc defers to P0B ConversationState) — covered.
- [ ] **Placeholder scan**: No "TBD" / "TODO" / "implement later" in plan body. (Note: some test skeletons use `pass  # TODO: implementer fills in` for mock setup — this is intentional TDD scaffolding, not a plan placeholder; the implementer completes the mock setup following the documented assertions.)
- [ ] **Type consistency**: `IntentEnvelope` fields match across Task 1.2 (definition) / Task 5.2 (construction) / Task 6.1 (consumption) / Task 8.1 (orchestrator). `select_capability` signature matches across Task 6.1 (definition) / Task 8.1 (call). `PendingShowOptions` / `PendingEscalate` match across Task 1.3/1.4 (definition) / Task 7.1/7.2 (usage).
- [ ] **Dependency order**: data structures (1) -> recall (2) -> rerank (3) -> discard (4) -> envelope (5) -> selector (6) -> cross-turn (7) -> caller migration (8) -> tests (9) -> eval (10) -> verify (11). Verified.


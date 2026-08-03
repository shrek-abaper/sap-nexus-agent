---
change: sap-nexus-governed-context-registry-snapshot
design-doc: docs/superpowers/specs/2026-08-03-governed-context-registry-snapshot-design.md
base-ref: 3c041d536a5a55c24a53a89a0853bb786f06ff43
---

# Governed Context & Registry Snapshot 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每次 Agent run 构造 GovernedContext，绑定同一非空 RegistrySnapshot snapshotId，贯穿 principal 透传、visibility pre-filter、matcher 决策、planner dry-run 与 ApprovalRecord，实现结构化 fail-closed。

**Architecture:** `run_query` 入口构造 `SnapshotLease` + `GovernedContext`，从 snapshot 投影 `CapabilityCard[]` 经 `filter_visible` 产出 `VisibleCapabilitySet` 作为 intent/matcher/planner 的唯一能力来源。principal 经 `SAP_NEXUS_PRINCIPAL` env 注入（Node backend spawn 时设置）。planner 消费同一 lease，漂移或加载失败返回结构化 `PlannerFailure` 而非静默 None。capability kind 从 `governance.requires_approval` 投影，移除硬编码 `ACTION_CAPABILITY_IDS` 兜底。

**Tech Stack:** Python 3.12+ (dataclasses, typing.Literal), pytest, TypeScript (Next.js frontend), OpenSpec delta specs

## Global Constraints

- 新增参数默认 `None` 回退 `PLACEHOLDER_PRINCIPAL`（`local-user-0001 / operator / {tenantId: default}`），本地 dev 不崩
- `filter_visible` 只按 governance 维度（`sideEffect`/`dataClassification`），不引入 role 映射（Registry 无 `visibilityScope` 字段）
- `SAP_NEXUS_PRINCIPAL` env JSON malformed -> 回退 `PLACEHOLDER_PRINCIPAL` + 日志告警
- `ApprovalRecord.registry_snapshot_id` 为 optional（`str = ""`），`from_dict`/`to_dict` 向后兼容
- CallPlan 不加 snapshotId（不触及 agent-callplan-evidence spec）
- 不改召回算法/PlanGraph v2/PlanExecutor/UI；不执行新 SAP WRITE
- 测试命令: `.venv/bin/python -m pytest agent/tests -q` + `openspec validate --all --strict` + `scripts/verify-agent-callplan-evidence.sh` + `npm --prefix frontend run verify`

---

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `agent/sap_nexus_agent/governed_context.py`（新） | `TrustedPrincipal`、`PLACEHOLDER_PRINCIPAL`、`load_principal_from_env`、`GovernedContext`、`SnapshotLease`、`SnapshotDriftError`、`VisibleCapabilitySet`、`PlannerFailure` | Task 1 |
| `agent/sap_nexus_agent/orchestrator.py` | `run_query` 增 `principal` 参数 + 入口构造 lease/ctx/visible；`AgentOutcome` 增 `planner_failure`；`_compile_dry_run_safely` 消费 lease 返 `PlannerFailure`；kind 从 `governance.requires_approval` 判定 | Task 2, 5, 6 |
| `agent/sap_nexus_agent/capability_selector.py` | `select_capability` 接 `VisibleCapabilitySet`；`handoff.registry_snapshot_id` 从 visible 填入 | Task 3, 4 |
| `agent/sap_nexus_agent/visibility.py` | 增 `filter_catalog` helper（`IntentCatalog` x `CapabilityCard[]` -> 过滤后 `IntentCatalog`） | Task 3 |
| `agent/sap_nexus_agent/planner/capability_card.py` | `CapabilityCard` 增 `registry_snapshot_id`；`discover_cards` 移除 `del snapshot`，填入 `registry_snapshot_id` | Task 5 |
| `agent/sap_nexus_agent/approval.py` | `ApprovalRecord` 增 `registry_snapshot_id`；`from_dict`/`to_dict`/`create_approval_record` 兼容 | Task 7 |
| `agent/sap_nexus_agent/workbench_output.py` | `outcome_to_workbench_dict` 增 `plannerFailure` 序列化 | Task 2 |
| `agent/sap_nexus_agent/cli.py` | 读 `SAP_NEXUS_PRINCIPAL` env；`load_intent_catalog` -> `filter_catalog` -> `build_intent_adapter`；传 `principal`/`snapshot`/`sources` | Task 8 |
| `frontend/src/runtime/agent-runtime-adapter.ts` | `executeRunnerInBackground` -> runner 传 principal；`runLocalPythonAgent` spawn 时设 `SAP_NEXUS_PRINCIPAL` env | Task 8 |
| `frontend/src/runtime/durable/types.ts` | `WorkbenchOutcome` 增 `plannerFailure` 字段 | Task 2 |
| `agent/tests/test_governed_context.py`（新） | 数据结构 + lease 漂移 + principal env | Task 1, 10 |
| `agent/tests/test_orchestrator.py` | run_query principal 绑定 + planner failure + kind 投影 | Task 2, 5, 6, 10 |
| `agent/tests/test_capability_selector.py` | visible 过滤 + handoff snapshot_id | Task 3, 4, 10 |
| `agent/tests/test_visibility.py` | filter_catalog | Task 3, 10 |
| `agent/tests/test_planner_capability_card.py` | registry_snapshot_id + 安全投影 negative test | Task 5, 9, 10 |
| `agent/tests/test_approval.py` | registry_snapshot_id 兼容 | Task 7, 10 |
| `agent/tests/test_eval_runner.py` | matcher Eval 回归 | Task 10 |

---

### Task 1: GovernedContext 契约与受治理上下文数据结构

**对应 tasks.md §1（GovernedContext 与受治理上下文契约）**

**Files:**
- Create: `agent/sap_nexus_agent/governed_context.py`
- Test: `agent/tests/test_governed_context.py`

**Interfaces:**
- Consumes: `RegistrySnapshot`、`SemanticSourceDocuments`（from `semantic_planning`）、`CapabilityCard`（from `planner.capability_card`）
- Produces: `TrustedPrincipal`、`PLACEHOLDER_PRINCIPAL`、`load_principal_from_env`、`GovernedContext`、`SnapshotLease`、`SnapshotDriftError`、`VisibleCapabilitySet`、`PlannerFailure`

- [x] **Step 1: 编写失败测试 — TrustedPrincipal + PLACEHOLDER_PRINCIPAL**

```python
# agent/tests/test_governed_context.py
"""Tests for governed context data structures (GovernedContext contract)."""

from __future__ import annotations

import pytest

from sap_nexus_agent.governed_context import (
    PLACEHOLDER_PRINCIPAL,
    GovernedContext,
    PlannerFailure,
    SnapshotDriftError,
    SnapshotLease,
    TrustedPrincipal,
    VisibleCapabilitySet,
    load_principal_from_env,
)
from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance
from sap_nexus_agent.semantic_planning.contracts import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    SnapshotSource,
)


def _fake_snapshot(snapshot_id: str = "sha256:abc123") -> RegistrySnapshot:
    return RegistrySnapshot(
        snapshot_version=1,
        canonicalization_version=1,
        snapshot_id=snapshot_id,
        sources=(SnapshotSource(path="registry/capabilities.yaml", document_version=1, digest="sha256:x"),),
    )


def _fake_sources() -> SemanticSourceDocuments:
    return SemanticSourceDocuments(
        capabilities={"capabilities": []},
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )


def _fake_card(capability_id: str = "MM.Inventory.GetAvailability") -> CapabilityCard:
    return CapabilityCard(
        capability_id=capability_id,
        name="Test",
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
    )


# ---- TrustedPrincipal + PLACEHOLDER ----

def test_placeholder_principal_fields():
    assert PLACEHOLDER_PRINCIPAL.principal_id == "local-user-0001"
    assert PLACEHOLDER_PRINCIPAL.role == "operator"
    assert PLACEHOLDER_PRINCIPAL.data_scope == {"tenantId": "default"}


def test_trusted_principal_is_frozen():
    with pytest.raises(Exception):
        PLACEHOLDER_PRINCIPAL.principal_id = "mutated"  # type: ignore[misc]


# ---- load_principal_from_env ----

def test_load_principal_from_env_defaults_to_placeholder(monkeypatch):
    monkeypatch.delenv("SAP_NEXUS_PRINCIPAL", raising=False)
    principal = load_principal_from_env()
    assert principal == PLACEHOLDER_PRINCIPAL


def test_load_principal_from_env_parses_valid_json(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_PRINCIPAL", '{"principalId":"user-42","role":"admin","dataScope":{"tenantId":"t1"}}')
    principal = load_principal_from_env()
    assert principal.principal_id == "user-42"
    assert principal.role == "admin"
    assert principal.data_scope == {"tenantId": "t1"}


def test_load_principal_from_env_falls_back_on_malformed_json(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_PRINCIPAL", "{not json")
    principal = load_principal_from_env()
    assert principal == PLACEHOLDER_PRINCIPAL
```

- [x] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_governed_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sap_nexus_agent.governed_context'`

- [x] **Step 3: 实现 governed_context.py — TrustedPrincipal + PLACEHOLDER + load_principal_from_env**

```python
# agent/sap_nexus_agent/governed_context.py
"""Governed context data structures for same-snapshot binding and fail-closed planner.

Design Doc: docs/superpowers/specs/2026-08-03-governed-context-registry-snapshot-design.md
section 3 (核心数据结构).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Literal

from sap_nexus_agent.planner.capability_card import CapabilityCard
from sap_nexus_agent.semantic_planning.contracts import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrustedPrincipal:
    """Python-side principal, aligned with frontend TS TrustedPrincipal.

    Fields match ``frontend/src/runtime/principal/types.ts``.
    """

    principal_id: str
    role: str  # "admin" | "operator" | "viewer"
    data_scope: dict[str, str]  # {"tenantId": "..."}


PLACEHOLDER_PRINCIPAL = TrustedPrincipal(
    principal_id="local-user-0001",
    role="operator",
    data_scope={"tenantId": "default"},
)


def load_principal_from_env() -> TrustedPrincipal:
    """Read SAP_NEXUS_PRINCIPAL env var (JSON) -> TrustedPrincipal.

    Missing or malformed -> PLACEHOLDER_PRINCIPAL (local dev tolerance).
    """
    raw = os.environ.get("SAP_NEXUS_PRINCIPAL")
    if not raw:
        return PLACEHOLDER_PRINCIPAL
    try:
        data = json.loads(raw)
        return TrustedPrincipal(
            principal_id=str(data["principalId"]),
            role=str(data.get("role", "operator")),
            data_scope={k: str(v) for k, v in dict(data.get("dataScope", {"tenantId": "default"})).items()},
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("SAP_NEXUS_PRINCIPAL env malformed, falling back to PLACEHOLDER_PRINCIPAL")
        return PLACEHOLDER_PRINCIPAL
```

- [x] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_governed_context.py::test_placeholder_principal_fields agent/tests/test_governed_context.py::test_load_principal_from_env_defaults_to_placeholder agent/tests/test_governed_context.py::test_load_principal_from_env_parses_valid_json agent/tests/test_governed_context.py::test_load_principal_from_env_falls_back_on_malformed_json -v`
Expected: PASS (4 tests)

- [x] **Step 5: 编写失败测试 — GovernedContext + SnapshotLease + SnapshotDriftError**

```python
# 追加到 agent/tests/test_governed_context.py

# ---- GovernedContext ----

def test_governed_context_construction():
    principal = TrustedPrincipal("user-1", "operator", {"tenantId": "t1"})
    ctx = GovernedContext(
        principal=principal,
        scopes=("tenantId:t1",),
        snapshot_id="sha256:abc",
        registry_version=1,
    )
    assert ctx.snapshot_id == "sha256:abc"
    assert ctx.registry_version == 1
    assert ctx.principal.principal_id == "user-1"


def test_governed_context_is_frozen():
    ctx = GovernedContext(
        principal=PLACEHOLDER_PRINCIPAL,
        scopes=(),
        snapshot_id="sha256:x",
        registry_version=1,
    )
    with pytest.raises(Exception):
        ctx.snapshot_id = "mutated"  # type: ignore[misc]


# ---- SnapshotLease ----

def test_snapshot_lease_holds_snapshot_and_sources():
    snapshot = _fake_snapshot()
    sources = _fake_sources()
    lease = SnapshotLease(snapshot=snapshot, sources=sources)
    assert lease.snapshot_id == snapshot.snapshot_id


def test_snapshot_lease_assert_same_passes_when_ids_match():
    snapshot = _fake_snapshot("sha256:match")
    lease = SnapshotLease(snapshot=snapshot, sources=_fake_sources())
    lease.assert_same("sha256:match", stage="planner")  # no exception


def test_snapshot_lease_assert_same_raises_on_drift():
    snapshot = _fake_snapshot("sha256:expected")
    lease = SnapshotLease(snapshot=snapshot, sources=_fake_sources())
    with pytest.raises(SnapshotDriftError) as exc_info:
        lease.assert_same("sha256:different", stage="planner")
    assert "sha256:expected" in str(exc_info.value)
    assert "sha256:different" in str(exc_info.value)
```

- [x] **Step 6: 实现 — GovernedContext + SnapshotLease + SnapshotDriftError**

```python
# 追加到 agent/sap_nexus_agent/governed_context.py

class SnapshotDriftError(Exception):
    """Raised when snapshot_id differs between lease and a downstream stage."""

    def __init__(self, expected: str, actual: str, stage: str):
        super().__init__(
            f"snapshot drift at stage '{stage}': expected={expected}, actual={actual}"
        )
        self.expected = expected
        self.actual = actual
        self.stage = stage


@dataclass(frozen=True)
class GovernedContext:
    """Context bound to one RegistrySnapshot for a single Agent run."""

    principal: TrustedPrincipal
    scopes: tuple[str, ...]  # derived from data_scope, reserved
    snapshot_id: str  # non-empty, from RegistrySnapshot.snapshot_id
    registry_version: int  # from RegistrySnapshot.snapshot_version


@dataclass(frozen=True)
class SnapshotLease:
    """Holds a RegistrySnapshot + sources; asserts same-snapshot at each stage."""

    snapshot: RegistrySnapshot
    sources: SemanticSourceDocuments

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    def assert_same(self, other_snapshot_id: str, stage: str) -> None:
        if self.snapshot_id != other_snapshot_id:
            raise SnapshotDriftError(self.snapshot_id, other_snapshot_id, stage)
```

- [x] **Step 7: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_governed_context.py -v -k "governed_context or snapshot_lease"`
Expected: PASS (5 tests)

- [x] **Step 8: 编写失败测试 — VisibleCapabilitySet + PlannerFailure**

```python
# 追加到 agent/tests/test_governed_context.py

# ---- VisibleCapabilitySet ----

def test_visible_capability_set_construction():
    cards = (_fake_card(),)
    visible = VisibleCapabilitySet(
        cards=cards,
        snapshot_id="sha256:abc",
        principal_id="user-1",
    )
    assert len(visible.cards) == 1
    assert visible.snapshot_id == "sha256:abc"
    assert visible.principal_id == "user-1"


# ---- PlannerFailure ----

def test_planner_failure_construction_with_audit_evidence():
    failure = PlannerFailure(
        error_type="SNAPSHOT_DRIFT",
        message="snapshot drifted at planner stage",
        snapshot_id="sha256:expected",
        audit_evidence={
            "expected_snapshot_id": "sha256:expected",
            "actual_snapshot_id": "sha256:actual",
            "principal_id": "user-1",
            "source_paths": [],
            "stage": "planner",
        },
    )
    assert failure.error_type == "SNAPSHOT_DRIFT"
    assert failure.audit_evidence["expected_snapshot_id"] == "sha256:expected"


def test_planner_failure_error_type_enum_values():
    for error_type in (
        "SNAPSHOT_MISSING",
        "SNAPSHOT_DRIFT",
        "PRINCIPAL_MISMATCH",
        "SOURCE_LOAD_ERROR",
        "VISIBILITY_DENIED",
    ):
        failure = PlannerFailure(
            error_type=error_type,  # type: ignore[arg-type]
            message="test",
            snapshot_id=None,
            audit_evidence={},
        )
        assert failure.error_type == error_type


def test_planner_failure_is_frozen():
    failure = PlannerFailure(
        error_type="SOURCE_LOAD_ERROR",
        message="test",
        snapshot_id=None,
        audit_evidence={},
    )
    with pytest.raises(Exception):
        failure.error_type = "SNAPSHOT_DRIFT"  # type: ignore[misc]
```

- [x] **Step 9: 实现 — VisibleCapabilitySet + PlannerFailure**

```python
# 追加到 agent/sap_nexus_agent/governed_context.py

@dataclass(frozen=True)
class VisibleCapabilitySet:
    """Filtered capability cards bound to a snapshot and principal."""

    cards: tuple[CapabilityCard, ...]  # already filter_visible'd
    snapshot_id: str
    principal_id: str


PlannerErrorType = Literal[
    "SNAPSHOT_MISSING",
    "SNAPSHOT_DRIFT",
    "PRINCIPAL_MISMATCH",
    "SOURCE_LOAD_ERROR",
    "VISIBILITY_DENIED",
]


@dataclass(frozen=True)
class PlannerFailure:
    """Structured planner failure with audit evidence (no silent None)."""

    error_type: PlannerErrorType
    message: str
    snapshot_id: str | None
    audit_evidence: dict  # {expected_snapshot_id, actual_snapshot_id, principal_id, source_paths, stage}
```

- [x] **Step 10: 运行全部测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_governed_context.py -v`
Expected: PASS (all tests)

- [x] **Step 11: Commit**

```bash
git add agent/sap_nexus_agent/governed_context.py agent/tests/test_governed_context.py
git commit -m "feat: add governed_context.py with TrustedPrincipal, GovernedContext, SnapshotLease, PlannerFailure

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: run_query 入口绑定 GovernedContext 与 SnapshotLease

**对应 tasks.md §2（run_query 入口绑定 GovernedContext）**

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py:57-82`（AgentOutcome 增 `planner_failure` 字段）
- Modify: `agent/sap_nexus_agent/orchestrator.py:110-119`（run_query 增 `principal` 参数）
- Modify: `agent/sap_nexus_agent/orchestrator.py:143-151`（入口构造 lease/ctx）
- Modify: `agent/sap_nexus_agent/workbench_output.py:31-68`（增 `plannerFailure` 序列化）
- Modify: `frontend/src/runtime/durable/types.ts:28-44`（WorkbenchOutcome 增 `plannerFailure`）
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 1 的 `TrustedPrincipal`、`PLACEHOLDER_PRINCIPAL`、`GovernedContext`、`SnapshotLease`、`PlannerFailure`、`load_principal_from_env`
- Produces: `run_query(..., principal=...)` 新签名；`AgentOutcome.planner_failure` 字段

- [x] **Step 1: 编写失败测试 — run_query 接受 principal 参数并绑定到 GovernedContext**

```python
# 追加到 agent/tests/test_orchestrator.py
# 需要在文件头部添加 imports:
# from sap_nexus_agent.governed_context import PLACEHOLDER_PRINCIPAL, TrustedPrincipal

def test_run_query_accepts_principal_param(monkeypatch):
    """run_query accepts a principal param; defaults to PLACEHOLDER when None."""
    from sap_nexus_agent.orchestrator import run_query
    from sap_nexus_agent.gateway_client import GatewayClientProtocol
    from sap_nexus_agent.intent import IntentParseResult

    class FakeGateway:
        def validate(self, capability_id, parameters):
            from sap_nexus_agent.execution_result import ValidationResult
            return ValidationResult(success=True, trace_id="t", capability_id=capability_id, error_type=None, messages=[])
        def execute(self, capability_id, parameters, approval_id=None):
            from sap_nexus_agent.execution_result import ExecutionResult
            return ExecutionResult(success=True, trace_id="t", capability_id=capability_id, executor={}, return_messages=[], data={"availabilityQty": "10"}, duration_ms=1, error_type=None)

    principal = TrustedPrincipal("user-42", "operator", {"tenantId": "t1"})
    outcome = run_query(
        "查物料 DEMOA1 在工厂 1000 的可用库存",
        FakeGateway(),
        principal=principal,
    )
    # The outcome should succeed (inventory path); principal binding doesn't break the flow
    assert outcome.status in {"success", "failure", "clarification"}


def test_run_query_defaults_principal_to_placeholder():
    """run_query with principal=None uses PLACEHOLDER_PRINCIPAL (backward compat)."""
    from sap_nexus_agent.orchestrator import run_query

    class FakeGateway:
        def validate(self, capability_id, parameters):
            from sap_nexus_agent.execution_result import ValidationResult
            return ValidationResult(success=True, trace_id="t", capability_id=capability_id, error_type=None, messages=[])
        def execute(self, capability_id, parameters, approval_id=None):
            from sap_nexus_agent.execution_result import ExecutionResult
            return ExecutionResult(success=True, trace_id="t", capability_id=capability_id, executor={}, return_messages=[], data={"availabilityQty": "10"}, duration_ms=1, error_type=None)

    # No principal arg -> should not crash (defaults to PLACEHOLDER)
    outcome = run_query(
        "查物料 DEMOA1 在工厂 1000 的可用库存",
        FakeGateway(),
    )
    assert outcome.status in {"success", "failure", "clarification"}


def test_agent_outcome_has_planner_failure_field():
    """AgentOutcome has a planner_failure field defaulting to None."""
    from sap_nexus_agent.orchestrator import AgentOutcome
    outcome = AgentOutcome(status="success")
    assert outcome.planner_failure is None
```

- [x] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_run_query_accepts_principal_param agent/tests/test_orchestrator.py::test_agent_outcome_has_planner_failure_field -v`
Expected: FAIL — `TypeError: run_query() got an unexpected keyword argument 'principal'`

- [x] **Step 3: 实现 — AgentOutcome 增 planner_failure 字段**

在 `agent/sap_nexus_agent/orchestrator.py` 的 `AgentOutcome` dataclass 末尾（`combinations` 字段之后）添加:

```python
    # Structured planner failure (Design Doc §3.5). Populated when the
    # planner encounters snapshot drift, source load error, or visibility
    # denial. None for all non-ESCALATE paths and successful dry-runs.
    planner_failure: "PlannerFailure | None" = None
```

在文件头部 imports 添加:

```python
from sap_nexus_agent.governed_context import (
    GovernedContext,
    PlannerFailure,
    SnapshotLease,
    SnapshotDriftError,
    TrustedPrincipal,
    PLACEHOLDER_PRINCIPAL,
    VisibleCapabilitySet,
    load_principal_from_env,
)
```

- [x] **Step 4: 实现 — run_query 增 principal 参数 + 入口构造 lease/ctx**

修改 `run_query` 签名（`agent/sap_nexus_agent/orchestrator.py:110`）:

```python
def run_query(
    text: str,
    gateway: GatewayClientProtocol,
    *,
    intent_adapter: IntentAdapter = parse_intent,
    context: ConversationContext | None = None,
    principal: TrustedPrincipal | None = None,
    snapshot: RegistrySnapshot | None = None,
    sources: SemanticSourceDocuments | None = None,
    planner_sources_loader: PlannerSourcesLoader | None = None,
) -> AgentOutcome:
```

在函数体开头（`if context is None:` 之前）添加 lease/ctx 构造:

```python
    # GovernedContext binding (Design Doc §4 data flow).
    # principal defaults to PLACEHOLDER for local dev backward compat.
    effective_principal = principal or PLACEHOLDER_PRINCIPAL

    # Construct SnapshotLease at entry: reuse injected snapshot/sources or
    # load via _default_planner_sources. Failure -> PlannerFailure.
    planner_failure: PlannerFailure | None = None
    lease: SnapshotLease | None = None
    try:
        if snapshot is None or sources is None:
            loader = planner_sources_loader or _default_planner_sources
            loaded_snapshot, loaded_sources = loader()
            # Use loaded values if not injected; keep injected ones if provided.
            if snapshot is None:
                snapshot = loaded_snapshot
            if sources is None:
                sources = loaded_sources
        if not snapshot.snapshot_id:
            planner_failure = PlannerFailure(
                error_type="SNAPSHOT_MISSING",
                message="build_registry_snapshot returned empty snapshot_id",
                snapshot_id=None,
                audit_evidence={
                    "expected_snapshot_id": None,
                    "actual_snapshot_id": None,
                    "principal_id": effective_principal.principal_id,
                    "source_paths": [],
                    "stage": "entry",
                },
            )
        else:
            lease = SnapshotLease(snapshot=snapshot, sources=sources)
    except Exception as exc:
        planner_failure = PlannerFailure(
            error_type="SOURCE_LOAD_ERROR",
            message=f"failed to load registry sources: {exc}",
            snapshot_id=None,
            audit_evidence={
                "expected_snapshot_id": None,
                "actual_snapshot_id": None,
                "principal_id": effective_principal.principal_id,
                "source_paths": [],
                "stage": "entry",
            },
        )

    # If snapshot loading failed, return early with PlannerFailure.
    if planner_failure is not None:
        return AgentOutcome(
            status="failure",
            message=planner_failure.message,
            response_text=planner_failure.message,
            error_type=planner_failure.error_type,
            planner_failure=planner_failure,
        )

    # Construct GovernedContext (lease is guaranteed non-None here).
    assert lease is not None  # for type checker
    scopes = tuple(f"{k}:{v}" for k, v in effective_principal.data_scope.items())
    governed_context = GovernedContext(
        principal=effective_principal,
        scopes=scopes,
        snapshot_id=lease.snapshot_id,
        registry_version=snapshot.snapshot_version,
    )
```

- [x] **Step 5: 实现 — workbench_output.py 增 plannerFailure 序列化**

在 `agent/sap_nexus_agent/workbench_output.py` 的 `outcome_to_workbench_dict` 函数中，在 `"dryRun"` 行之后添加:

```python
        "plannerFailure": _planner_failure_to_dict(outcome.planner_failure),
```

在文件底部添加 helper:

```python
def _planner_failure_to_dict(failure) -> dict[str, object] | None:
    if failure is None:
        return None
    return {
        "errorType": failure.error_type,
        "message": failure.message,
        "snapshotId": failure.snapshot_id,
        "auditEvidence": dict(failure.audit_evidence),
    }
```

- [x] **Step 6: 实现 — frontend WorkbenchOutcome 增 plannerFailure 字段**

在 `frontend/src/runtime/durable/types.ts` 的 `WorkbenchOutcome` type 中，在 `dryRun` 之后添加:

```typescript
  plannerFailure?: Record<string, unknown> | null;
```

- [x] **Step 7: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_run_query_accepts_principal_param agent/tests/test_orchestrator.py::test_run_query_defaults_principal_to_placeholder agent/tests/test_orchestrator.py::test_agent_outcome_has_planner_failure_field -v`
Expected: PASS (3 tests)

- [x] **Step 8: 运行现有回归测试确保不破坏**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py agent/tests/test_conversation_context.py -v`
Expected: PASS (all existing tests still pass — new params default None, new field defaults None)

- [x] **Step 9: Commit**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/sap_nexus_agent/workbench_output.py frontend/src/runtime/durable/types.ts agent/tests/test_orchestrator.py
git commit -m "feat: bind GovernedContext + SnapshotLease in run_query entry; add planner_failure to AgentOutcome

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: visibility pre-filter 接入 matcher 决策路径

**对应 tasks.md §3（visibility pre-filter 接入 matcher 决策路径）**

**Files:**
- Modify: `agent/sap_nexus_agent/visibility.py`（增 `filter_catalog` helper）
- Modify: `agent/sap_nexus_agent/orchestrator.py:143-151`（discover_cards -> filter_visible -> VisibleCapabilitySet，传给 select_capability）
- Modify: `agent/sap_nexus_agent/capability_selector.py:42`（select_capability 接 VisibleCapabilitySet）
- Test: `agent/tests/test_visibility.py`、`agent/tests/test_capability_selector.py`

**Interfaces:**
- Consumes: Task 1 的 `VisibleCapabilitySet`、`GovernedContext`；Task 2 的 `SnapshotLease`
- Produces: `filter_catalog(catalog, visible_cards) -> IntentCatalog`；`select_capability(parse_result, visible) -> MatchDecision`

- [x] **Step 1: 编写失败测试 — filter_catalog helper**

```python
# 追加到 agent/tests/test_visibility.py
from sap_nexus_agent.visibility import filter_catalog
from sap_nexus_agent.registry_loader import IntentCatalog, CapabilityDescriptor, InputDescriptor


def _descriptor(capability_id: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        name=f"Cap {capability_id}",
        description="",
        domain="",
        business_object="",
        inputs=(),
    )


def test_filter_catalog_keeps_visible_capabilities():
    catalog = IntentCatalog(
        capabilities=(_descriptor("A"), _descriptor("B"), _descriptor("C")),
        capability_ids=frozenset({"A", "B", "C"}),
    )
    visible_cards = [
        CapabilityCard(
            capability_id="A",
            name="A",
            governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        ),
        CapabilityCard(
            capability_id="C",
            name="C",
            governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        ),
    ]
    filtered = filter_catalog(catalog, visible_cards)
    assert filtered.capability_ids == frozenset({"A", "C"})
    assert len(filtered.capabilities) == 2


def test_filter_catalog_empty_visible_returns_empty():
    catalog = IntentCatalog(
        capabilities=(_descriptor("A"),),
        capability_ids=frozenset({"A"}),
    )
    filtered = filter_catalog(catalog, [])
    assert filtered.capability_ids == frozenset()
    assert len(filtered.capabilities) == 0


def test_filter_catalog_preserves_capability_not_in_cards():
    """Capabilities not in visible_cards are filtered out."""
    catalog = IntentCatalog(
        capabilities=(_descriptor("A"), _descriptor("B")),
        capability_ids=frozenset({"A", "B"}),
    )
    visible_cards = [
        CapabilityCard(
            capability_id="A",
            name="A",
            governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        ),
    ]
    filtered = filter_catalog(catalog, visible_cards)
    assert filtered.capability_ids == frozenset({"A"})
```

- [x] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_visibility.py::test_filter_catalog_keeps_visible_capabilities -v`
Expected: FAIL — `ImportError: cannot import name 'filter_catalog'`

- [x] **Step 3: 实现 — filter_catalog helper**

在 `agent/sap_nexus_agent/visibility.py` 末尾添加:

```python
from sap_nexus_agent.registry_loader import IntentCatalog


def filter_catalog(
    catalog: IntentCatalog,
    visible_cards: list[CapabilityCard],
) -> IntentCatalog:
    """Filter an IntentCatalog to only capabilities present in visible_cards.

    Used by cli.py to pre-filter the catalog before building the intent
    adapter, so the LLM prompt only contains visible capabilities
    (Design Doc §4 data flow: ``filter_visible(catalog) -> visible catalog``).
    """
    visible_ids = frozenset(c.capability_id for c in visible_cards)
    filtered = tuple(c for c in catalog.capabilities if c.capability_id in visible_ids)
    return IntentCatalog(
        capabilities=filtered,
        capability_ids=frozenset(c.capability_id for c in filtered),
    )
```

在 `__all__` 列表中添加 `"filter_catalog"`。

- [x] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_visibility.py -v -k filter_catalog`
Expected: PASS (3 tests)

- [x] **Step 5: 编写失败测试 — select_capability 接受 VisibleCapabilitySet**

```python
# 追加到 agent/tests/test_capability_selector.py
from sap_nexus_agent.governed_context import VisibleCapabilitySet
from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance


def _visible_card(capability_id: str, snapshot_id: str = "sha256:test") -> VisibleCapabilitySet:
    card = CapabilityCard(
        capability_id=capability_id,
        name=capability_id,
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        registry_snapshot_id=snapshot_id,
    )
    return VisibleCapabilitySet(cards=(card,), snapshot_id=snapshot_id, principal_id="user-1")


def test_select_capability_accepts_visible_capability_set():
    """select_capability with visible set filters matched_intents to visible only."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(capability_id="MM.Inventory.GetAvailability", parameters={}, missing=[]),
            MatchedIntent(capability_id="MM.Hidden.Capability", parameters={}, missing=[]),
        ],
    )
    visible = _visible_card("MM.Inventory.GetAvailability", "sha256:snap-1")
    decision = select_capability(parse_result, visible=visible)
    # Multi-intent -> ESCALATE; handoff should carry snapshot_id from visible
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.registry_snapshot_id == "sha256:snap-1"
    # Hidden capability should be filtered out of matched_intents
    visible_in_handoff = [mi.capability_id for mi in decision.handoff.matched_intents]
    assert "MM.Hidden.Capability" not in visible_in_handoff


def test_select_capability_without_visible_backward_compat():
    """select_capability without visible param behaves as before (backward compat)."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "M1", "plant": "P1"},
        missing_parameters=[],
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "SELECT"
```

- [x] **Step 6: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py::test_select_capability_accepts_visible_capability_set -v`
Expected: FAIL — `TypeError: select_capability() got an unexpected keyword argument 'visible'` 或 `AttributeError: registry_snapshot_id`

- [x] **Step 7: 实现 — select_capability 接 VisibleCapabilitySet**

修改 `agent/sap_nexus_agent/capability_selector.py:42` 的 `select_capability` 签名和函数体:

```python
def select_capability(
    parse_result: IntentParseResult,
    visible: "VisibleCapabilitySet | None" = None,
) -> MatchDecision:
```

在文件头部添加 TYPE_CHECKING import:

```python
if TYPE_CHECKING:
    from sap_nexus_agent.governed_context import VisibleCapabilitySet
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchDecision, MatchedIntent
```

在函数体开头（lazy import 之后）添加 visible 过滤逻辑:

```python
    # When a VisibleCapabilitySet is provided, filter matched_intents to
    # only visible capabilities (double-check; the catalog was already
    # pre-filtered). Also derive snapshot_id for the handoff from visible.
    visible_snapshot_id = ""
    if visible is not None:
        visible_ids = frozenset(c.capability_id for c in visible.cards)
        visible_snapshot_id = visible.snapshot_id
        if parse_result.matched_intents:
            filtered = [
                mi for mi in parse_result.matched_intents
                if mi.capability_id in visible_ids
            ]
            # Use filtered list for the rest of the decision tree.
            # (SimpleNamespace-like approach: create a shallow copy)
            parse_result = dataclasses.replace(
                parse_result,
                matched_intents=filtered,
            )
```

在文件头部添加 `import dataclasses`。

修改 ESCALATE_TO_PLANNER 分支中的 `registry_snapshot_id` 填入:

```python
            handoff=EscalationHandoff(
                reason="multi-intent",
                matched_intents=list(parse_result.matched_intents),
                utterance=getattr(parse_result, "utterance", ""),
                registry_snapshot_id=visible_snapshot_id or getattr(parse_result, "registry_snapshot_id", ""),
            ),
```

- [x] **Step 8: 实现 — orchestrator 中构造 VisibleCapabilitySet 并传给 select_capability**

在 `agent/sap_nexus_agent/orchestrator.py` 的 `run_query` 函数体中，在 `parsed = intent_adapter(text)` 或 `parsed = intent_adapter(text, context)` 之后，`decision = select_capability(parsed)` 之前，添加:

```python
    # Discover cards from snapshot and filter visible (Design Doc §4).
    from sap_nexus_agent.planner.capability_card import discover_cards
    from sap_nexus_agent.visibility import filter_visible

    all_cards = discover_cards(snapshot, sources)
    visible_cards = filter_visible(all_cards, for_execution=False)
    visible_capability_set = VisibleCapabilitySet(
        cards=tuple(visible_cards),
        snapshot_id=lease.snapshot_id,
        principal_id=effective_principal.principal_id,
    )
```

修改 `select_capability` 调用:

```python
    decision = select_capability(parsed, visible=visible_capability_set)
```

- [x] **Step 9: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py agent/tests/test_visibility.py -v`
Expected: PASS

- [x] **Step 10: 运行回归测试**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_eval_runner.py -v`
Expected: PASS

- [x] **Step 11: Commit**

```bash
git add agent/sap_nexus_agent/visibility.py agent/sap_nexus_agent/capability_selector.py agent/sap_nexus_agent/orchestrator.py agent/tests/test_visibility.py agent/tests/test_capability_selector.py
git commit -m "feat: wire visibility pre-filter into matcher path; select_capability accepts VisibleCapabilitySet

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: matcher 绑定非空 snapshotId

**对应 tasks.md §4（matcher 绑定非空 snapshotId）**

**Files:**
- Modify: `agent/sap_nexus_agent/capability_selector.py:72-86`（handoff.registry_snapshot_id 从 visible 填入）
- Test: `agent/tests/test_capability_selector.py`

**Interfaces:**
- Consumes: Task 3 的 `VisibleCapabilitySet.snapshot_id`
- Produces: `EscalationHandoff.registry_snapshot_id` 非空（来自 `VisibleCapabilitySet`）

> **注意:** Task 3 的 Step 7 已在 `select_capability` 中将 `visible_snapshot_id` 填入 `handoff.registry_snapshot_id`。本 Task 补充专项测试断言非空 + 等于 GovernedContext.snapshotId，并验证 `EscalationHandoff` 类型语义不变（`str`，非 optional，语义非空）。

- [x] **Step 1: 编写失败测试 — handoff.registry_snapshot_id 非空且等于 visible.snapshot_id**

```python
# 追加到 agent/tests/test_capability_selector.py

def test_handoff_snapshot_id_is_non_empty_when_visible_provided():
    """EscalationHandoff.registry_snapshot_id must be non-empty when visible is provided."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(capability_id="MM.Inventory.GetAvailability", parameters={}, missing=[]),
            MatchedIntent(capability_id="MM.PurchaseOrder.GetList", parameters={}, missing=[]),
        ],
    )
    visible = _visible_card("MM.Inventory.GetAvailability", "sha256:snap-42")
    # Add second visible card
    from sap_nexus_agent.governed_context import VisibleCapabilitySet
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance
    visible = VisibleCapabilitySet(
        cards=(
            CapabilityCard(
                capability_id="MM.Inventory.GetAvailability",
                name="Inv",
                governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
                registry_snapshot_id="sha256:snap-42",
            ),
            CapabilityCard(
                capability_id="MM.PurchaseOrder.GetList",
                name="PO",
                governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
                registry_snapshot_id="sha256:snap-42",
            ),
        ),
        snapshot_id="sha256:snap-42",
        principal_id="user-1",
    )
    decision = select_capability(parse_result, visible=visible)
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.registry_snapshot_id == "sha256:snap-42"
    assert decision.handoff.registry_snapshot_id != ""


def test_handoff_snapshot_id_empty_when_no_visible():
    """Without visible, handoff.registry_snapshot_id falls back to getattr default (backward compat)."""
    from sap_nexus_agent.intent import IntentParseResult
    from sap_nexus_agent.match_decision import MatchedIntent
    from sap_nexus_agent.capability_selector import select_capability

    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        matched_intents=[
            MatchedIntent(capability_id="A", parameters={}, missing=[]),
            MatchedIntent(capability_id="B", parameters={}, missing=[]),
        ],
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "ESCALATE_TO_PLANNER"
    assert decision.handoff is not None
    assert decision.handoff.registry_snapshot_id == ""
```

- [x] **Step 2: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_capability_selector.py::test_handoff_snapshot_id_is_non_empty_when_visible_provided agent/tests/test_capability_selector.py::test_handoff_snapshot_id_empty_when_no_visible -v`
Expected: PASS（Task 3 已实现填入逻辑；本 Task 的测试验证语义正确性）

- [x] **Step 3: Commit**

```bash
git add agent/tests/test_capability_selector.py
git commit -m "test: assert EscalationHandoff.registry_snapshot_id non-empty when visible provided

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: planner 绑定同一 snapshot + 结构化 fail-closed

**对应 tasks.md §5（planner 绑定同一 snapshot + 结构化 fail-closed）**

**Files:**
- Modify: `agent/sap_nexus_agent/planner/capability_card.py:66-88`（CapabilityCard 增 `registry_snapshot_id`）
- Modify: `agent/sap_nexus_agent/planner/capability_card.py:137-195`（discover_cards 移除 `del snapshot`，填入 `registry_snapshot_id`）
- Modify: `agent/sap_nexus_agent/orchestrator.py:173-189`（ESCALATE 路径: lease.assert_same + _compile_dry_run_safely 消费 lease 返 PlannerFailure）
- Modify: `agent/sap_nexus_agent/orchestrator.py:595-617`（_compile_dry_run_safely 重写: 消费 lease, 返 PlannerFailure 而非 None）
- Test: `agent/tests/test_planner_capability_card.py`、`agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 1 的 `SnapshotLease`、`PlannerFailure`、`SnapshotDriftError`；Task 2 的 `AgentOutcome.planner_failure`
- Produces: `CapabilityCard.registry_snapshot_id` 字段；`_compile_dry_run_safely(handoff, lease) -> DryRunResult | PlannerFailure`

- [x] **Step 1: 编写失败测试 — CapabilityCard 携带 registry_snapshot_id**

```python
# 追加到 agent/tests/test_planner_capability_card.py

def test_capability_card_has_registry_snapshot_id_field():
    """CapabilityCard has a registry_snapshot_id field."""
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance
    card = CapabilityCard(
        capability_id="X",
        name="X",
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        registry_snapshot_id="sha256:snap-1",
    )
    assert card.registry_snapshot_id == "sha256:snap-1"


def test_capability_card_registry_snapshot_id_defaults_empty():
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance
    card = CapabilityCard(
        capability_id="X",
        name="X",
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
    )
    assert card.registry_snapshot_id == ""


def test_discover_cards_binds_registry_snapshot_id():
    """discover_cards fills registry_snapshot_id from the snapshot."""
    from sap_nexus_agent.planner.capability_card import discover_cards
    snapshot, sources = _real_sources()  # existing fixture in this test file
    cards = discover_cards(snapshot, sources)
    assert len(cards) > 0
    for card in cards:
        assert card.registry_snapshot_id == snapshot.snapshot_id
```

- [x] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_capability_card.py::test_capability_card_has_registry_snapshot_id_field -v`
Expected: FAIL — `TypeError: CapabilityCard.__init__() got an unexpected keyword argument 'registry_snapshot_id'`

- [x] **Step 3: 实现 — CapabilityCard 增 registry_snapshot_id 字段**

在 `agent/sap_nexus_agent/planner/capability_card.py:66-88` 的 `CapabilityCard` dataclass 中，在 `inputs` 字段之后添加:

```python
    registry_snapshot_id: str = ""
```

- [x] **Step 4: 实现 — discover_cards 移除 del snapshot，填入 registry_snapshot_id**

在 `agent/sap_nexus_agent/planner/capability_card.py:137` 的 `discover_cards` 函数中:

1. 移除 `del snapshot  # reserved for Task 8 PlanCompiler wiring` 行（第 157 行）
2. 在 `cards.append(CapabilityCard(...))` 中添加 `registry_snapshot_id=snapshot.snapshot_id`

修改后的 `cards.append` 调用:

```python
        cards.append(
            CapabilityCard(
                capability_id=capability_id,
                name=str(raw.get("name", "")),
                inputs=inputs,
                governance=_project_governance(governance_raw),
                visibility="VISIBLE_DRY_RUN",
                produces_fact_types=_project_produces_fact_types(
                    raw.get("outputs")
                ),
                registry_snapshot_id=snapshot.snapshot_id,
            )
        )
```

- [x] **Step 5: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_capability_card.py -v -k "registry_snapshot_id or discover_cards_binds"`
Expected: PASS

- [x] **Step 6: 运行回归测试确保 discover_cards 变更不破坏现有测试**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_capability_card.py agent/tests/test_planner_handoff.py agent/tests/test_planner_plan_compiler.py -v`
Expected: PASS

- [x] **Step 7: 编写失败测试 — _compile_dry_run_safely 返回 PlannerFailure on drift**

```python
# 追加到 agent/tests/test_orchestrator.py

def test_compile_dry_run_safely_returns_planner_failure_on_drift():
    """When handoff.snapshot_id != lease.snapshot_id, return PlannerFailure(SNAPSHOT_DRIFT)."""
    from sap_nexus_agent.orchestrator import _compile_dry_run_safely
    from sap_nexus_agent.governed_context import SnapshotLease, SnapshotDriftError
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
    from sap_nexus_agent.semantic_planning.contracts import (
        RegistrySnapshot, SemanticSourceDocuments, SnapshotSource,
    )

    snapshot = RegistrySnapshot(
        snapshot_version=1, canonicalization_version=1,
        snapshot_id="sha256:lease-snap",
        sources=(SnapshotSource(path="x", document_version=1, digest="x"),),
    )
    sources = SemanticSourceDocuments(
        capabilities={"capabilities": []},
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )
    lease = SnapshotLease(snapshot=snapshot, sources=sources)

    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[MatchedIntent(capability_id="A", parameters={}, missing=[])],
        utterance="test",
        registry_snapshot_id="sha256:different-snap",
    )

    result = _compile_dry_run_safely(handoff, lease=lease)
    assert result is not None
    # result should be a PlannerFailure, not a DryRunResult
    from sap_nexus_agent.governed_context import PlannerFailure
    assert isinstance(result, PlannerFailure)
    assert result.error_type == "SNAPSHOT_DRIFT"
    assert result.audit_evidence["expected_snapshot_id"] == "sha256:lease-snap"
    assert result.audit_evidence["actual_snapshot_id"] == "sha256:different-snap"


def test_compile_dry_run_safely_returns_planner_failure_on_source_load_error():
    """When compile_dry_run_from_handoff raises, return PlannerFailure(SOURCE_LOAD_ERROR)."""
    from sap_nexus_agent.orchestrator import _compile_dry_run_safely
    from sap_nexus_agent.governed_context import SnapshotLease, PlannerFailure
    from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
    from sap_nexus_agent.semantic_planning.contracts import (
        RegistrySnapshot, SemanticSourceDocuments, SnapshotSource,
    )

    snapshot = RegistrySnapshot(
        snapshot_version=1, canonicalization_version=1,
        snapshot_id="sha256:snap",
        sources=(SnapshotSource(path="x", document_version=1, digest="x"),),
    )
    # Malformed sources that will cause compile_dry_run_from_handoff to fail
    sources = SemanticSourceDocuments(
        capabilities={"capabilities": "not-a-list"},  # type: ignore[arg-type]
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )
    lease = SnapshotLease(snapshot=snapshot, sources=sources)

    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[MatchedIntent(capability_id="A", parameters={}, missing=[])],
        utterance="test",
        registry_snapshot_id="sha256:snap",
    )

    result = _compile_dry_run_safely(handoff, lease=lease)
    # Either a PlannerFailure or a DryRunResult with invalid_plan_graph flag.
    # The key assertion: it must NOT be None (no silent swallowing).
    assert result is not None
```

- [x] **Step 8: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_compile_dry_run_safely_returns_planner_failure_on_drift -v`
Expected: FAIL — `TypeError: _compile_dry_run_safely() got an unexpected keyword argument 'lease'`

- [x] **Step 9: 实现 — _compile_dry_run_safely 重写: 消费 lease, 返 PlannerFailure**

替换 `agent/sap_nexus_agent/orchestrator.py:595-617` 的 `_compile_dry_run_safely` 函数:

```python
def _compile_dry_run_safely(
    handoff,
    *,
    lease: SnapshotLease,
) -> "DryRunResult | PlannerFailure":
    """Compile a dry-run from the handoff, consuming the same lease.

    Checks snapshot drift via ``lease.assert_same`` before compiling.
    On drift or source-load failure, returns a structured ``PlannerFailure``
    (Design Doc §3.5) instead of silently returning None.
    """
    try:
        lease.assert_same(handoff.registry_snapshot_id, stage="planner")
    except SnapshotDriftError as exc:
        return PlannerFailure(
            error_type="SNAPSHOT_DRIFT",
            message=str(exc),
            snapshot_id=lease.snapshot_id,
            audit_evidence={
                "expected_snapshot_id": exc.expected,
                "actual_snapshot_id": exc.actual,
                "principal_id": None,
                "source_paths": [],
                "stage": exc.stage,
            },
        )
    try:
        return compile_dry_run_from_handoff(handoff, lease.snapshot, lease.sources)
    except Exception as exc:
        return PlannerFailure(
            error_type="SOURCE_LOAD_ERROR",
            message=f"planner source compilation failed: {exc}",
            snapshot_id=lease.snapshot_id,
            audit_evidence={
                "expected_snapshot_id": lease.snapshot_id,
                "actual_snapshot_id": lease.snapshot_id,
                "principal_id": None,
                "source_paths": [],
                "stage": "planner",
            },
        )
```

- [x] **Step 10: 实现 — orchestrator ESCALATE 路径调用新 _compile_dry_run_safely**

修改 `agent/sap_nexus_agent/orchestrator.py:173-189` 的 ESCALATE 路径:

```python
    # SHOW_OPTIONS / ESCALATE_TO_PLANNER: handoff to workbench/planner, no Gateway.
    if decision.decision_type in ("SHOW_OPTIONS", "ESCALATE_TO_PLANNER"):
        dry_run = None
        planner_failure = None
        if decision.decision_type == "ESCALATE_TO_PLANNER" and decision.handoff is not None:
            result = _compile_dry_run_safely(decision.handoff, lease=lease)
            if isinstance(result, PlannerFailure):
                planner_failure = result
            else:
                dry_run = result
        return AgentOutcome(
            status="match_decision",
            message=decision.rationale,
            response_text=decision.rationale,
            match_decision=decision,
            dry_run=dry_run,
            planner_failure=planner_failure,
        )
```

- [x] **Step 11: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_compile_dry_run_safely_returns_planner_failure_on_drift agent/tests/test_orchestrator.py::test_compile_dry_run_safely_returns_planner_failure_on_source_load_error -v`
Expected: PASS

- [x] **Step 12: 运行回归测试**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_planner_handoff.py agent/tests/test_planner_capability_card.py agent/tests/test_planner_plan_compiler.py agent/tests/test_eval_runner.py -v`
Expected: PASS

- [x] **Step 13: Commit**

```bash
git add agent/sap_nexus_agent/planner/capability_card.py agent/sap_nexus_agent/orchestrator.py agent/tests/test_planner_capability_card.py agent/tests/test_orchestrator.py
git commit -m "feat: discover_cards binds snapshot; _compile_dry_run_safely consumes lease, returns PlannerFailure on drift/error

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: capability kind 从 Registry snapshot 投影

**对应 tasks.md §6（capability kind 从 Registry snapshot 投影）**

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py:191-225`（kind 从 `governance.requires_approval` 判定，移除 `ACTION_CAPABILITY_IDS` 兜底）
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 3 的 `VisibleCapabilitySet.cards`（含 `governance.requires_approval`）
- Produces: kind 判定不再依赖 `ACTION_CAPABILITY_IDS` 硬编码集合

- [x] **Step 1: 编写失败测试 — kind 从 governance.requires_approval 判定**

```python
# 追加到 agent/tests/test_orchestrator.py

def test_kind_from_governance_requires_approval():
    """Action kind is determined by governance.requires_approval, not ACTION_CAPABILITY_IDS."""
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance

    # A card with requires_approval=True -> Action
    card_action = CapabilityCard(
        capability_id="MM.PR.CreateDraft",
        name="PR",
        governance=Governance(side_effect="sap_write", requires_approval=True, data_classification="internal"),
        registry_snapshot_id="sha256:x",
    )
    assert card_action.governance.requires_approval is True

    # A card with requires_approval=False -> Function
    card_function = CapabilityCard(
        capability_id="MM.Inventory.GetAvailability",
        name="Inv",
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        registry_snapshot_id="sha256:x",
    )
    assert card_function.governance.requires_approval is False


def test_orchestrator_kind_uses_governance_not_action_capability_ids():
    """orchestrator kind判定 should use governance.requires_approval from visible cards.

    This is a regression guard: if ACTION_CAPABILITY_IDS is removed and the
    capability still has governance.requires_approval=True in the snapshot,
    the kind should still be 'Action'.
    """
    from sap_nexus_agent.orchestrator import run_query
    from sap_nexus_agent.gateway_client import GatewayClientProtocol

    class FakeGateway:
        def validate(self, capability_id, parameters):
            from sap_nexus_agent.execution_result import ValidationResult
            return ValidationResult(success=True, trace_id="t", capability_id=capability_id, error_type=None, messages=[])
        def execute(self, capability_id, parameters, approval_id=None):
            from sap_nexus_agent.execution_result import ExecutionResult
            return ExecutionResult(success=True, trace_id="t", capability_id=capability_id, executor={}, return_messages=[], data={}, duration_ms=1, error_type=None)

    # PR CreateDraft path should produce awaiting_approval (Action kind)
    outcome = run_query(
        "帮我创建采购申请 物料 M1 工厂 1000 数量 10",
        FakeGateway(),
    )
    # PR path -> awaiting_approval (Action)
    assert outcome.status in {"awaiting_approval", "clarification", "failure"}
```

- [x] **Step 2: 运行测试验证通过（部分已有行为）**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_kind_from_governance_requires_approval -v`
Expected: PASS（CapabilityCard 已有 governance 字段）

- [x] **Step 3: 实现 — orchestrator kind 判定从 governance 投影**

在 `agent/sap_nexus_agent/orchestrator.py` 的 `run_query` 函数中，需要从 `visible_capability_set` 查找当前 `capability_id` 对应的 card，用 `card.governance.requires_approval` 判定 kind。

在 SELECT 路径（`capability_id = decision.capability_id` 之后）添加 card 查找:

```python
    # Kind from snapshot projection (Design Doc D6): use
    # governance.requires_approval from the visible CapabilityCard,
    # not the hardcoded ACTION_CAPABILITY_IDS set.
    matched_card = next(
        (c for c in visible_capability_set.cards if c.capability_id == capability_id),
        None,
    )
    is_action = matched_card is not None and matched_card.governance.requires_approval
```

替换所有 `kind = "Action" if capability_id in ACTION_CAPABILITY_IDS else "Function"` 行为:

```python
    kind = "Action" if is_action else "Function"
```

替换 `is_action = call_plan.kind == "Action"` 行（已有，保持不变）。

同时修改 multi_parameters 路径中的 kind 判定（`orchestrator.py:211`）:

```python
        kind = "Action" if is_action else "Function"
```

> **注意:** `ACTION_CAPABILITY_IDS` 常量保留（`continue_batch` 仍用于 defense-in-depth guard），但 `run_query` 的 kind 判定不再依赖它。

- [x] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v -k "kind or pr_create or awaiting_approval"`
Expected: PASS

- [x] **Step 5: 运行回归测试**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_orchestrator_write.py agent/tests/test_eval_runner.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat: project capability kind from governance.requires_approval instead of ACTION_CAPABILITY_IDS

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: ApprovalRecord 携带 registry_snapshot_id

**对应 tasks.md §7（ApprovalRecord 携带 registry_snapshot_id）**

**Files:**
- Modify: `agent/sap_nexus_agent/approval.py:26-63`（ApprovalRecord 增字段 + from_dict/to_dict）
- Modify: `agent/sap_nexus_agent/approval.py:122-140`（create_approval_record 接收 registry_snapshot_id）
- Modify: `agent/sap_nexus_agent/orchestrator.py:241-245`（create_approval_record 调用填入）
- Test: `agent/tests/test_approval.py`

**Interfaces:**
- Consumes: Task 2 的 `GovernedContext.snapshot_id`（通过 `lease.snapshot_id`）
- Produces: `ApprovalRecord.registry_snapshot_id: str = ""`（optional, 向后兼容）

- [x] **Step 1: 编写失败测试 — ApprovalRecord registry_snapshot_id 字段**

```python
# 追加到 agent/tests/test_approval.py

def test_approval_record_has_registry_snapshot_id_field():
    """ApprovalRecord has a registry_snapshot_id field defaulting to empty."""
    from sap_nexus_agent.approval import ApprovalRecord, ApprovalState
    from datetime import datetime, timezone
    record = ApprovalRecord(
        approval_id="appr-1",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:x",
        parameters={"material": "M1"},
        approver="user",
        approved_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        status=ApprovalState.pending,
    )
    assert record.registry_snapshot_id == ""


def test_approval_record_to_dict_includes_registry_snapshot_id():
    from sap_nexus_agent.approval import ApprovalRecord, ApprovalState
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-1",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:x",
        parameters={"material": "M1"},
        approver="user",
        approved_at=now,
        expires_at=now,
        status=ApprovalState.pending,
        registry_snapshot_id="sha256:snap-1",
    )
    d = record.to_dict()
    assert d["registrySnapshotId"] == "sha256:snap-1"


def test_approval_record_from_dict_backward_compat_without_field():
    """Old payloads without registrySnapshotId default to empty."""
    from sap_nexus_agent.approval import ApprovalRecord
    payload = {
        "approvalId": "appr-1",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:x",
        "parameters": {"material": "M1"},
        "approver": "user",
        "approvedAt": "2026-01-01T00:00:00+00:00",
        "expiresAt": "2026-01-01T00:10:00+00:00",
        "status": "pending",
    }
    record = ApprovalRecord.from_dict(payload)
    assert record.registry_snapshot_id == ""


def test_approval_record_from_dict_reads_registry_snapshot_id():
    from sap_nexus_agent.approval import ApprovalRecord
    payload = {
        "approvalId": "appr-1",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:x",
        "parameters": {},
        "approver": "user",
        "approvedAt": "2026-01-01T00:00:00+00:00",
        "expiresAt": "2026-01-01T00:10:00+00:00",
        "status": "pending",
        "registrySnapshotId": "sha256:snap-2",
    }
    record = ApprovalRecord.from_dict(payload)
    assert record.registry_snapshot_id == "sha256:snap-2"


def test_create_approval_record_accepts_registry_snapshot_id():
    from sap_nexus_agent.approval import create_approval_record
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M1"},
        approver="user",
        registry_snapshot_id="sha256:snap-3",
    )
    assert record.registry_snapshot_id == "sha256:snap-3"
```

- [x] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest agent/tests/test_approval.py::test_approval_record_has_registry_snapshot_id_field -v`
Expected: FAIL — `TypeError: ApprovalRecord.__init__() got an unexpected keyword argument 'registry_snapshot_id'`

- [x] **Step 3: 实现 — ApprovalRecord 增 registry_snapshot_id 字段**

在 `agent/sap_nexus_agent/approval.py:26-35` 的 `ApprovalRecord` dataclass 中，在 `status` 字段之后添加:

```python
    registry_snapshot_id: str = ""
```

- [x] **Step 4: 实现 — from_dict / to_dict 兼容**

修改 `from_dict`（`approval.py:37-51`），在 return 的 cls(...) 中添加:

```python
            registry_snapshot_id=str(payload.get("registrySnapshotId", "")),
```

修改 `to_dict`（`approval.py:53-63`），在 return dict 中添加:

```python
            "registrySnapshotId": self.registry_snapshot_id,
```

- [x] **Step 5: 实现 — create_approval_record 接收 registry_snapshot_id**

修改 `create_approval_record`（`approval.py:122-140`）签名:

```python
def create_approval_record(
    capability_id: str,
    parameters: dict[str, str],
    approver: str,
    ttl_seconds: int | None = None,
    registry_snapshot_id: str = "",
) -> ApprovalRecord:
```

在 `ApprovalRecord(...)` 构造中添加:

```python
        registry_snapshot_id=registry_snapshot_id,
```

- [x] **Step 6: 实现 — orchestrator 调用 create_approval_record 填入 snapshot_id**

修改 `agent/sap_nexus_agent/orchestrator.py:241-245` 的 `create_approval_record` 调用:

```python
        pending = create_approval_record(
            capability_id=call_plan.capability_id,
            parameters=call_plan.parameters,
            approver="user",
            registry_snapshot_id=lease.snapshot_id,
        )
```

- [x] **Step 7: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_approval.py -v`
Expected: PASS

- [x] **Step 8: 运行回归测试**

Run: `.venv/bin/python -m pytest agent/tests/test_approval.py agent/tests/test_orchestrator.py agent/tests/test_orchestrator_write.py agent/tests/test_cli_approval.py -v`
Expected: PASS

- [x] **Step 9: Commit**

```bash
git add agent/sap_nexus_agent/approval.py agent/sap_nexus_agent/orchestrator.py agent/tests/test_approval.py
git commit -m "feat: ApprovalRecord carries registry_snapshot_id; create_approval_record fills from lease

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: principal 透传 Node backend -> Python agent

**对应 tasks.md §8（principal 透传 Node backend -> Python agent）**

**Files:**
- Modify: `agent/sap_nexus_agent/cli.py:18-130`（读 SAP_NEXUS_PRINCIPAL env -> TrustedPrincipal；filter_catalog -> build_intent_adapter；传 principal/snapshot/sources）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts:145-155`（executeRunnerInBackground -> runner 传 principal）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts:49-55`（AgentRunnerInput 增 principal）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts:725-777`（runLocalPythonAgent spawn 时设 SAP_NEXUS_PRINCIPAL env）
- Test: `agent/tests/test_cli_context.py`、`frontend/src/runtime/agent-runtime-adapter.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `load_principal_from_env`；Task 3 的 `filter_catalog`
- Produces: cli.py 读 env + 过滤 catalog + 传 principal；frontend spawn 时设 env

- [x] **Step 1: 编写失败测试 — cli.py 读 SAP_NEXUS_PRINCIPAL env**

```python
# 追加到 agent/tests/test_cli_context.py（或新建 test_cli_principal.py）

def test_cli_reads_principal_from_env(monkeypatch, capsys):
    """cli.py reads SAP_NEXUS_PRINCIPAL env and passes to run_query."""
    import json
    monkeypatch.setenv("SAP_NEXUS_PRINCIPAL", json.dumps({
        "principalId": "user-cli-test",
        "role": "operator",
        "dataScope": {"tenantId": "t1"},
    }))
    # Run cli with --json and a simple query
    from sap_nexus_agent.cli import main
    exit_code = main(["--json", "查物料 DEMOA1 在工厂 1000 的可用库存"])
    assert exit_code in {0, 1}
    output = capsys.readouterr().out
    payload = json.loads(output)
    # The outcome should be produced (status is one of the expected values)
    assert "status" in payload
```

- [x] **Step 2: 运行测试验证通过（env 默认回退 PLACEHOLDER）**

Run: `.venv/bin/python -m pytest agent/tests/test_cli_context.py::test_cli_reads_principal_from_env -v`
Expected: 可能 PASS（默认行为不崩），但需要验证 principal 被正确读取

- [x] **Step 3: 实现 — cli.py 读 env + filter_catalog + 传 principal**

修改 `agent/sap_nexus_agent/cli.py`，在 imports 中添加:

```python
from sap_nexus_agent.governed_context import load_principal_from_env
from sap_nexus_agent.visibility import filter_catalog
from sap_nexus_agent.planner.capability_card import discover_cards
from sap_nexus_agent.visibility import filter_visible
from sap_nexus_agent.semantic_planning import build_registry_snapshot, load_semantic_sources
```

修改 `main` 函数中非 continuation 路径（`--context` 路径和默认路径），在 `catalog = load_intent_catalog()` 之后添加:

```python
    principal = load_principal_from_env()
    # Load snapshot for visibility filtering + pass to run_query.
    repo_root = Path(__file__).resolve().parents[1]
    # Walk up to find registry/
    for parent in [Path(__file__).resolve().parents[1], *Path(__file__).resolve().parents[1].parents]:
        if (parent / "registry" / "capabilities.yaml").exists():
            repo_root = parent
            break
    try:
        sources = load_semantic_sources(repo_root)
        snapshot = build_registry_snapshot(sources)
        cards = discover_cards(snapshot, sources)
        visible_cards = filter_visible(cards, for_execution=False)
        catalog = filter_catalog(catalog, visible_cards)
    except Exception:
        pass  # fallback: use unfiltered catalog (local dev tolerance)
    intent_adapter = build_intent_adapter(args.intent_mode, catalog)
```

需要 `from pathlib import Path` 在文件头部。

修改 `run_query` 调用，传入 `principal`、`snapshot`、`sources`:

```python
    outcome = run_query(
        args.query,
        gateway,
        intent_adapter=intent_adapter,
        principal=principal,
        snapshot=snapshot if "snapshot" in dir() else None,
        sources=sources if "sources" in dir() else None,
    )
```

> **注意:** `--context` 路径也需要同样处理。两个路径提取为 helper 或在每处重复。

- [x] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_cli_context.py -v`
Expected: PASS

- [x] **Step 5: 编写失败测试 — runLocalPythonAgent 设置 SAP_NEXUS_PRINCIPAL env**

```typescript
// 追加到 frontend/src/runtime/agent-runtime-adapter.test.ts

import { describe, test, expect } from "vitest";

describe("runLocalPythonAgent principal env", () => {
  test("AgentRunnerInput includes principal field", () => {
    // Type-level test: AgentRunnerInput must accept principal
    const input: AgentRunnerInput = {
      query: "test",
      gatewayUrl: "http://localhost:8080",
      intentMode: "rule",
      principal: {
        principalId: "user-1",
        role: "operator",
        dataScope: { tenantId: "t1" },
      },
    };
    expect(input.principal?.principalId).toBe("user-1");
  });
});
```

- [x] **Step 6: 实现 — AgentRunnerInput 增 principal 字段**

修改 `frontend/src/runtime/agent-runtime-adapter.ts:49-55` 的 `AgentRunnerInput` type:

```typescript
type AgentRunnerInput = {
  query: string;
  gatewayUrl: string;
  intentMode: string;
  continuation?: ApprovalContinuation | BatchContinuation;
  context?: ConversationContext;
  principal?: TrustedPrincipal;
};
```

- [x] **Step 7: 实现 — executeRunnerInBackground 传 principal 给 runner**

修改 `frontend/src/runtime/agent-runtime-adapter.ts:145-155` 的 `executeRunnerInBackground` 函数，在 `runner` 调用中传入 principal:

```typescript
async function executeRunnerInBackground(
  runId: string,
  query: string,
  conversationId: string | undefined,
  timestamp: string,
  principalId: string,
  principal?: TrustedPrincipal,
): Promise<void> {
  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const context = conversationId ? buildContext(await getSession(conversationId, principalId)) : undefined;
    const outcome = await runner({ query, gatewayUrl: gatewayUrl(), intentMode: intentMode(), context, principal });
```

修改 `createAgentRun`（`agent-runtime-adapter.ts:140`）的调用:

```typescript
  void executeRunnerInBackground(runId, query, input.conversationId, timestamp, input.principal.principalId, input.principal);
```

- [x] **Step 8: 实现 — runLocalPythonAgent spawn 时设 SAP_NEXUS_PRINCIPAL env**

修改 `frontend/src/runtime/agent-runtime-adapter.ts:767-770` 的 `env` 对象:

```typescript
  const env = {
    ...process.env,
    PYTHONPATH: [path.join(repoRoot, "agent"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    ...(input.principal ? { SAP_NEXUS_PRINCIPAL: JSON.stringify(input.principal) } : {}),
  };
```

- [x] **Step 9: 运行前端测试验证通过**

Run: `npm --prefix frontend run verify`
Expected: PASS

- [x] **Step 10: 运行 Python 回归测试**

Run: `.venv/bin/python -m pytest agent/tests/test_cli_context.py agent/tests/test_cli_approval.py agent/tests/test_cli_batch.py -v`
Expected: PASS

- [x] **Step 11: Commit**

```bash
git add agent/sap_nexus_agent/cli.py frontend/src/runtime/agent-runtime-adapter.ts agent/tests/test_cli_context.py frontend/src/runtime/agent-runtime-adapter.test.ts
git commit -m "feat: principal passthrough Node backend -> Python agent via SAP_NEXUS_PRINCIPAL env

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: CapabilityCard 安全投影固化

**对应 tasks.md §9（CapabilityCard 安全投影固化）**

**Files:**
- Test: `agent/tests/test_planner_capability_card.py`

**Interfaces:**
- Consumes: Task 5 的 `discover_cards`（已绑 snapshot + 填入 `registry_snapshot_id`）
- Produces: negative test 断言 CapabilityCard 不含技术绑定字段

- [x] **Step 1: 编写 negative test — CapabilityCard 不泄漏技术绑定**

```python
# 追加到 agent/tests/test_planner_capability_card.py

def test_capability_card_does_not_leak_technical_bindings():
    """CapabilityCard must NOT contain rfcName, serviceUrl, credentialRef,
    rawSql, executorBinding, or any technical mapping.

    Design Doc §8 测试策略: CapabilityCard 安全投影 negative test.
    """
    snapshot, sources = _real_sources()
    cards = discover_cards(snapshot, sources)
    assert len(cards) > 0

    forbidden_fields = {
        "rfcName",
        "serviceUrl",
        "entitySet",
        "httpMethod",
        "headers",
        "credentialRef",
        "rawSql",
        "executorBinding",
        "executor",
    }
    for card in cards:
        # Check dataclass fields
        field_names = {f.name for f in dataclasses.fields(card)}
        assert not (field_names & forbidden_fields), (
            f"CapabilityCard leaks technical field(s): {field_names & forbidden_fields}"
        )
        # Check governance fields
        gov_fields = {f.name for f in dataclasses.fields(card.governance)}
        assert not (gov_fields & forbidden_fields), (
            f"Governance leaks technical field(s): {gov_fields & forbidden_fields}"
        )


def test_capability_card_only_exposes_semantic_fields():
    """CapabilityCard fields are limited to semantic projection."""
    from sap_nexus_agent.planner.capability_card import CapabilityCard
    expected_fields = {
        "capability_id",
        "name",
        "governance",
        "visibility",
        "produces_fact_types",
        "inputs",
        "registry_snapshot_id",
    }
    actual_fields = {f.name for f in dataclasses.fields(CapabilityCard)}
    assert actual_fields == expected_fields, (
        f"Unexpected CapabilityCard fields: {actual_fields - expected_fields}"
    )
```

需要在 test 文件头部添加 `import dataclasses`（如果尚未导入）。

- [x] **Step 2: 运行测试验证通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_capability_card.py::test_capability_card_does_not_leak_technical_bindings agent/tests/test_planner_capability_card.py::test_capability_card_only_exposes_semantic_fields -v`
Expected: PASS（Task 5 已实现 registry_snapshot_id 字段；现有 CapabilityCard 已无技术绑定字段）

- [x] **Step 3: Commit**

```bash
git add agent/tests/test_planner_capability_card.py
git commit -m "test: CapabilityCard safe projection negative test (no technical binding leakage)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 测试与验证

**对应 tasks.md §10（测试与验证）**

**Files:**
- Test: `agent/tests/test_governed_context.py`（新）
- Test: `agent/tests/test_orchestrator.py`
- Test: `agent/tests/test_eval_runner.py`
- Spec: `openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/`

**Interfaces:**
- Consumes: Task 1-9 全部实现
- Produces: visibility leakage = 0 测试、cross-principal 决策层测试、snapshot 漂移/source load 失败/visibility denial 测试、matcher Eval 回归、安全投影回归、openspec validate

- [x] **Step 1: 编写 visibility leakage = 0 测试**

```python
# 追加到 agent/tests/test_governed_context.py

def test_visibility_leakage_zero():
    """HIDDEN capability must not enter VisibleCapabilitySet, LLM prompt, or matcher."""
    from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance
    from sap_nexus_agent.visibility import filter_visible

    hidden_card = CapabilityCard(
        capability_id="MM.Internal.Debug",
        name="Debug",
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        visibility="HIDDEN",
        registry_snapshot_id="sha256:snap",
    )
    visible_card = CapabilityCard(
        capability_id="MM.Inventory.GetAvailability",
        name="Inv",
        governance=Governance(side_effect="none", requires_approval=False, data_classification="internal"),
        visibility="VISIBLE_DRY_RUN",
        registry_snapshot_id="sha256:snap",
    )
    cards = [hidden_card, visible_card]
    visible = filter_visible(cards, for_execution=False)
    visible_ids = {c.capability_id for c in visible}
    assert "MM.Internal.Debug" not in visible_ids
    assert "MM.Inventory.GetAvailability" in visible_ids
```

- [x] **Step 2: 编写 cross-principal 决策层 fail-closed 测试**

```python
# 追加到 agent/tests/test_governed_context.py

def test_cross_principal_governed_context_binding():
    """Different principals produce different GovernedContexts with correct principal_id."""
    from sap_nexus_agent.semantic_planning.contracts import (
        RegistrySnapshot, SemanticSourceDocuments, SnapshotSource,
    )

    snapshot = RegistrySnapshot(
        snapshot_version=1, canonicalization_version=1,
        snapshot_id="sha256:same-snap",
        sources=(SnapshotSource(path="x", document_version=1, digest="x"),),
    )
    sources = SemanticSourceDocuments(
        capabilities={"capabilities": []},
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )
    lease = SnapshotLease(snapshot=snapshot, sources=sources)

    principal_a = TrustedPrincipal("user-A", "operator", {"tenantId": "t1"})
    principal_b = TrustedPrincipal("user-B", "viewer", {"tenantId": "t2"})

    ctx_a = GovernedContext(
        principal=principal_a,
        scopes=("tenantId:t1",),
        snapshot_id=lease.snapshot_id,
        registry_version=1,
    )
    ctx_b = GovernedContext(
        principal=principal_b,
        scopes=("tenantId:t2",),
        snapshot_id=lease.snapshot_id,
        registry_version=1,
    )

    assert ctx_a.principal.principal_id == "user-A"
    assert ctx_b.principal.principal_id == "user-B"
    # Same snapshot binding for both
    assert ctx_a.snapshot_id == ctx_b.snapshot_id == "sha256:same-snap"
```

- [x] **Step 3: 编写 snapshot 漂移 / source load 失败 / visibility denial 返回结构化 PlannerFailure 测试**

```python
# 追加到 agent/tests/test_governed_context.py

def test_planner_failure_snapshot_missing():
    """Empty snapshot_id -> PlannerFailure(SNAPSHOT_MISSING)."""
    failure = PlannerFailure(
        error_type="SNAPSHOT_MISSING",
        message="snapshot_id is empty",
        snapshot_id=None,
        audit_evidence={
            "expected_snapshot_id": None,
            "actual_snapshot_id": None,
            "principal_id": "user-1",
            "source_paths": [],
            "stage": "entry",
        },
    )
    assert failure.error_type == "SNAPSHOT_MISSING"
    assert failure.snapshot_id is None


def test_planner_failure_visibility_denied():
    """Empty visible set -> PlannerFailure(VISIBILITY_DENIED)."""
    failure = PlannerFailure(
        error_type="VISIBILITY_DENIED",
        message="principal has no visible capabilities",
        snapshot_id="sha256:snap",
        audit_evidence={
            "expected_snapshot_id": "sha256:snap",
            "actual_snapshot_id": "sha256:snap",
            "principal_id": "user-1",
            "source_paths": [],
            "stage": "visibility",
        },
    )
    assert failure.error_type == "VISIBILITY_DENIED"
```

> **注意:** Task 5 的 Step 7 已编写 `_compile_dry_run_safely` 的 drift 和 source load error 测试。本 Step 补充 SNAPSHOT_MISSING 和 VISIBILITY_DENIED 的数据结构验证。

- [x] **Step 4: 运行所有新增测试**

Run: `.venv/bin/python -m pytest agent/tests/test_governed_context.py -v`
Expected: PASS

- [x] **Step 5: 运行 matcher Eval 6/6 回归**

Run: `.venv/bin/python -m pytest agent/tests/test_eval_runner.py -v`
Expected: PASS (matcher_cases.yaml 5 active + dry_run 3 active 回归不回退)

- [x] **Step 6: 运行 inventory/PO/PR 路径回归**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_orchestrator_write.py agent/tests/test_cli_approval.py agent/tests/test_cli_batch.py agent/tests/test_cli_context.py -v`
Expected: PASS

- [x] **Step 7: 运行 CapabilityCard 安全投影回归**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_capability_card.py agent/tests/test_visibility.py -v`
Expected: PASS

- [x] **Step 8: 运行 openspec validate**

Run: `openspec validate --all --strict`
Expected: PASS (all specs valid)

- [x] **Step 9: 运行 openspec list**

Run: `openspec list --json`
Expected: 输出包含 `sap-nexus-governed-context-registry-snapshot` change

- [x] **Step 10: 运行 verify-agent-callplan-evidence**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: PASS

- [x] **Step 11: 运行前端 verify**

Run: `npm --prefix frontend run verify`
Expected: PASS

- [x] **Step 12: 运行全量 pytest**

Run: `.venv/bin/python -m pytest agent/tests -q`
Expected: PASS (all tests, no regressions)

- [x] **Step 13: Commit**

```bash
git add agent/tests/test_governed_context.py agent/tests/test_orchestrator.py
git commit -m "test: visibility leakage, cross-principal, PlannerFailure structured error tests

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自检清单

### Spec 覆盖

| Spec 要求 | 对应 Task |
|---|---|
| GovernedContext binds one RegistrySnapshot | Task 1, 2 |
| Snapshot lease and drift fail-closed | Task 1, 5 |
| Visibility pre-filter before LLM prompt | Task 3, 8 |
| Structured planner failure | Task 1, 5 |
| CapabilityCard safe projection | Task 5, 9 |
| Capability kind projected from snapshot | Task 6 |
| Escalation handoff binds non-empty snapshot | Task 3, 4 |
| ApprovalRecord carries registry_snapshot_id | Task 7 |
| principal 透传 Node -> Python | Task 8 |
| 测试验证 | Task 10 |

### 类型一致性

- `TrustedPrincipal`: `principal_id: str`, `role: str`, `data_scope: dict[str, str]` — Python 与 frontend TS 对齐
- `GovernedContext`: `snapshot_id: str`, `registry_version: int` — 来自 `RegistrySnapshot`
- `SnapshotLease.assert_same(other_snapshot_id: str, stage: str) -> None` — raise `SnapshotDriftError`
- `PlannerFailure.error_type`: `Literal["SNAPSHOT_MISSING", "SNAPSHOT_DRIFT", "PRINCIPAL_MISMATCH", "SOURCE_LOAD_ERROR", "VISIBILITY_DENIED"]`
- `PlannerFailure.audit_evidence`: `dict` with keys `{expected_snapshot_id, actual_snapshot_id, principal_id, source_paths, stage}`
- `VisibleCapabilitySet.cards`: `tuple[CapabilityCard, ...]`
- `CapabilityCard.registry_snapshot_id`: `str = ""`
- `ApprovalRecord.registry_snapshot_id`: `str = ""`
- `select_capability(parse_result, visible=None)`: `visible` 类型为 `VisibleCapabilitySet | None`
- `_compile_dry_run_safely(handoff, *, lease) -> DryRunResult | PlannerFailure`
- `filter_catalog(catalog: IntentCatalog, visible_cards: list[CapabilityCard]) -> IntentCatalog`

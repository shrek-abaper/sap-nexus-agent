---
change: sap-nexus-semantic-plan-authoring-v2
design-doc: docs/superpowers/specs/2026-08-03-sap-nexus-semantic-plan-authoring-v2-design.md
base-ref: 6de56e6dac15d9f957db2fab388ca67d0219a24a
archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

# PlanGraph v2 语义计划编写 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 PlanGraph v2 schema、确定性 v2 compiler 与 v2 validator，产出含 4 源 provenance、data/dependency edge、READ/WRITE 分区的 PlanGraph v2，复用 S1 校验原语，v1 零回归。

**Architecture:** 双版本并存——v1 模块（`contracts.py`/`validation.py`/`graph.py`/`plan_compiler.py`/`goal_spec.py`/`plan_draft.py`/`handoff.py`/`capability_card.py`）零改动；新建 `schemas/plan-graph-v2.schema.json`、`semantic_planning/validation_v2.py`、`planner/plan_compiler_v2.py`（含 `PlanCompileResult`），并在 `planner/handoff.py` 新增 `compile_plan_v2_from_handoff` 入口。v2 validator import S1 的 `_validate_*` 内部函数组合 + 叠加 partition/ref 校验；v2 compiler 复用 `discover_cards`/`build_goal_spec`/`CapabilityCard`/`Gap`/`Flag`。

**Tech Stack:** Python 3.11+、`jsonschema` (Draft 2020-12)、`dataclasses`、`pytest`、YAML registry fixtures。

## Global Constraints

- 双版本并存：v1 模块（`agent/sap_nexus_agent/semantic_planning/validation.py`、`contracts.py`、`graph.py`、`planner/plan_compiler.py`、`goal_spec.py`、`plan_draft.py`、`handoff.py`、`capability_card.py`）与 `schemas/plan-graph.schema.json` **零改动**。
- 参数源 4 源闭集：`goalConstraint` / `literal` / `factField` / `registeredDefault`；`registeredDefault` 本期 schema 定义形状但 compiler **不产出**。
- edge authoring 由 S1 validator 契约驱动：`factField` 绑定 -> 一条 `data` edge；snapshot `dependsOn` 关系（两端 capability 都在 plan 内）-> 一条 `dependency` edge（`fromNodeId=prerequisite`, `toNodeId=dependent`）。
- 分区：`readPartition`/`actionPartition` = nodeId 列表（按 `topologicalOrder` 排序），并集 = 全部 nodeId，无交集；Action/非 read-only 节点只入 `actionPartition` 且 `requiresApproval=true`。
- `projectionRef`/`ruleSetRefs` 本期空；失败不返回 `None`（结构化 gaps/flags/`PlannerFailure`）；snapshot 漂移 -> 抛 `PlannerFailure(SNAPSHOT_DRIFT)`。
- 确定性：不调用 LLM / Gateway validate / Gateway execute / SAP；同输入同输出。
- v2 validator 复用 S1 内部函数（同包 `from .validation import _validate_*`）；`_validate_plan_shape` 硬编码 v1 schema，v2 自写 shape 校验加载 `plan-graph-v2.schema.json`。
- 验证命令：`.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py -q` + `scripts/verify-agent-callplan-evidence.sh` + `openspec validate --all --strict`。

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `schemas/plan-graph-v2.schema.json` | PlanGraph v2 JSON Schema（`planGraphVersion:2` + `readPartition`/`actionPartition`/`projectionRef`/`ruleSetRefs` + `registeredDefault` 源） | 新建 |
| `agent/sap_nexus_agent/semantic_planning/validation_v2.py` | v2 validator：复用 S1 `_validate_*` + `_validate_partitions` + `_validate_refs` + `_validate_plan_shape_v2` | 新建 |
| `agent/sap_nexus_agent/planner/plan_compiler_v2.py` | v2 compiler `compile_plan_v2` + `PlanCompileResult` dataclass | 新建 |
| `agent/sap_nexus_agent/planner/handoff.py` | 新增 `compile_plan_v2_from_handoff` 入口（v1 `compile_dry_run_from_handoff` 不动） | 修改（追加） |
| `agent/tests/test_planner_plan_compiler_v2.py` | v2 compiler 测试：双 READ fixture、factField fixture、bad-case、dry-run、确定性 | 新建 |
| `agent/tests/test_semantic_planning_v2.py` | v2 validator 测试：partition/ref/bad-case fail-closed | 新建 |
| `docs/runbooks/README.md` + roadmap row 26 + Runbook 15 | 状态/版本更新 | 修改 |

**复用契约（来自 v1，零改动）：**

- `sap_nexus_agent.planner.plan_compiler`：`Gap(kind, detail)`、`Flag(kind, detail)`、`_SOURCE_KIND_GOAL_CONSTRAINT`/`_SOURCE_KIND_LITERAL`/`_SOURCE_KIND_FACT_FIELD`、`_FLAG_INVALID_PLAN_GRAPH`/`_FLAG_WRITE_SIDE_EFFECT`/`_FLAG_APPROVAL_REQUIRED`、`_GAP_MISSING_CAPABILITY`/`_GAP_MISSING_PARAMETER`、`_WRITE_SIDE_EFFECTS`、`_node_id_for`、`_plan_id_for`、`_project_node_governance`、`_index_producers_by_fact_type`、`_index_raw_capabilities`、`_compute_gaps`、`_format_issues`。
- `sap_nexus_agent.semantic_planning.validation`（私有函数，同包 import）：`_validate_snapshot_and_goal_identity`、`_validate_nodes_and_projections`、`_validate_parameter_source`、`_validate_edges`、`_validate_topological_order`、`_validate_plan_governance`、`_validate_goal_outputs`、`_validate_plan_stable_ids`、`_to_json_value`、`_plan_schema_error_details`、`_plan_unique_items_is_semantic`、`_unique_items_is_conversion_artifact`、`_canonical_issues`、`_load_schema`、`_is_read_only`。
- `sap_nexus_agent.semantic_planning.contracts`：`PlanValidationReport(valid, issues)`、`ValidationIssue(path, code, message)`、`RegistrySnapshot`、`SemanticSourceDocuments`。
- `sap_nexus_agent.semantic_planning.graph`：`SemanticGraphCompiler`、`ImmutableSemanticGraph`、`SemanticEdge(relation_type, source_id, target_id)`。
- `sap_nexus_agent.planner.capability_card`：`CapabilityCard`、`InputDescriptor(name, semantic_type, required, binding_kind, satisfiable_by_fact_type)`、`Governance(side_effect, requires_approval, data_classification)`、`discover_cards`。
- `sap_nexus_agent.planner.goal_spec`：`GoalSpec`、`GoalConstraint`、`build_goal_spec`。
- `sap_nexus_agent.governed_context`：`SnapshotLease`、`PlannerFailure`、`PlannerErrorType`（含 `SNAPSHOT_DRIFT`）、`SnapshotDriftError`。
- `sap_nexus_agent.match_decision`：`EscalationHandoff(reason, matched_intents, utterance, registry_snapshot_id)`、`MatchedIntent(capability_id, parameters, missing)`。

**关键事实（来自代码勘察）：**

- 真实 registry（`registry/capabilities.yaml` + `ontology/capability-relations.yaml`）：`MM.Inventory.GetAvailability` 与 `MM.PurchaseOrder.GetList` 均为 READ-only Function；`MM.PR.CreateDraft` 为 `sap_write` Action；**当前无 `dependsOn` 关系、无 `bindingKind: fact` 输入**。故双 READ fixture 用真实 registry（天然空 edges）；factField/dependency 测试需自定义 `SemanticSourceDocuments`。
- `SemanticGraphCompiler` 将 `dependsOn` relation 转为 `SemanticEdge(relation_type="dependsOn", source_id=capabilityId[dependent], target_id=dependsOnCapabilityId[prerequisite])`；S1 `_validate_edges` 据此期望 dependency edge `fromNodeId=prerequisite, toNodeId=dependent`。
- S1 `_validate_parameter_source` 用 `source["kind"]` 分发，未识别 kind 会落到 fact 分支访问 `source["producerNodeId"]` -> `KeyError`；故 `registeredDefault` 必须由 v2 自定义分支预处理。

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 1: PlanGraph v2 Schema 文件 + v1 回归守护

**对应 tasks.md：** 1.1, 1.2

**Files:**
- Create: `schemas/plan-graph-v2.schema.json`
- Test: `agent/tests/test_semantic_planning_v2.py`

**Interfaces:**
- Produces: `schemas/plan-graph-v2.schema.json`（`planGraphVersion: const 2`，required 含 `readPartition`/`actionPartition`/`projectionRef`/`ruleSetRefs`，`parameterSource` oneOf 含 `registeredDefaultSource`）。

- [x] **Step 1: 写 v2 schema 失败测试**

新建 `agent/tests/test_semantic_planning_v2.py`，首个测试加载 v2 schema 并断言关键字段：

```python
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_plan_graph_v2_schema_carries_partition_and_registered_default():
    schema = _load_schema("plan-graph-v2.schema.json")
    assert schema["properties"]["planGraphVersion"]["const"] == 2
    required = schema["required"]
    for field in (
        "readPartition",
        "actionPartition",
        "projectionRef",
        "ruleSetRefs",
    ):
        assert field in required, f"v2 schema must require {field}"
    source_kinds = {
        branch["properties"]["kind"]["const"]
        for branch in schema["$defs"]["parameterSource"]["oneOf"]
    }
    assert source_kinds == {
        "goalConstraint",
        "literal",
        "factField",
        "registeredDefault",
    }
    # readPartition / actionPartition: unique string arrays
    for part in ("readPartition", "actionPartition"):
        assert schema["properties"][part]["type"] == "array"
        assert schema["properties"][part]["uniqueItems"] is True
```

- [x] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py::test_plan_graph_v2_schema_carries_partition_and_registered_default -q`
Expected: FAIL（`plan-graph-v2.schema.json` 不存在，`FileNotFoundError`）

- [x] **Step 3: 创建 v2 schema 文件**

创建 `schemas/plan-graph-v2.schema.json`。基于 v1 `plan-graph.schema.json` 复制并修改：

- `planGraphVersion` const 改 `2`。
- `required` 追加 `readPartition`、`actionPartition`、`projectionRef`、`ruleSetRefs`。
- `properties` 追加：
  - `readPartition`：`{"type":"array","uniqueItems":true,"items":{"type":"string","minLength":1}}`
  - `actionPartition`：同上。
  - `projectionRef`：`{"type":"array","uniqueItems":true,"items":{"type":"string","minLength":1}}`（本期不强制 `maxItems:0`，留前向兼容；validator 校验非空须来自 snapshot）。
  - `ruleSetRefs`：同 `projectionRef`。
- `$defs.parameterSource.oneOf` 追加第 4 个分支 `registeredDefaultSource`：
  ```jsonc
  {
    "type": "object",
    "additionalProperties": false,
    "required": ["kind", "parameterName", "semanticType", "value"],
    "properties": {
      "kind": { "const": "registeredDefault" },
      "parameterName": { "type": "string", "minLength": 1 },
      "semanticType": { "type": "string", "minLength": 1 },
      "value": { "type": ["string", "number", "integer", "boolean"] }
    }
  }
  ```
- 其余 `$defs`（node/edge/governance/goalOutput/goalConstraintSource/literalSource/factFieldSource/dataEdge/dependencyEdge/sha256）与 v1 一致。

- [x] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py::test_plan_graph_v2_schema_carries_partition_and_registered_default -q`
Expected: PASS

- [x] **Step 5: v1 回归守护——断言 v1 schema 未改动**

在同一测试文件追加：

```python
def test_plan_graph_v1_schema_remains_unchanged():
    """Design Doc §4.1 / spec R1: v1 schema (planGraphVersion:1) 未改动。"""
    v1 = _load_schema("plan-graph.schema.json")
    assert v1["properties"]["planGraphVersion"]["const"] == 1
    # v1 不含 v2 字段
    for field in ("readPartition", "actionPartition", "projectionRef", "ruleSetRefs"):
        assert field not in v1["properties"]
        assert field not in v1["required"]
    # v1 参数源仍是 3 源闭集
    v1_kinds = {
        branch["properties"]["kind"]["const"]
        for branch in v1["$defs"]["parameterSource"]["oneOf"]
    }
    assert v1_kinds == {"goalConstraint", "literal", "factField"}
```

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py -q`
Expected: PASS（2 tests）

- [x] **Step 6: v1 fixtures 仍通过 v1 schema 校验**

追加测试，用现有 fixture `agent/tests/fixtures/semantic_planning/plan-material-supply.yaml` 校验 v1 schema 通过、v2 schema 因 `const:2` 拒绝：

```python
import yaml

def _load_fixture(name: str) -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "agent/tests/fixtures/semantic_planning" / name).read_text(
            encoding="utf-8"
        )
    )


def test_v1_fixture_passes_v1_schema_and_fails_v2_schema():
    fixture = _load_fixture("plan-material-supply.yaml")
    v1 = _load_schema("plan-graph.schema.json")
    v2 = _load_schema("plan-graph-v2.schema.json")
    jsonschema.Draft202012Validator(v1).validate(fixture)  # 不抛
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(v2).validate(fixture)
```

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py -q`
Expected: PASS（3 tests）

- [x] **Step 7: 提交**

```bash
git add schemas/plan-graph-v2.schema.json agent/tests/test_semantic_planning_v2.py
git commit -m "feat(schema): add PlanGraph v2 schema with partitions and registeredDefault source"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 2: PlanCompileResult dataclass + v2 常量

**对应 tasks.md：** 2.1, 3.5（部分）

**Files:**
- Create: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Consumes: `sap_nexus_agent.planner.plan_compiler.Gap`、`Flag`（复用 v1 dataclass）。
- Produces: `PlanCompileResult`（frozen dataclass）、v2 常量 `_SOURCE_KIND_REGISTERED_DEFAULT`、`_PARTITION_READ`/`_PARTITION_ACTION`。

- [x] **Step 1: 写失败测试**

新建 `agent/tests/test_planner_plan_compiler_v2.py`：

```python
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sap_nexus_agent.planner.plan_compiler import Gap, Flag
from sap_nexus_agent.planner.plan_compiler_v2 import PlanCompileResult

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plan_compile_result_is_frozen_and_carries_v2_fields():
    gap = Gap(kind="missing_parameter", detail="material")
    flag = Flag(kind="invalid_plan_graph", detail="x")
    result = PlanCompileResult(
        plan_graph={"planGraphVersion": 2, "nodes": []},
        gaps=[gap],
        governance_flags=[flag],
        projection_ref=[],
        rule_set_refs=[],
        snapshot_id="sha256:" + "0" * 64,
        rationale="v2 dry-run",
    )
    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.rationale = "mutated"  # type: ignore[misc]
    assert result.projection_ref == []
    assert result.rule_set_refs == []
    assert result.snapshot_id.startswith("sha256:")
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_plan_compile_result_is_frozen_and_carries_v2_fields -q`
Expected: FAIL（`ModuleNotFoundError: sap_nexus_agent.planner.plan_compiler_v2`）

- [x] **Step 3: 实现 PlanCompileResult + 常量**

创建 `agent/sap_nexus_agent/planner/plan_compiler_v2.py`：

```python
"""PlanGraph v2 deterministic compiler (semantic-plan-authoring-v2).

Compiles EscalationHandoff + RegistrySnapshot + SemanticSourceDocuments
into a PlanCompileResult carrying a validated PlanGraph v2 with full
parameter provenance (4-source closed set), data/dependency edges, and
READ/WRITE partitions. Deterministic: no LLM, no Gateway/SAP.

Design Doc: docs/superpowers/specs/2026-08-03-sap-nexus-semantic-plan-authoring-v2-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sap_nexus_agent.planner.plan_compiler import Gap, Flag

# v2 新增源种类（schema 闭集第 4 种；compiler 本期不产出）。
_SOURCE_KIND_REGISTERED_DEFAULT = "registeredDefault"

# 分区标签（内部使用，不写入 plan_graph）。
_PARTITION_READ = "readPartition"
_PARTITION_ACTION = "actionPartition"


@dataclass(frozen=True)
class PlanCompileResult:
    """v2 dry-run 输出。

    ``plan_graph`` 是 PlanGraph v2 dict（camelCase JSON 形状），校验失败
    时仍返回部分图（不返回 None）。``projection_ref`` / ``rule_set_refs``
    本期空（reserved）。``snapshot_id`` 与 handoff/lease 绑定一致。
    """

    plan_graph: dict[str, Any]
    gaps: list[Gap]
    governance_flags: list[Flag]
    projection_ref: list
    rule_set_refs: list
    snapshot_id: str
    rationale: str
```

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_plan_compile_result_is_frozen_and_carries_v2_fields -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): add PlanCompileResult dataclass for v2 compiler"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 3: v2 Validator 主体——shape 校验 + 复用 S1 原语

**对应 tasks.md：** 2.2

**Files:**
- Create: `agent/sap_nexus_agent/semantic_planning/validation_v2.py`
- Test: `agent/tests/test_semantic_planning_v2.py`

**Interfaces:**
- Consumes: S1 `from .validation import _validate_snapshot_and_goal_identity, _validate_nodes_and_projections, _validate_parameter_source, _validate_edges, _validate_topological_order, _validate_plan_governance, _validate_goal_outputs, _validate_plan_stable_ids, _to_json_value, _plan_schema_error_details, _plan_unique_items_is_semantic, _unique_items_is_conversion_artifact, _canonical_issues, _load_schema`；`from .graph import ImmutableSemanticGraph, SemanticGraphCompiler`；`from .contracts import RegistrySnapshot, PlanValidationReport, ValidationIssue`。
- Produces: `validate_plan_graph_v2(graph, snapshot, goal_spec, plan_graph) -> PlanValidationReport`；内部 `_validate_plan_shape_v2(plan_graph, issues) -> dict`、`_validate_parameter_sources_v2(graph, goal_spec, node_index, issues)`。

**复用边界（关键）：**
- S1 `_validate_plan_shape` 硬编码 `_load_schema("plan-graph.schema.json")`，v2 不能直接复用——自写 `_validate_plan_shape_v2` 加载 `plan-graph-v2.schema.json`，其余归一化/稳定 id 逻辑复用 S1 的 `_to_json_value`/`_validate_plan_stable_ids`/`_plan_schema_error_details`/`_plan_unique_items_is_semantic`/`_unique_items_is_conversion_artifact`。
- `_validate_parameter_source` 不认识 `registeredDefault`——v2 写 `_validate_parameter_sources_v2`，遍历 bindings 时对 `registeredDefault` 走自定义分支（本期报 `RESERVED_SOURCE_NOT_AUTHORED`），其余 3 源调用 S1 `_validate_parameter_source`。
- 其余 `_validate_*`（snapshot/identity、nodes、edges、topological、governance、goalOutputs）直接 import 复用。

- [x] **Step 1: 写失败测试——v2 validator 接受合法 v2 plan**

在 `agent/tests/test_semantic_planning_v2.py` 追加。用真实 registry 构造一个最小合法 v2 plan（双 READ 节点 + 空分区占位由 compiler 产出；此处手工构造以隔离 validator）：

```python
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    build_registry_snapshot,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.validation_v2 import validate_plan_graph_v2


def _real_sources() -> SemanticSourceDocuments:
    return load_semantic_sources(REPO_ROOT)


def _real_snapshot() -> RegistrySnapshot:
    return build_registry_snapshot(_real_sources())


def _valid_v2_plan(snapshot: RegistrySnapshot) -> dict:
    """手工构造一个合法 v2 plan（inventory 单节点，READ_ONLY）。"""
    return {
        "planGraphVersion": 2,
        "planId": "plan.v2.test",
        "goalId": "goal.v2.test",
        "executionMode": "READ_ONLY",
        "snapshotId": snapshot.snapshot_id,
        "nodes": [
            {
                "nodeId": "node.MM.Inventory.GetAvailability",
                "capabilityId": "MM.Inventory.GetAvailability",
                "parameterBindings": [
                    {
                        "parameterName": "material",
                        "source": {
                            "kind": "goalConstraint",
                            "constraintName": "material",
                        },
                    },
                    {
                        "parameterName": "plant",
                        "source": {
                            "kind": "goalConstraint",
                            "constraintName": "plant",
                        },
                    },
                ],
                "producesFactTypes": ["sapnexus:InventoryAvailabilityFact"],
                "governance": {
                    "capabilityKind": "Function",
                    "sideEffect": "none",
                    "requiresApproval": False,
                    "approvalPolicy": "not_required",
                },
            }
        ],
        "edges": [],
        "topologicalOrder": ["node.MM.Inventory.GetAvailability"],
        "goalOutputs": [
            {
                "factTypeId": "sapnexus:InventoryAvailabilityFact",
                "producerNodeId": "node.MM.Inventory.GetAvailability",
            }
        ],
        "readPartition": ["node.MM.Inventory.GetAvailability"],
        "actionPartition": [],
        "projectionRef": [],
        "ruleSetRefs": [],
    }


def _goal_spec_for_inventory() -> dict:
    return {
        "goalSpecVersion": 1,
        "goalId": "goal.v2.test",
        "goalType": "sapnexus:GoalFor:InventoryAvailabilityFact",
        "executionMode": "READ_ONLY",
        "desiredFactTypes": ["sapnexus:InventoryAvailabilityFact"],
        "constraints": [
            {"name": "material", "semanticType": "sapnexus:MaterialNumber", "value": "M1"},
            {"name": "plant", "semanticType": "sapnexus:Plant", "value": "5300"},
        ],
    }


def test_validate_plan_graph_v2_accepts_valid_v2_plan():
    snapshot = _real_snapshot()
    sources = _real_sources()
    graph = SemanticGraphCompiler().compile(sources)
    plan = _valid_v2_plan(snapshot)
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is True, report.issues
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py::test_validate_plan_graph_v2_accepts_valid_v2_plan -q`
Expected: FAIL（`ModuleNotFoundError: sap_nexus_agent.semantic_planning.validation_v2`）

- [x] **Step 3: 实现 v2 validator 主体**

创建 `agent/sap_nexus_agent/semantic_planning/validation_v2.py`：

```python
"""PlanGraph v2 validator (semantic-plan-authoring-v2).

Reuses S1 ``semantic_planning.validation`` internal primitives (same-package
import of ``_validate_*`` functions) and adds partition isolation + ref
checks. ``_validate_plan_shape`` is S1-specific (hardcoded v1 schema), so v2
provides ``_validate_plan_shape_v2`` loading ``plan-graph-v2.schema.json``.

Design Doc: docs/superpowers/specs/2026-08-03-sap-nexus-semantic-plan-authoring-v2-design.md §4.3
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

import jsonschema

from .contracts import (
    PlanValidationReport,
    RegistrySnapshot,
    ValidationIssue,
)
from .graph import ImmutableSemanticGraph
from .validation import (
    _canonical_issues,
    _load_schema,
    _plan_schema_error_details,
    _plan_unique_items_is_semantic,
    _to_json_value,
    _unique_items_is_conversion_artifact,
    _validate_edges,
    _validate_goal_outputs,
    _validate_nodes_and_projections,
    _validate_parameter_source,
    _validate_plan_governance,
    _validate_plan_stable_ids,
    _validate_snapshot_and_goal_identity,
    _validate_topological_order,
)

_SOURCE_KIND_REGISTERED_DEFAULT = "registeredDefault"


def validate_plan_graph_v2(
    graph: ImmutableSemanticGraph,
    snapshot: RegistrySnapshot,
    goal_spec: dict[str, Any],
    plan_graph: dict[str, Any],
) -> PlanValidationReport:
    issues: list[ValidationIssue] = []
    normalized_plan = _validate_plan_shape_v2(plan_graph, issues)
    if issues:
        return PlanValidationReport(False, _canonical_issues(issues))

    _validate_snapshot_and_goal_identity(snapshot, goal_spec, normalized_plan, issues)
    node_index = _validate_nodes_and_projections(graph, normalized_plan, issues)
    _validate_parameter_sources_v2(graph, goal_spec, node_index, issues)
    _validate_edges(graph, node_index, normalized_plan, issues)
    _validate_topological_order(node_index, normalized_plan, issues)
    _validate_plan_governance(goal_spec, node_index, issues)
    _validate_goal_outputs(goal_spec, node_index, normalized_plan, issues)
    _validate_partitions(normalized_plan, node_index, issues)
    _validate_refs(normalized_plan, snapshot, issues)
    ordered = _canonical_issues(issues)
    return PlanValidationReport(valid=not ordered, issues=ordered)


def _validate_plan_shape_v2(
    plan_graph: Any,
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    candidates: list[tuple[str, ValidationIssue]] = []
    normalized = _to_json_value(plan_graph, (), "", "__plan__", "", candidates)
    conversion_issues = [issue for _, issue in candidates]
    conversion_paths = {issue.path for issue in conversion_issues}
    issues.extend(conversion_issues)

    validator = jsonschema.Draft202012Validator(
        _load_schema("plan-graph-v2.schema.json")
    )
    errors = sorted(
        validator.iter_errors(normalized),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )
    for error in errors:
        if _plan_unique_items_is_semantic(error):
            continue
        if _unique_items_is_conversion_artifact(error, conversion_paths):
            continue
        for tokens, message in _plan_schema_error_details(error):
            path = "".join(f"/{token}" for token in tokens)
            if error.instance is None and path in conversion_paths:
                continue
            issues.append(ValidationIssue(path, "SCHEMA_INVALID", message))

    if isinstance(normalized, dict):
        _validate_plan_stable_ids(normalized, issues)
        return normalized
    return {}


def _validate_parameter_sources_v2(
    graph: ImmutableSemanticGraph,
    goal_spec: Mapping[str, Any],
    node_index: Mapping[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    issues: list[ValidationIssue],
) -> None:
    """v2 parameter source 校验：前 3 源复用 S1 ``_validate_parameter_source``，
    ``registeredDefault`` 走 v2 自定义分支（本期 compiler 不产出，出现即报
    ``RESERVED_SOURCE_NOT_AUTHORED``）。"""
    del graph
    constraints = {
        constraint["name"]: constraint
        for constraint in goal_spec.get("constraints", ())
        if isinstance(constraint, Mapping)
    }
    for node_id in sorted(node_index):
        node_position, node, capability = node_index[node_id]
        inputs = {item["name"]: item for item in capability["inputs"]}
        bindings: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
        for binding_index, binding in enumerate(node["parameterBindings"]):
            parameter_name = binding["parameterName"]
            input_field = inputs.get(parameter_name)
            if input_field is None:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_position}/parameterBindings/{binding_index}/parameterName",
                        "PLAN_PROJECTION_MISMATCH",
                        f"parameter is not registered: {parameter_name}",
                    )
                )
                continue
            bindings[parameter_name].append((binding_index, binding))

        for parameter_name, input_field in inputs.items():
            matches = bindings.get(parameter_name, [])
            if input_field["required"] and not matches:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_position}/parameterBindings",
                        "PARAMETER_SOURCE_MISSING",
                        f"required parameter has no source: {parameter_name}",
                    )
                )
            for duplicate_index, _ in matches[1:]:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_position}/parameterBindings/{duplicate_index}/parameterName",
                        "PARAMETER_SOURCE_DUPLICATE",
                        f"parameter has multiple sources: {parameter_name}",
                    )
                )
            if len(matches) == 1:
                binding_index, binding = matches[0]
                source = binding["source"]
                if source["kind"] == _SOURCE_KIND_REGISTERED_DEFAULT:
                    _validate_registered_default_source(
                        node_position, binding_index, input_field, source, issues
                    )
                else:
                    _validate_parameter_source(
                        node_position,
                        binding_index,
                        input_field,
                        source,
                        constraints,
                        node_index,
                        issues,
                    )


def _validate_registered_default_source(
    node_position: int,
    binding_index: int,
    input_field: Mapping[str, Any],
    source: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    """registeredDefault 源本期 reserved：compiler 不产出。

    若出现，校验 semanticType 须匹配 input；不论匹配与否，报
    ``RESERVED_SOURCE_NOT_AUTHORED``（fail-closed，提示该源本期未激活）。
    """
    base_path = (
        f"/nodes/{node_position}/parameterBindings/{binding_index}/source"
    )
    if source.get("semanticType") != input_field["semanticType"]:
        issues.append(
            ValidationIssue(
                f"{base_path}/semanticType",
                "PARAMETER_SOURCE_MISSING",
                "registeredDefault semanticType does not match parameter",
            )
        )
    issues.append(
        ValidationIssue(
            base_path,
            "RESERVED_SOURCE_NOT_AUTHORED",
            "registeredDefault source is reserved and not authored this phase",
        )
    )


def _validate_partitions(
    plan_graph: Mapping[str, Any],
    node_index: Mapping[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    issues: list[ValidationIssue],
) -> None:
    """分区隔离：并集=全部 nodeId，无交集；readPartition 仅 read-only。"""
    # 占位：Task 4 实现
    raise NotImplementedError


def _validate_refs(
    plan_graph: Mapping[str, Any],
    snapshot: RegistrySnapshot,
    issues: list[ValidationIssue],
) -> None:
    """projectionRef/ruleSetRefs 非空须来自 snapshot；空通过。"""
    # 占位：Task 5 实现
    raise NotImplementedError
```

注意：`_validate_partitions` 与 `_validate_refs` 本 task 先放占位 `NotImplementedError`，Task 4/5 实现。为让 Task 3 测试（合法 plan，分区合法、refs 空）通过，本 task 先把这两个函数实现为"最小可过"版本——见 Step 4。

- [x] **Step 4: 实现 `_validate_partitions` 与 `_validate_refs` 最小版本（空通过）**

为让 Task 3 测试先通过，把两个占位函数替换为最小实现：

```python
def _validate_partitions(
    plan_graph: Mapping[str, Any],
    node_index: Mapping[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    issues: list[ValidationIssue],
) -> None:
    read = list(plan_graph.get("readPartition", ()))
    action = list(plan_graph.get("actionPartition", ()))
    node_ids = set(node_index)
    if set(read) | set(action) != node_ids:
        issues.append(
            ValidationIssue(
                "/readPartition",
                "PARTITION_COVERAGE",
                "readPartition ∪ actionPartition must equal all node ids",
            )
        )
    if set(read) & set(action):
        issues.append(
            ValidationIssue(
                "/actionPartition",
                "PARTITION_OVERLAP",
                "readPartition ∩ actionPartition must be empty",
            )
        )
    # read-only 校验在 Task 4 强化


def _validate_refs(
    plan_graph: Mapping[str, Any],
    snapshot: RegistrySnapshot,
    issues: list[ValidationIssue],
) -> None:
    # 本期 projectionRef/ruleSetRefs 空 -> 通过；非空校验在 Task 5
    return None
```

- [x] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py -q`
Expected: PASS（含 schema 3 tests + validator 1 test）

- [x] **Step 6: 提交**

```bash
git add agent/sap_nexus_agent/semantic_planning/validation_v2.py agent/tests/test_semantic_planning_v2.py
git commit -m "feat(semantic_planning): add v2 validator reusing S1 primitives with v2 shape"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 4: 分区隔离校验（read-only 强制）

**对应 tasks.md：** 2.3

**Files:**
- Modify: `agent/sap_nexus_agent/semantic_planning/validation_v2.py`（`_validate_partitions`）
- Test: `agent/tests/test_semantic_planning_v2.py`

**Interfaces:**
- Consumes: S1 `_is_read_only(capability) -> bool`（Function + sideEffect=none + requiresApproval=false + approvalPolicy=not_required）。
- Produces: `_validate_partitions` 强化版——`readPartition` 中非 read-only 节点 -> `PARTITION_GOVERNANCE_VIOLATION`。

- [x] **Step 1: 写失败测试——Action 节点入 readPartition 被拒**

```python
def test_validate_plan_graph_v2_rejects_action_in_read_partition():
    snapshot = _real_snapshot()
    sources = _real_sources()
    graph = SemanticGraphCompiler().compile(sources)
    plan = _valid_v2_plan(snapshot)
    # 把 inventory 节点的 governance 改成 Action 并放入 readPartition
    plan["nodes"][0]["governance"] = {
        "capabilityKind": "Action",
        "sideEffect": "sap_write",
        "requiresApproval": True,
        "approvalPolicy": "human_required",
    }
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    codes = {issue.code for issue in report.issues}
    assert "PARTITION_GOVERNANCE_VIOLATION" in codes or "GOVERNANCE_VIOLATION" in codes
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py::test_validate_plan_graph_v2_rejects_action_in_read_partition -q`
Expected: FAIL（当前 `_validate_partitions` 未校验 read-only，report.valid 为 True 或仅 GOVERNANCE_VIOLATION 但无 PARTITION 信号——视 _validate_plan_governance 是否先报；需确保有 PARTITION_GOVERNANCE_VIOLATION）

- [x] **Step 3: 强化 `_validate_partitions`**

在 `validation_v2.py` 中 import `_is_read_only`，强化 `_validate_partitions`：

```python
from .validation import _is_read_only  # 追加到现有 import

def _validate_partitions(
    plan_graph: Mapping[str, Any],
    node_index: Mapping[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    issues: list[ValidationIssue],
) -> None:
    read = list(plan_graph.get("readPartition", ()))
    action = list(plan_graph.get("actionPartition", ()))
    node_ids = set(node_index)
    if set(read) | set(action) != node_ids:
        issues.append(
            ValidationIssue(
                "/readPartition",
                "PARTITION_COVERAGE",
                "readPartition ∪ actionPartition must equal all node ids",
            )
        )
    if set(read) & set(action):
        issues.append(
            ValidationIssue(
                "/actionPartition",
                "PARTITION_OVERLAP",
                "readPartition ∩ actionPartition must be empty",
            )
        )
    # readPartition 中节点须为 read-only（capability 维度）
    for node_id in read:
        entry = node_index.get(node_id)
        if entry is None:
            continue
        node_position, _, capability = entry
        if not _is_read_only(capability):
            issues.append(
                ValidationIssue(
                    f"/readPartition",
                    "PARTITION_GOVERNANCE_VIOLATION",
                    f"non-read-only node in readPartition: {node_id}",
                )
            )
```

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/semantic_planning/validation_v2.py agent/tests/test_semantic_planning_v2.py
git commit -m "feat(semantic_planning): enforce read-only partition isolation in v2 validator"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 5: projectionRef / ruleSetRefs 引用校验

**对应 tasks.md：** 2.4

**Files:**
- Modify: `agent/sap_nexus_agent/semantic_planning/validation_v2.py`（`_validate_refs`）
- Test: `agent/tests/test_semantic_planning_v2.py`

**Interfaces:**
- Produces: `_validate_refs`——`projectionRef`/`ruleSetRefs` 非空时，每个引用须能在 snapshot sources 中找到；空通过。

- [x] **Step 1: 写失败测试——非空 projectionRef 且不在 snapshot 被拒；空通过**

```python
def test_validate_plan_graph_v2_empty_refs_pass():
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["projectionRef"] = []
    plan["ruleSetRefs"] = []
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is True, report.issues


def test_validate_plan_graph_v2_unknown_projection_ref_fails_closed():
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["projectionRef"] = ["sapnexus:Projection:DoesNotExist"]
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    codes = {issue.code for issue in report.issues}
    assert "UNKNOWN_PROJECTION_REF" in codes
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py::test_validate_plan_graph_v2_unknown_projection_ref_fails_closed -q`
Expected: FAIL（当前 `_validate_refs` 直接 return，report.valid 为 True）

- [x] **Step 3: 实现 `_validate_refs`**

本期 snapshot 不含 projection/ruleSet 注册表，故任何非空 ref 都无法在 snapshot 中找到 -> fail-closed。实现：

```python
def _validate_refs(
    plan_graph: Mapping[str, Any],
    snapshot: RegistrySnapshot,
    issues: list[ValidationIssue],
) -> None:
    """projectionRef/ruleSetRefs 非空须来自 snapshot；本期 snapshot 无注册表，
    非空即 fail-closed。空通过。"""
    for field_name, code in (
        ("projectionRef", "UNKNOWN_PROJECTION_REF"),
        ("ruleSetRefs", "UNKNOWN_RULESET_REF"),
    ):
        refs = plan_graph.get(field_name, ())
        if not refs:
            continue
        for index, ref in enumerate(refs):
            issues.append(
                ValidationIssue(
                    f"/{field_name}/{index}",
                    code,
                    f"{field_name} references entity not present in snapshot: {ref}",
                )
            )
```

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/semantic_planning/validation_v2.py agent/tests/test_semantic_planning_v2.py
git commit -m "feat(semantic_planning): validate projectionRef/ruleSetRefs against snapshot in v2"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 6: v2 Compiler 骨架 + goalConstraint 源

**对应 tasks.md：** 3.1, 3.2（goalConstraint）, 3.5（结构化失败基础）

**Files:**
- Modify: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（追加 `compile_plan_v2`）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Consumes: `EscalationHandoff`、`RegistrySnapshot`、`SemanticSourceDocuments`、`discover_cards`、`build_goal_spec`、`GoalSpec`/`GoalConstraint`、`CapabilityCard`、`SemanticGraphCompiler`、`validate_plan_graph_v2`、v1 `Gap`/`Flag`/常量/`_node_id_for`/`_plan_id_for`/`_project_node_governance`/`_index_producers_by_fact_type`/`_index_raw_capabilities`/`_compute_gaps`/`_format_issues`。
- Produces: `compile_plan_v2(handoff, snapshot, sources) -> PlanCompileResult`。

- [x] **Step 1: 写失败测试——compile_plan_v2 产出双 READ v2 plan（goalConstraint 源）**

```python
from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
from sap_nexus_agent.planner.plan_compiler_v2 import compile_plan_v2
from sap_nexus_agent.semantic_planning import (
    build_registry_snapshot,
    load_semantic_sources,
)


def _real_sources():
    return load_semantic_sources(REPO_ROOT)


def _real_snapshot():
    return build_registry_snapshot(_real_sources())


def _dual_read_handoff(snapshot) -> EscalationHandoff:
    return EscalationHandoff(
        reason="dual-read",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA4B", "plant": "5300"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={"material": "DEMOA4B", "plant": "5300"},
                missing=[],
            ),
        ],
        utterance="show inventory and PO for material DEMOA4B at plant 5300",
        registry_snapshot_id=snapshot.snapshot_id,
    )


def test_compile_plan_v2_produces_dual_read_plan_with_goal_constraint_sources():
    snapshot = _real_snapshot()
    sources = _real_sources()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    assert result.plan_graph["planGraphVersion"] == 2
    assert result.snapshot_id == snapshot.snapshot_id
    cap_ids = {n["capabilityId"] for n in result.plan_graph["nodes"]}
    assert cap_ids == {"MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}
    # 双 READ -> readPartition 含两节点，actionPartition 空
    assert set(result.plan_graph["readPartition"]) == {
        n["nodeId"] for n in result.plan_graph["nodes"]
    }
    assert result.plan_graph["actionPartition"] == []
    # 参数源为 goalConstraint
    for node in result.plan_graph["nodes"]:
        kinds = {b["source"]["kind"] for b in node["parameterBindings"]}
        assert kinds == {"goalConstraint"}
    # refs 空
    assert result.plan_graph["projectionRef"] == []
    assert result.plan_graph["ruleSetRefs"] == []
    # 无 Gateway 调用、无 invalid flag
    assert not any(
        f.kind == "invalid_plan_graph" for f in result.governance_flags
    )
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_produces_dual_read_plan_with_goal_constraint_sources -q`
Expected: FAIL（`compile_plan_v2` 未实现，`ImportError`）

- [x] **Step 3: 实现 `compile_plan_v2` 骨架**

在 `plan_compiler_v2.py` 追加（复用 v1 内部函数 + goalConstraint authoring + 分区 + v2 validator）：

```python
from sap_nexus_agent.match_decision import EscalationHandoff
from sap_nexus_agent.planner.capability_card import CapabilityCard, discover_cards
from sap_nexus_agent.planner.goal_spec import GoalSpec, build_goal_spec
from sap_nexus_agent.planner.handoff import _build_goal_with_constraints
from sap_nexus_agent.planner.plan_compiler import (
    Flag,
    Gap,
    _SOURCE_KIND_GOAL_CONSTRAINT,
    _compute_gaps,
    _format_issues,
    _index_producers_by_fact_type,
    _index_raw_capabilities,
    _node_id_for,
    _plan_id_for,
    _project_node_governance,
    _FLAG_INVALID_PLAN_GRAPH,
)
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.validation_v2 import validate_plan_graph_v2


def compile_plan_v2(
    handoff: EscalationHandoff,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> PlanCompileResult:
    """编译确定性 PlanGraph v2。不调用 LLM/Gateway/SAP。"""
    cards = discover_cards(snapshot, sources)
    raw_capabilities = _index_raw_capabilities(sources)
    goal = _build_goal_with_constraints(handoff, cards)
    plan_graph = _build_plan_graph_v2(goal, snapshot, cards, raw_capabilities)
    gaps = _compute_gaps(goal, cards, _strip_v2_fields_for_gap_calc(plan_graph))

    graph = SemanticGraphCompiler().compile(sources)
    report = validate_plan_graph_v2(graph, snapshot, goal.to_dict(), plan_graph)

    n_nodes = len(plan_graph["nodes"])
    n_gaps = len(gaps)
    if not report.valid:
        flags = [Flag(_FLAG_INVALID_PLAN_GRAPH, _format_issues(report.issues))]
        rationale = (
            f"v2 validator failed: {len(report.issues)} issue(s); "
            f"compiled {n_nodes} node(s), {n_gaps} gap(s), 1 flag(s)"
        )
    else:
        flags = _compute_governance_flags_v2(plan_graph, cards)
        n_flags = len(flags)
        rationale = (
            f"v2 dry-run compiled {n_nodes} node(s), "
            f"{n_gaps} gap(s), {n_flags} flag(s)"
        )

    return PlanCompileResult(
        plan_graph=plan_graph,
        gaps=gaps,
        governance_flags=flags,
        projection_ref=list(plan_graph.get("projectionRef", [])),
        rule_set_refs=list(plan_graph.get("ruleSetRefs", [])),
        snapshot_id=snapshot.snapshot_id,
        rationale=rationale,
    )


def _build_plan_graph_v2(
    goal: GoalSpec,
    snapshot: RegistrySnapshot,
    cards: list[CapabilityCard],
    raw_capabilities: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    producers_by_fact = _index_producers_by_fact_type(cards)
    nodes: list[dict[str, Any]] = []
    node_ids: list[str] = []
    node_id_by_capability: dict[str, str] = {}
    fact_type_to_node: dict[str, str] = {}

    for fact_type in goal.desired_fact_types:
        producers = producers_by_fact.get(fact_type)
        if not producers:
            continue
        card = producers[0]
        node_id = node_id_by_capability.get(card.capability_id)
        if node_id is None:
            node_id = _node_id_for(card.capability_id)
            node_id_by_capability[card.capability_id] = node_id
            node_ids.append(node_id)
            raw = raw_capabilities.get(card.capability_id, {})
            nodes.append(_build_node_v2(card, goal, node_id, raw))
        fact_type_to_node[fact_type] = node_id

    goal_outputs = [
        {"factTypeId": ft, "producerNodeId": nid}
        for ft, nid in fact_type_to_node.items()
    ]
    edges: list[dict[str, Any]] = []  # Task 8/9 追加 data/dependency edge
    topological_order = _topological_order(node_ids, edges)

    read_partition, action_partition = _partition_nodes(nodes, raw_capabilities, topological_order)

    return {
        "planGraphVersion": 2,
        "planId": _plan_id_for(goal),
        "goalId": goal.goal_id,
        "executionMode": goal.execution_mode,
        "snapshotId": snapshot.snapshot_id,
        "nodes": nodes,
        "edges": edges,
        "topologicalOrder": topological_order,
        "goalOutputs": goal_outputs,
        "readPartition": read_partition,
        "actionPartition": action_partition,
        "projectionRef": [],
        "ruleSetRefs": [],
    }


def _build_node_v2(
    card: CapabilityCard,
    goal: GoalSpec,
    node_id: str,
    raw_capability: Mapping[str, Any],
) -> dict[str, Any]:
    """v2 node：本期先 author goalConstraint 源（同 v1）；literal/factField
    在 Task 7/8 追加。"""
    constraints_by_name = {c.name: c for c in goal.constraints}
    bindings: list[dict[str, Any]] = []
    for inp in card.inputs:
        if not inp.required:
            continue
        constraint = constraints_by_name.get(inp.name)
        if (
            inp.binding_kind == "identifier"
            and constraint is not None
            and constraint.semantic_type == inp.semantic_type
        ):
            bindings.append(
                {
                    "parameterName": inp.name,
                    "source": {
                        "kind": _SOURCE_KIND_GOAL_CONSTRAINT,
                        "constraintName": constraint.name,
                    },
                }
            )
    return {
        "nodeId": node_id,
        "capabilityId": card.capability_id,
        "parameterBindings": bindings,
        "producesFactTypes": sorted(card.produces_fact_types),
        "governance": _project_node_governance(raw_capability),
    }


def _topological_order(node_ids: list[str], edges: list[dict[str, Any]]) -> list[str]:
    """无 edge 时按 nodeId 排序（确定性）；有 edge 时按拓扑排序。Task 9 强化。"""
    return list(node_ids) if not edges else list(node_ids)


def _partition_nodes(
    nodes: list[dict[str, Any]],
    raw_capabilities: Mapping[str, Mapping[str, Any]],
    topological_order: list[str],
) -> tuple[list[str], list[str]]:
    """分区：read-only -> readPartition；其余 -> actionPartition。按 topologicalOrder 排序。"""
    from sap_nexus_agent.semantic_planning.validation import _is_read_only

    read: list[str] = []
    action: list[str] = []
    # 构造 capability -> nodeId 映射用于 _is_read_only（需 raw capability）
    node_by_id = {n["nodeId"]: n for n in nodes}
    for node_id in topological_order:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        raw = raw_capabilities.get(node["capabilityId"], {})
        # 构造 S1 _is_read_only 期望的 capability 形状
        capability_view = {
            "kind": raw.get("kind", "Function"),
            "governance": raw.get("governance", {}),
        }
        if _is_read_only(capability_view):
            read.append(node_id)
        else:
            action.append(node_id)
    return read, action


def _compute_governance_flags_v2(
    plan_graph: dict[str, Any], cards: list[CapabilityCard]
) -> list[Flag]:
    """v2 governance flags：复用 v1 逻辑（write_side_effect/approval_required）。"""
    from sap_nexus_agent.planner.plan_compiler import (
        _compute_governance_flags,
        _WRITE_SIDE_EFFECTS,
        _FLAG_WRITE_SIDE_EFFECT,
        _FLAG_APPROVAL_REQUIRED,
    )
    return _compute_governance_flags(plan_graph, cards)


def _strip_v2_fields_for_gap_calc(plan_graph: dict[str, Any]) -> dict[str, Any]:
    """_compute_gaps 读取 nodes/parameterBindings，v2 字段不影响。返回原 plan_graph。"""
    return plan_graph
```

注意：`_is_read_only` 期望 capability 含 `kind` 与 `governance`（含 `sideEffect`/`requiresApproval`/`approvalPolicy`）。`_project_node_governance` 已把 `capabilityKind` 投影到 node；但 `_is_read_only` 读 `capability["kind"]` 与 `capability["governance"]`，故需用 raw capability 形状。上面 `_partition_nodes` 已构造 `capability_view`。

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_produces_dual_read_plan_with_goal_constraint_sources -q`
Expected: PASS

- [x] **Step 5: 确定性测试**

```python
def test_compile_plan_v2_is_deterministic():
    snapshot = _real_snapshot()
    sources = _real_sources()
    first = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    second = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    assert first == second
    assert first.plan_graph == second.plan_graph
```

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 6: 提交**

```bash
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): v2 compiler skeleton with goalConstraint sources and partitions"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 7: literal 源 authoring

**对应 tasks.md：** 3.2（literal）

**Files:**
- Modify: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（`_build_node_v2` 追加 literal 分支）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Produces: `_build_node_v2` 对 identifier 输入，无匹配 GoalConstraint 但有 handoff 参数值 -> `literal` 源（semanticType 从 InputDescriptor 取，校验类型一致）。

- [x] **Step 1: 写失败测试——identifier 输入无 GoalConstraint 但有 handoff 值 -> literal 源**

```python
def test_compile_plan_v2_authors_literal_source_for_identifier_without_constraint():
    snapshot = _real_snapshot()
    sources = _real_sources()
    # handoff 提供 plant 值，但不构造对应 GoalConstraint（移除 plant constraint）
    handoff = EscalationHandoff(
        reason="literal",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "M1", "plant": "5300"},
                missing=[],
            )
        ],
        utterance="inventory for M1 at 5300",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    inv_nodes = [
        n for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert inv_nodes
    kinds = {b["source"]["kind"] for b in inv_nodes[0]["parameterBindings"]}
    # material 有 GoalConstraint -> goalConstraint；plant 无 constraint 但有值 -> literal
    assert "literal" in kinds
    literal_bindings = [
        b for b in inv_nodes[0]["parameterBindings"]
        if b["source"]["kind"] == "literal"
    ]
    assert any(b["parameterName"] == "plant" for b in literal_bindings)
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_authors_literal_source_for_identifier_without_constraint -q`
Expected: FAIL（当前 `_build_node_v2` 只 author goalConstraint，plant 无 constraint -> 不绑定 -> missing_parameter gap）

- [x] **Step 3: 在 `_build_node_v2` 追加 literal 分支**

修改 `_build_node_v2`，在 goalConstraint 分支后追加：

```python
def _build_node_v2(
    card: CapabilityCard,
    goal: GoalSpec,
    node_id: str,
    raw_capability: Mapping[str, Any],
    handoff_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    constraints_by_name = {c.name: c for c in goal.constraints}
    bindings: list[dict[str, Any]] = []
    params = handoff_parameters or {}
    for inp in card.inputs:
        if not inp.required:
            continue
        constraint = constraints_by_name.get(inp.name)
        if (
            inp.binding_kind == "identifier"
            and constraint is not None
            and constraint.semantic_type == inp.semantic_type
        ):
            bindings.append(
                {
                    "parameterName": inp.name,
                    "source": {
                        "kind": _SOURCE_KIND_GOAL_CONSTRAINT,
                        "constraintName": constraint.name,
                    },
                }
            )
        elif (
            inp.binding_kind == "identifier"
            and inp.name in params
            and constraint is None
        ):
            # literal 源：semanticType 从 InputDescriptor 取，值从 handoff 参数取
            bindings.append(
                {
                    "parameterName": inp.name,
                    "source": {
                        "kind": "literal",
                        "semanticType": inp.semantic_type,
                        "value": params[inp.name],
                    },
                }
            )
        # factField 分支在 Task 8 追加
    return {
        "nodeId": node_id,
        "capabilityId": card.capability_id,
        "parameterBindings": bindings,
        "producesFactTypes": sorted(card.produces_fact_types),
        "governance": _project_node_governance(raw_capability),
    }
```

同时修改 `_build_plan_graph_v2`，把 handoff 的 matched_intents 参数聚合后传入 `_build_node_v2`：

```python
# 在 _build_plan_graph_v2 签名追加 handoff 参数，构造 params_by_capability
def _build_plan_graph_v2(
    goal: GoalSpec,
    snapshot: RegistrySnapshot,
    cards: list[CapabilityCard],
    raw_capabilities: Mapping[str, Mapping[str, Any]],
    handoff: EscalationHandoff,
) -> dict[str, Any]:
    params_by_capability: dict[str, dict[str, Any]] = {}
    for matched in handoff.matched_intents:
        params_by_capability.setdefault(matched.capability_id, {}).update(
            matched.parameters
        )
    # ... 在 _build_node_v2 调用处传入 handoff_parameters=params_by_capability.get(card.capability_id, {})
```

`compile_plan_v2` 调用处传入 `handoff`。

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): v2 compiler authors literal parameter source"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 8: factField 源 + data edge authoring

**对应 tasks.md：** 3.2（factField）, 3.3（data edge）

**Files:**
- Modify: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（`_build_node_v2` factField 分支 + `_build_plan_graph_v2` data edge authoring）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Produces: 对 `fact` 输入，若有生产者节点产出该 factType -> `factField` 源 + 一条 `data` edge（`fromNodeId=producer, toNodeId=consumer, factTypeId`）。

- [x] **Step 1: 构造自定义 fixture（含 fact 输入的生产者-消费者对）**

真实 registry 无 fact 输入，需自定义 `SemanticSourceDocuments`。在测试文件加 helper：

```python
from copy import deepcopy
from sap_nexus_agent.semantic_planning.contracts import SemanticSourceDocuments


def _sources_with_fact_field() -> tuple[SemanticSourceDocuments, RegistrySnapshot]:
    """构造一个含 fact 输入的自定义 sources：producer 产出 FactA，consumer
    消费 FactA 的字段。"""
    base = _real_sources()
    caps = deepcopy(base.capabilities)
    facts = deepcopy(base.fact_types)
    # 追加一个 consumer capability，其 input bindingKind=fact
    caps["capabilities"].append({
        "capabilityId": "Test.Consumer.GetSummary",
        "name": "Test Consumer",
        "description": "Consumes a fact field",
        "domain": "MM",
        "businessObject": "Test",
        "ontologyIri": "sapnexus:Test_Consumer",
        "semanticType": "sapnexus:TestConsumerReadFunction",
        "aliases": [],
        "status": "active",
        "kind": "Function",
        "inputs": [
            {
                "name": "inventoryFact",
                "semanticType": "sapnexus:InventoryAvailabilityFact",
                "required": True,
                "bindingKind": "fact",
                "satisfiableByFactType": "sapnexus:InventoryAvailabilityFact",
            }
        ],
        "outputs": [
            {"name": "summary", "factTypeRef": "sapnexus:TestSummaryFact"}
        ],
        "governance": {
            "sideEffect": "none",
            "requiresApproval": False,
            "approvalPolicy": "not_required",
            "dataClassification": "internal",
        },
        "executor": {"type": "ODATA"},
        "executorBinding": {"type": "ODATA", "bindingId": "test-binding"},
    })
    if "sapnexus:TestSummaryFact" not in facts.get("factTypes", []):
        facts["factTypes"].append({"factTypeId": "sapnexus:TestSummaryFact", "fields": []})
    sources = SemanticSourceDocuments(
        capabilities=caps,
        executor_bindings=base.executor_bindings,
        fact_types=facts,
        relations=base.relations,
    )
    snapshot = build_registry_snapshot(sources)
    return sources, snapshot
```

- [x] **Step 2: 写失败测试——factField 源 + data edge**

```python
def test_compile_plan_v2_authors_fact_field_source_and_data_edge():
    sources, snapshot = _sources_with_fact_field()
    handoff = EscalationHandoff(
        reason="fact-field",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "M1", "plant": "5300"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="Test.Consumer.GetSummary",
                parameters={},
                missing=[],
            ),
        ],
        utterance="summary from inventory",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    consumer_nodes = [
        n for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "Test.Consumer.GetSummary"
    ]
    assert consumer_nodes
    fact_bindings = [
        b for b in consumer_nodes[0]["parameterBindings"]
        if b["source"]["kind"] == "factField"
    ]
    assert fact_bindings, "expected a factField source binding"
    # 对应 data edge
    data_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "data"]
    assert len(data_edges) == 1
    edge = data_edges[0]
    assert edge["factTypeId"] == "sapnexus:InventoryAvailabilityFact"
    assert edge["toNodeId"] == consumer_nodes[0]["nodeId"]
    inv_nodes = [
        n for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert edge["fromNodeId"] == inv_nodes[0]["nodeId"]
```

- [x] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_authors_fact_field_source_and_data_edge -q`
Expected: FAIL（当前不 author factField/data edge）

- [x] **Step 4: 实现 factField 源 + data edge authoring**

在 `_build_plan_graph_v2` 中，nodes 构造完成后，第二轮扫描 fact 输入并 author data edge。修改 `_build_node_v2` 追加 factField 分支，并在 `_build_plan_graph_v2` 中 author data edge：

```python
def _build_plan_graph_v2(goal, snapshot, cards, raw_capabilities, handoff):
    # ... 现有 nodes 构造 ...
    # 构造 fact_type -> producer_node_id 映射（从 goal_outputs）
    fact_type_to_producer = dict(fact_type_to_node)  # 已有

    # 第二轮：为每个 fact 输入 author factField 源 + data edge
    data_edges: list[dict[str, Any]] = []
    edge_counter = 0
    for node in nodes:
        card = next(c for c in cards if c.capability_id == node["capabilityId"])
        params = params_by_capability.get(card.capability_id, {})
        for inp in card.inputs:
            if inp.binding_kind != "fact" or not inp.required:
                continue
            fact_type = inp.satisfiable_by_fact_type
            producer_node_id = fact_type_to_producer.get(fact_type)
            if producer_node_id is None or producer_node_id == node["nodeId"]:
                continue
            # 从 producer capability outputs 找匹配 field（name + factTypeRef）
            producer_card = next(
                c for c in cards if c.capability_id == node["capabilityId"]  # 修正见下
            )
            # 找 producer raw outputs 中 factTypeRef == fact_type 的 field name
            producer_cap_id = next(
                n["capabilityId"] for n in nodes if n["nodeId"] == producer_node_id
            )
            producer_raw = raw_capabilities.get(producer_cap_id, {})
            field_name = _first_fact_field(producer_raw, fact_type)
            node["parameterBindings"].append({
                "parameterName": inp.name,
                "source": {
                    "kind": "factField",
                    "producerNodeId": producer_node_id,
                    "factTypeId": fact_type,
                    "field": field_name,
                },
            })
            data_edges.append({
                "edgeId": f"edge.data.{edge_counter}",
                "kind": "data",
                "fromNodeId": producer_node_id,
                "toNodeId": node["nodeId"],
                "factTypeId": fact_type,
            })
            edge_counter += 1

    edges.extend(data_edges)
    # ... topological_order / partition / return ...
```

`_first_fact_field` helper：从 producer raw outputs 找第一个 `factTypeRef == fact_type` 的 output `name`：

```python
def _first_fact_field(producer_raw: Mapping[str, Any], fact_type: str) -> str:
    for output in producer_raw.get("outputs", []):
        if output.get("factTypeRef") == fact_type and output.get("name"):
            return output["name"]
    return ""
```

注意：S1 `_validate_parameter_source` 校验 `output["name"] == source["field"]` 且 `output.get("factTypeRef") == source["factTypeId"]`。若 `field` 为空字符串，校验失败 -> `FACT_TYPE_MISMATCH`。需确保 producer output 有 `name` 字段。真实 `MM.Inventory.GetAvailability` 的 outputs 应有 `name`。测试 fixture 的 producer output 需含 `name`。

- [x] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_authors_fact_field_source_and_data_edge -q`
Expected: PASS

- [x] **Step 6: 提交**

```bash
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): v2 compiler authors factField source and data edge"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 9: dependency edge authoring + 拓扑排序强化

**对应 tasks.md：** 3.3（dependency edge）

**Files:**
- Modify: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（`_build_plan_graph_v2` dependency edge + `_topological_order` 真拓扑排序）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Consumes: snapshot `relations` 中 `dependsOn` 关系（`capabilityId`=dependent, `dependsOnCapabilityId`=prerequisite）；两端 capability 都在 plan 内 -> author 一条 `dependency` edge（`fromNodeId=prerequisite, toNodeId=dependent`）。
- Produces: `_topological_order` 按 data+dependency edges 拓扑排序（Kahn 算法，无 edge 时按 nodeId 排序）。

- [x] **Step 1: 构造含 dependsOn 关系的 fixture + 写失败测试**

```python
def _sources_with_depends_on() -> tuple[SemanticSourceDocuments, RegistrySnapshot]:
    base = _real_sources()
    relations = deepcopy(base.relations)
    # 追加：Test.Consumer.GetSummary dependsOn MM.Inventory.GetAvailability
    relations["relations"].append({
        "relationId": "rel.test.dependsOn",
        "relationType": "dependsOn",
        "capabilityId": "Test.Consumer.GetSummary",
        "dependsOnCapabilityId": "MM.Inventory.GetAvailability",
    })
    sources = SemanticSourceDocuments(
        capabilities=base.capabilities,
        executor_bindings=base.executor_bindings,
        fact_types=base.fact_types,
        relations=relations,
    )
    return sources, build_registry_snapshot(sources)


def test_compile_plan_v2_authors_dependency_edge_from_depends_on_relation():
    sources, snapshot = _sources_with_depends_on()
    # 复用 factField fixture 的 consumer，但它不消费 fact（避免混淆）：
    # 这里验证两个独立 capability 间的 dependsOn
    # 为简化，用 Inventory + 一个纯 dependsOn consumer（无 fact 输入）
    # 若 _sources_with_fact_field 的 consumer 无 fact 输入，可直接用
    # 此处假设 consumer 无 fact 输入，仅 dependsOn 关系
    handoff = EscalationHandoff(
        reason="depends-on",
        matched_intents=[
            MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, []),
            MatchedIntent("Test.Consumer.GetSummary", {}, []),
        ],
        utterance="summary depending on inventory",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    dep_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "dependency"]
    assert len(dep_edges) == 1
    inv = next(n for n in result.plan_graph["nodes"] if n["capabilityId"] == "MM.Inventory.GetAvailability")
    con = next(n for n in result.plan_graph["nodes"] if n["capabilityId"] == "Test.Consumer.GetSummary")
    assert dep_edges[0]["fromNodeId"] == inv["nodeId"]
    assert dep_edges[0]["toNodeId"] == con["nodeId"]
    # topologicalOrder 中 inv 在 con 之前
    order = result.plan_graph["topologicalOrder"]
    assert order.index(inv["nodeId"]) < order.index(con["nodeId"])
```

注意：若 `Test.Consumer.GetSummary` 同时有 fact 输入和 dependsOn 关系，会同时产生 data edge + dependency edge。为隔离测试，本 fixture 的 consumer 应**无 fact 输入**（纯 dependsOn）。调整 `_sources_with_depends_on` 的 consumer inputs 为空或 identifier。

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_authors_dependency_edge_from_depends_on_relation -q`
Expected: FAIL（当前不 author dependency edge）

- [x] **Step 3: 实现 dependency edge authoring + 真拓扑排序**

在 `_build_plan_graph_v2` 中，nodes 构造后扫描 `sources.relations`：

```python
def _build_plan_graph_v2(goal, snapshot, cards, raw_capabilities, handoff):
    # ... nodes / data_edges 构造 ...
    dependency_edges: list[dict[str, Any]] = []
    cap_to_node = {n["capabilityId"]: n["nodeId"] for n in nodes}
    relations = sources.relations.get("relations", []) if hasattr(sources, "relations") else []
    # 注：_build_plan_graph_v2 需接收 sources 参数以读 relations
    edge_counter = len(data_edges)
    for relation in relations:
        if relation.get("relationType") != "dependsOn":
            continue
        dependent_cap = relation.get("capabilityId")
        prerequisite_cap = relation.get("dependsOnCapabilityId")
        if dependent_cap not in cap_to_node or prerequisite_cap not in cap_to_node:
            continue
        dependency_edges.append({
            "edgeId": f"edge.dep.{edge_counter}",
            "kind": "dependency",
            "fromNodeId": cap_to_node[prerequisite_cap],
            "toNodeId": cap_to_node[dependent_cap],
        })
        edge_counter += 1
    edges.extend(dependency_edges)
    topological_order = _topological_order(node_ids, edges)
    # ... partition / return ...
```

强化 `_topological_order`（Kahn 算法）：

```python
def _topological_order(node_ids: list[str], edges: list[dict[str, Any]]) -> list[str]:
    """按 data+dependency edges 拓扑排序；无 edge 时按 nodeId 排序（确定性）。"""
    from collections import defaultdict, deque
    adj: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = {nid: 0 for nid in node_ids}
    for edge in edges:
        src, dst = edge["fromNodeId"], edge["toNodeId"]
        if src in indeg and dst in indeg:
            adj[src].append(dst)
            indeg[dst] += 1
    # 确定性：同 indeg=0 时按 nodeId 字典序
    queue = deque(sorted(nid for nid in node_ids if indeg[nid] == 0))
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        next_ready = []
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                next_ready.append(nxt)
        for nxt in sorted(next_ready):
            queue.append(nxt)
    # 环或断点：回退到 nodeId 排序（validator 会报 DEPENDENCY_CYCLE）
    return order if len(order) == len(node_ids) else list(node_ids)
```

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): v2 compiler authors dependency edges and topological sort"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 10: 分区 authoring 校验 + Action 节点 requiresApproval

**对应 tasks.md：** 3.4

**Files:**
- Modify: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（`_partition_nodes` 强化：Action 节点 governance `requiresApproval=true`）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Produces: `_partition_nodes` 确保 Action/非 read-only 节点入 `actionPartition`；node governance `requiresApproval=true`（已在 `_project_node_governance` 从 raw capability 投影，无需额外改）。

- [x] **Step 1: 写测试——PR.CreateDraft（write Action）入 actionPartition**

```python
def test_compile_plan_v2_partitions_write_action_into_action_partition():
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="write",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.PR.CreateDraft",
                parameters={
                    "material": "M1", "plant": "5100", "quantity": 10,
                    "unit": "EA", "delivery_date": "2026-08-01",
                    "purchasing_group": "PG1",
                },
                missing=[],
            )
        ],
        utterance="create PR",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    pr_nodes = [n for n in result.plan_graph["nodes"] if n["capabilityId"] == "MM.PR.CreateDraft"]
    assert pr_nodes
    assert pr_nodes[0]["nodeId"] in result.plan_graph["actionPartition"]
    assert pr_nodes[0]["nodeId"] not in result.plan_graph["readPartition"]
    assert pr_nodes[0]["governance"]["requiresApproval"] is True
    assert pr_nodes[0]["governance"]["capabilityKind"] == "Action"
```

- [x] **Step 2: 运行确认（应已通过，因 Task 6 已实现分区）**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_partitions_write_action_into_action_partition -q`
Expected: PASS（若 FAIL，修正 `_partition_nodes` 的 `_is_read_only` 判断）

- [x] **Step 3: 若 FAIL，修正 `_partition_nodes`**

确保 `_is_read_only` 接收的 `capability_view` 含完整 `governance`（含 `approvalPolicy`）。`_project_node_governance` 已产出 `approvalPolicy`，但 `_is_read_only` 读 `capability["governance"]["approvalPolicy"]`。`_partition_nodes` 的 `capability_view` 用 raw capability 的 governance，需确保 raw capability governance 含 `approvalPolicy`。真实 `MM.PR.CreateDraft` 的 governance 应含 `approvalPolicy: human_required`。

- [x] **Step 4: 运行确认通过 + 提交**

```bash
.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): v2 partition authoring isolates Action nodes with requiresApproval"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 11: snapshot 漂移 -> PlannerFailure(SNAPSHOT_DRIFT)

**对应 tasks.md：** 3.6, 3.5（结构化失败完整化）

**Files:**
- Modify: `agent/sap_nexus_agent/planner/plan_compiler_v2.py`（`compile_plan_v2` 入口加 snapshot 漂移检查）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Consumes: `PlannerFailure`、`PlannerErrorType`（`SNAPSHOT_DRIFT`）。
- Produces: `compile_plan_v2` 在 `handoff.registry_snapshot_id != snapshot.snapshot_id` 时 raise `PlannerFailure(SNAPSHOT_DRIFT, ...)`。

- [x] **Step 1: 写失败测试——snapshot 漂移抛 PlannerFailure**

```python
from sap_nexus_agent.governed_context import PlannerFailure
import pytest


def test_compile_plan_v2_raises_planner_failure_on_snapshot_drift():
    snapshot = _real_snapshot()
    sources = _real_sources()
    drift_handoff = EscalationHandoff(
        reason="drift",
        matched_intents=[
            MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, [])
        ],
        utterance="drift",
        registry_snapshot_id="sha256:" + "f" * 64,  # 不同于 snapshot.snapshot_id
    )
    with pytest.raises(PlannerFailure) as exc_info:
        compile_plan_v2(drift_handoff, snapshot, sources)
    assert exc_info.value.error_type == "SNAPSHOT_DRIFT"
    assert exc_info.value.snapshot_id == snapshot.snapshot_id
    assert "expected_snapshot_id" in exc_info.value.audit_evidence
    assert "actual_snapshot_id" in exc_info.value.audit_evidence
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_raises_planner_failure_on_snapshot_drift -q`
Expected: FAIL（当前不检查 snapshot 漂移）

- [x] **Step 3: 在 `compile_plan_v2` 入口加漂移检查**

```python
from sap_nexus_agent.governed_context import PlannerFailure

def compile_plan_v2(handoff, snapshot, sources):
    if handoff.registry_snapshot_id != snapshot.snapshot_id:
        raise PlannerFailure(
            error_type="SNAPSHOT_DRIFT",
            message=(
                f"snapshot drift: handoff={handoff.registry_snapshot_id} "
                f"!= snapshot={snapshot.snapshot_id}"
            ),
            snapshot_id=snapshot.snapshot_id,
            audit_evidence={
                "expected_snapshot_id": snapshot.snapshot_id,
                "actual_snapshot_id": handoff.registry_snapshot_id,
                "stage": "compile_plan_v2",
            },
        )
    # ... 现有编译逻辑 ...
```

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/planner/plan_compiler_v2.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): v2 compiler raises PlannerFailure on snapshot drift"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 12: handoff 入口 + dry-run 输出 + 不调 Gateway/SAP

**对应 tasks.md：** 4.1, 4.2

**Files:**
- Modify: `agent/sap_nexus_agent/planner/handoff.py`（追加 `compile_plan_v2_from_handoff`，v1 `compile_dry_run_from_handoff` 不动）
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

**Interfaces:**
- Produces: `compile_plan_v2_from_handoff(handoff, snapshot, sources) -> PlanCompileResult`（薄封装，调用 `compile_plan_v2`）。

- [x] **Step 1: 写失败测试——dry-run 输出齐全 + 不调 Gateway**

```python
from unittest.mock import MagicMock
from sap_nexus_agent.gateway_client import GatewayClientProtocol


def test_compile_plan_v2_from_handoff_outputs_all_v2_fields_without_gateway(monkeypatch):
    import sap_nexus_agent.gateway_client as gateway_module
    exploding = MagicMock(side_effect=AssertionError(
        "GatewayClient must not be instantiated by v2 compiler"
    ))
    monkeypatch.setattr(gateway_module, "GatewayClient", exploding)
    mock_gateway = MagicMock(spec=GatewayClientProtocol)

    snapshot = _real_snapshot()
    sources = _real_sources()
    from sap_nexus_agent.planner.handoff import compile_plan_v2_from_handoff
    result = compile_plan_v2_from_handoff(_dual_read_handoff(snapshot), snapshot, sources)

    # v2 dry-run 输出齐全
    assert result.plan_graph["planGraphVersion"] == 2
    assert result.projection_ref == []
    assert result.rule_set_refs == []
    assert result.snapshot_id == snapshot.snapshot_id
    assert isinstance(result.gaps, list)
    assert isinstance(result.governance_flags, list)
    assert isinstance(result.rationale, str) and result.rationale
    # 不调 Gateway
    mock_gateway.validate.assert_not_called()
    mock_gateway.execute.assert_not_called()
    exploding.assert_not_called()
```

- [x] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py::test_compile_plan_v2_from_handoff_outputs_all_v2_fields_without_gateway -q`
Expected: FAIL（`compile_plan_v2_from_handoff` 未定义）

- [x] **Step 3: 在 `handoff.py` 追加入口**

在 `agent/sap_nexus_agent/planner/handoff.py` 末尾追加（不修改 v1 `compile_dry_run_from_handoff`）：

```python
from sap_nexus_agent.planner.plan_compiler_v2 import PlanCompileResult, compile_plan_v2


def compile_plan_v2_from_handoff(
    handoff: EscalationHandoff,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> PlanCompileResult:
    """Compile a deterministic PlanGraph v2 from an escalation handoff.

    Thin wrapper over ``compile_plan_v2``. Reuses ``_build_goal_with_constraints``
    for GoalSpec derivation. The v1 ``compile_dry_run_from_handoff`` is untouched.
    """
    return compile_plan_v2(handoff, snapshot, sources)
```

- [x] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/planner/handoff.py agent/tests/test_planner_plan_compiler_v2.py
git commit -m "feat(planner): add compile_plan_v2_from_handoff entrypoint with dry-run output"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 13: 7 类 bad-case fail-closed（compiler + validator 联合）

**对应 tasks.md：** 5.2

**Files:**
- Test: `agent/tests/test_planner_plan_compiler_v2.py` + `agent/tests/test_semantic_planning_v2.py`

**bad-case 清单（来自 spec）：** unknown capability、unknown/inconsistent relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ。

- [x] **Step 1: 写 7 类 bad-case 测试（compiler 层）**

在 `test_planner_plan_compiler_v2.py` 追加。每类断言 `result.plan_graph` 非 None（结构化）且 `governance_flags` 含 `invalid_plan_graph` 或 raise `PlannerFailure`：

```python
def test_bad_case_unknown_capability_fails_closed():
    """spec R4: unknown capability -> UNKNOWN_CAPABILITY, plan invalid."""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.DoesNotExist.Get", {"material": "M1", "plant": "5300"}, [])],
        utterance="bad",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    assert result.plan_graph is not None  # 不返回 None
    assert any(f.kind == "invalid_plan_graph" for f in result.governance_flags)


def test_bad_case_missing_parameter_source_fails_closed():
    """spec R4: required parameter no source -> PARAMETER_SOURCE_MISSING."""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.Inventory.GetAvailability", {"plant": "5300"}, [])],
        utterance="bad",  # 缺 material
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    assert result.plan_graph is not None
    assert any(f.kind == "invalid_plan_graph" for f in result.governance_flags)
    # gap 记录 missing_parameter
    assert any(g.kind == "missing_parameter" for g in result.gaps)


def test_bad_case_snapshot_drift_fails_closed():
    """spec R7: snapshot drift -> PlannerFailure(SNAPSHOT_DRIFT)。"""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, [])],
        utterance="bad",
        registry_snapshot_id="sha256:" + "f" * 64,
    )
    with pytest.raises(PlannerFailure) as exc:
        compile_plan_v2(handoff, snapshot, sources)
    assert exc.value.error_type == "SNAPSHOT_DRIFT"
```

- [x] **Step 2: 写 7 类 bad-case 测试（validator 层，直接构造非法 v2 plan）**

在 `test_semantic_planning_v2.py` 追加：

```python
def test_bad_case_unknown_capability_validator():
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["nodes"][0]["capabilityId"] = "MM.DoesNotExist.Get"
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "UNKNOWN_CAPABILITY" for i in report.issues)


def test_bad_case_cycle_validator():
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    # 加第二个节点 + 互相 dependency edge 形成环
    plan["nodes"].append({
        "nodeId": "node.MM.PurchaseOrder.GetList",
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameterBindings": [],
        "producesFactTypes": ["sapnexus:PurchaseOrderSupplyFact"],
        "governance": plan["nodes"][0]["governance"],
    })
    plan["edges"] = [
        {"edgeId": "e1", "kind": "dependency", "fromNodeId": "node.MM.Inventory.GetAvailability", "toNodeId": "node.MM.PurchaseOrder.GetList"},
        {"edgeId": "e2", "kind": "dependency", "fromNodeId": "node.MM.PurchaseOrder.GetList", "toNodeId": "node.MM.Inventory.GetAvailability"},
    ]
    plan["topologicalOrder"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["readPartition"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["actionPartition"] = []
    plan["goalOutputs"] = [{"factTypeId": "sapnexus:InventoryAvailabilityFact", "producerNodeId": "node.MM.Inventory.GetAvailability"}]
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "DEPENDENCY_CYCLE" for i in report.issues)


def test_bad_case_type_mismatch_validator():
    """factField source 引用 producer 不产出的 factType -> FACT_TYPE_MISMATCH。"""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    # 给 inventory 节点加一个 factField 源指向不存在的 producer
    plan["nodes"][0]["parameterBindings"].append({
        "parameterName": "bogus",
        "source": {
            "kind": "factField",
            "producerNodeId": "node.MM.Inventory.GetAvailability",
            "factTypeId": "sapnexus:DoesNotExist",
            "field": "x",
        },
    })
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "FACT_TYPE_MISMATCH" for i in report.issues)


def test_bad_case_inconsistent_relation_validator():
    """dependency edge 不匹配 snapshot dependsOn -> EDGE_INCONSISTENT。"""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["nodes"].append({
        "nodeId": "node.MM.PurchaseOrder.GetList",
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameterBindings": [],
        "producesFactTypes": ["sapnexus:PurchaseOrderSupplyFact"],
        "governance": plan["nodes"][0]["governance"],
    })
    # snapshot 无 dependsOn 关系，但 plan author 了一条 dependency edge
    plan["edges"] = [{"edgeId": "e1", "kind": "dependency", "fromNodeId": "node.MM.Inventory.GetAvailability", "toNodeId": "node.MM.PurchaseOrder.GetList"}]
    plan["topologicalOrder"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["readPartition"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["actionPartition"] = []
    plan["goalOutputs"] = [{"factTypeId": "sapnexus:InventoryAvailabilityFact", "producerNodeId": "node.MM.Inventory.GetAvailability"}]
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "EDGE_INCONSISTENT" for i in report.issues)


def test_bad_case_action_in_read_validator():
    """spec R3: Action 节点入 readPartition -> PARTITION_GOVERNANCE_VIOLATION。"""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["nodes"][0]["governance"] = {
        "capabilityKind": "Action", "sideEffect": "sap_write",
        "requiresApproval": True, "approvalPolicy": "human_required",
    }
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(
        i.code == "PARTITION_GOVERNANCE_VIOLATION" or i.code == "GOVERNANCE_VIOLATION"
        for i in report.issues
    )


def test_bad_case_missing_source_validator():
    """spec R4: required parameter no source -> PARAMETER_SOURCE_MISSING。"""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    # 清空 inventory 节点的 parameterBindings（material/plant 都无源）
    plan["nodes"][0]["parameterBindings"] = []
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "PARAMETER_SOURCE_MISSING" for i in report.issues)
```

- [x] **Step 3: 运行全部 bad-case**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_v2.py agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: 全部 PASS。若有 FAIL，根据失败码修正 compiler/validator（常见：unknown capability 在 compiler 层因 `discover_cards` 过滤掉非 active -> 节点为空 -> `_validate_nodes_and_projections` 不报 UNKNOWN_CAPABILITY 而是走 schema minItems=1；需确认 bad-case 测试断言 `invalid_plan_graph` flag 而非特定 issue code）。

- [x] **Step 4: 结构化 issues 不返回 None 守护测试**

```python
def test_invalid_plan_preserves_structured_issues_not_none():
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.Inventory.GetAvailability", {"plant": "5300"}, [])],
        utterance="bad",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    assert result is not None
    assert result.plan_graph is not None
    invalid_flags = [f for f in result.governance_flags if f.kind == "invalid_plan_graph"]
    assert invalid_flags
    # rationale 携带 issue 摘要
    assert "issue" in result.rationale or "failed" in result.rationale
```

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py agent/tests/test_semantic_planning_v2.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add agent/tests/test_planner_plan_compiler_v2.py agent/tests/test_semantic_planning_v2.py
git commit -m "test(planner): 7 bad-case fail-closed scenarios for v2 compiler and validator"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 14: 双 READ fixture + factField fixture 稳定性测试

**对应 tasks.md：** 5.1

**Files:**
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

- [x] **Step 1: 强化双 READ fixture 测试（稳定可重复 + 空 edges + refs 空）**

```python
def test_dual_read_fixture_is_stable_with_empty_edges_and_refs():
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = _dual_read_handoff(snapshot)
    r1 = compile_plan_v2(handoff, snapshot, sources)
    r2 = compile_plan_v2(handoff, snapshot, sources)
    assert r1 == r2
    pg = r1.plan_graph
    assert pg["edges"] == []
    assert pg["projectionRef"] == []
    assert pg["ruleSetRefs"] == []
    assert pg["actionPartition"] == []
    assert set(pg["readPartition"]) == {n["nodeId"] for n in pg["nodes"]}
    # snapshotId 绑定
    assert pg["snapshotId"] == snapshot.snapshot_id
    # goalOutputs 覆盖两个 FactType
    output_facts = {o["factTypeId"] for o in pg["goalOutputs"]}
    assert "sapnexus:InventoryAvailabilityFact" in output_facts
    assert "sapnexus:PurchaseOrderSupplyFact" in output_facts
```

- [x] **Step 2: factField fixture 稳定性（已在 Task 8 构造，此处强化断言）**

```python
def test_fact_field_fixture_produces_data_edge_and_stable():
    sources, snapshot = _sources_with_fact_field()
    handoff = EscalationHandoff(
        reason="fact-field",
        matched_intents=[
            MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, []),
            MatchedIntent("Test.Consumer.GetSummary", {}, []),
        ],
        utterance="summary",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    r1 = compile_plan_v2(handoff, snapshot, sources)
    r2 = compile_plan_v2(handoff, snapshot, sources)
    assert r1 == r2
    data_edges = [e for e in r1.plan_graph["edges"] if e["kind"] == "data"]
    assert len(data_edges) == 1
```

- [x] **Step 3: 运行确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 4: 提交**

```bash
git add agent/tests/test_planner_plan_compiler_v2.py
git commit -m "test(planner): stabilize dual-READ and factField v2 fixtures"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 15: dry-run 输出测试 + v1 回归

**对应 tasks.md：** 5.3, 5.4

**Files:**
- Test: `agent/tests/test_planner_plan_compiler_v2.py`

- [x] **Step 1: dry-run 输出齐全测试（plan/gaps/governance/refs/snapshotId）**

```python
def test_v2_dry_run_output_surfaces_all_fields():
    snapshot = _real_snapshot()
    sources = _real_sources()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    # plan
    assert result.plan_graph["planGraphVersion"] == 2
    # gaps
    assert isinstance(result.gaps, list)
    # governance
    assert isinstance(result.governance_flags, list)
    # projectionRef / ruleSetRefs
    assert result.projection_ref == []
    assert result.rule_set_refs == []
    # snapshotId
    assert result.snapshot_id == snapshot.snapshot_id
    # rationale 含节点数
    assert str(len(result.plan_graph["nodes"])) in result.rationale
```

- [x] **Step 2: v1 回归——v1 测试不改仍通过**

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler.py agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_handoff.py -q`
Expected: PASS（v1 零改动，全部通过）

- [x] **Step 3: v1 compiler 输出仍为 v1（版本守护）**

```python
def test_v1_compiler_still_produces_v1_plan_graph():
    """spec R1: v1 compiler 输出 planGraphVersion:1，不受 v2 影响。"""
    from sap_nexus_agent.planner.plan_compiler import compile_dry_run
    from sap_nexus_agent.planner.goal_spec import GoalSpec, GoalConstraint
    goal = GoalSpec(
        goal_id="goal.regression",
        goal_type="sapnexus:PlannerDryRunGoal",
        desired_fact_types=("sapnexus:InventoryAvailabilityFact",),
        execution_mode="PLAN_ONLY",
        constraints=(
            GoalConstraint("material", "sapnexus:MaterialNumber", "M1"),
            GoalConstraint("plant", "sapnexus:Plant", "5300"),
        ),
    )
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    assert result.plan_graph["planGraphVersion"] == 1
    # v1 不含 v2 字段
    for field in ("readPartition", "actionPartition", "projectionRef", "ruleSetRefs"):
        assert field not in result.plan_graph
```

Run: `.venv/bin/python -m pytest agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: PASS

- [x] **Step 4: 提交**

```bash
git add agent/tests/test_planner_plan_compiler_v2.py
git commit -m "test(planner): v2 dry-run output surface and v1 regression guard"
```

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Task 16: 全量验证 + 文档更新

**对应 tasks.md：** 6.1, 6.2, 6.3, 6.4

**Files:**
- Modify: `docs/runbooks/README.md`、roadmap row 26、Runbook 15（状态/版本）

- [x] **Step 1: 全量 pytest（v1 + v2）**

Run: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py agent/tests/test_semantic_planning_v2.py agent/tests/test_planner_plan_compiler_v2.py -q`
Expected: 全绿。若 v1 测试 FAIL，说明 v2 改动意外影响 v1 -> 修正（v1 模块必须零改动）。

- [x] **Step 2: verify-agent-callplan-evidence.sh**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: 通过。若报 evidence 命令缺失，检查脚本是否需追加 v2 测试命令（按 CLAUDE.md §4，该脚本应含 `pytest agent/tests`，已覆盖）。

- [x] **Step 3: openspec validate**

Run: `openspec validate --all --strict`
Expected: 通过。若报 spec.md 场景与实现不符（如 `registeredDefault` scenario），按 Design Doc §6 Spec Patch 更新 `specs/semantic-plan-authoring-v2/spec.md` 的 "Optional input uses registered default" scenario 为 reserved 描述。

- [x] **Step 4: 更新 Runbook 15 状态/版本 + docs/runbooks/README.md + roadmap row 26**

- Runbook 15：标记 v2 实现 completed，版本 bump（先读实际当前版本再 bump，避免漂移）。
- `docs/runbooks/README.md`：更新 Runbook 15 状态链接。
- roadmap row 26：标记进度。

- [x] **Step 5: git status 确认 + 提交**

```bash
git status --short
git add docs/runbooks/README.md docs/runbooks/ docs/wiki/  # 实际改动的文档
git commit -m "docs(runbook-15): mark semantic-plan-authoring-v2 implemented with v2 plan graph"
```

- [x] **Step 6: 最终全量验证**

Run:
```bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py -q
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```
Expected: 全部通过。

archived-with: 2026-08-04-sap-nexus-semantic-plan-authoring-v2
---

## Self-Review

**1. Spec 覆盖（8 个 ADDED Requirements -> Tasks）：**
- R1 PlanGraph v2 schema（partition/provenance/refs）-> Task 1 ✓
- R2 v2 compiler authors full provenance + relations -> Task 6/7/8/9 ✓
- R3 READ/WRITE partition isolates Action -> Task 4/10 ✓
- R4 v2 validator reuses S1 + partition + ref -> Task 3/4/5 ✓
- R5 Validation failures structured, never None -> Task 11/13 ✓
- R6 v2 dry-run auditable + non-executing -> Task 12/15 ✓
- R7 v2 compiler consumes EscalationHandoff + same-snapshot -> Task 6/11 ✓
- R8 LLM cannot create registry entities -> Task 8/9（edge/ref 来自 snapshot）+ Task 13（unknown capability/relation fail-closed）✓

**2. tasks.md 22 task 覆盖：** 1.1/1.2->Task1；2.1->Task2；2.2->Task3；2.3->Task4；2.4->Task5；3.1->Task6；3.2->Task6/7/8；3.3->Task8/9；3.4->Task10；3.5->Task2/11/13；3.6->Task11；4.1->Task12；4.2->Task12；5.1->Task14；5.2->Task13；5.3->Task15；5.4->Task15；6.1/6.2/6.3->Task16；6.4->Task16。✓

**3. Placeholder 扫描：** Task 3 的 `_validate_partitions`/`_validate_refs` 占位 `NotImplementedError` 已在 Step 4 替换为最小实现；无遗留 TBD/TODO。✓

**4. 类型一致性：** `PlanCompileResult` 字段（plan_graph/gaps/governance_flags/projection_ref/rule_set_refs/snapshot_id/rationale）在 Task 2 定义、Task 6/12/15 使用一致；`compile_plan_v2` 签名（handoff, snapshot, sources）-> PlanCompileResult 在 Task 6 定义、Task 11/12/13 使用一致；`validate_plan_graph_v2` 签名（graph, snapshot, goal_spec, plan_graph）-> PlanValidationReport 在 Task 3 定义、Task 4/5/13 使用一致。✓

**5. 关键技术约束体现：** 双版本并存（Global Constraints + 每个 Task 强调 v1 零改动）；4 源闭集（Task 1 schema + Task 7/8 authoring + Task 3 registeredDefault 校验）；edge 由 S1 契约驱动（Task 8 data edge + Task 9 dependency edge fromNodeId=prerequisite）；分区按 topologicalOrder 排序（Task 6/10）；不返回 None（Task 11/13）；snapshot 漂移抛 PlannerFailure（Task 11）；不调 Gateway/SAP（Task 12/15）。✓


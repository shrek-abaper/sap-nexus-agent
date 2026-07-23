---
change: sap-nexus-semantic-planning-foundation
design-doc: docs/superpowers/specs/2026-07-19-sap-nexus-semantic-planning-foundation-design.md
base-ref: 7a1832a1328e7783e295cd9e9da21a80a01e4fc2
status: ready-for-execution-choice
archived-with: 2026-07-19-sap-nexus-semantic-planning-foundation
---

# SAP Nexus Semantic Planning Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可版本化、可确定性校验的语义规划基础层，使 SAP Nexus 能用发布的 Fact Type 和能力关系验证 `GoalSpec` / `PlanGraph`，但不在 S1 生成计划或执行 Gateway/SAP。

**Architecture:** 将语义真值拆分到 `capabilities.yaml`、`fact-types.yaml`、`capability-relations.yaml`，由 `SemanticGraphCompiler` 生成不可变只读图；`executor-bindings.yaml` 只进入内容寻址的 `RegistrySnapshot`。现有 Registry 安全校验保持不变，新语义校验通过一个组合 CLI 接入证据脚本，且不接入 selector、orchestrator、`CallPlan` 或 `ReasoningFact`。

**Tech Stack:** Python 3.12、PyYAML 6.x（现有依赖）、pytest、jsonschema 4.x（现有 test extra）、JSON Schema 2020-12、YAML、SHA-256。

## Global Constraints

- 先通过 `/comet` 创建 `sap-nexus-semantic-planning-foundation` 的 OpenSpec change，再开始 Task 1；本计划本身不创建 change。
- 只在当前分支工作；不创建、切换或重命名分支。
- 未经用户明确要求，不执行 `git commit`；每个 Task 以 review checkpoint 代替自动提交。
- `registry/capabilities.yaml` 必须从 version `1` 原子迁移到 `2`，不保留双读或半迁移状态。
- OpenHarness 只作设计参考；不增加 OpenHarness runtime、plugin loader 或第二执行权威。
- S1 不调用 LLM、Gateway、SAP，不生成 `PlanDraft` / `PlanGraph`，不修改 selector、orchestrator、`CallPlan`、`ReasoningFact`、frontend 或 Java Gateway。
- `GoalSpec.executionMode` 仅允许 `PLAN_ONLY` / `READ_ONLY`；`READ_ONLY` 必须拒绝 Action 或任何非 `sideEffect=none` 投影。
- `PlanGraph`、`GoalSpec` 禁止出现 `bindingId`、`rfcName`、URL、credential、header 或 executor mapping。
- OWL 只允许做离线镜像，不是 YAML/JSON Schema/validator 的权威来源。
- 不新增外部依赖；复用已有 PyYAML 和 jsonschema。
- 所有 issue 使用 JSON Pointer path，并按 `(path, code, message)` 确定性排序。
- 不提交 `.env`、凭据、token、连接串、真实运行 trace 或 SAP 数据。

---

## File Structure

### Create

| Path | Responsibility |
|---|---|
| `ontology/fact-types.yaml` | 三个首批 canonical Fact Type |
| `ontology/capability-relations.yaml` | 非派生 `dependsOn` / `precondition` 关系；首版为空 |
| `schemas/fact-type-catalog.schema.json` | Fact Type catalog contract |
| `schemas/capability-relation.schema.json` | 非派生关系 discriminated union |
| `schemas/goal-spec.schema.json` | `GoalSpec v1` contract |
| `schemas/plan-graph.schema.json` | `PlanGraph v1`、参数来源和 edge union |
| `schemas/registry-snapshot.schema.json` | Snapshot manifest contract |
| `agent/sap_nexus_agent/semantic_planning/__init__.py` | 公开稳定接口 |
| `agent/sap_nexus_agent/semantic_planning/contracts.py` | immutable value objects、reports、source container |
| `agent/sap_nexus_agent/semantic_planning/loader.py` | 加载四份权威 YAML |
| `agent/sap_nexus_agent/semantic_planning/snapshot.py` | canonical JSON + SHA-256 |
| `agent/sap_nexus_agent/semantic_planning/graph.py` | `SemanticGraphCompiler` 和只读图 |
| `agent/sap_nexus_agent/semantic_planning/validation.py` | contract / goal / plan validators |
| `scripts/validate-semantic-planning-contract.py` | 组合旧 Registry gate 与新语义 gate 的 CLI |
| `agent/tests/test_semantic_planning_contract.py` | catalog、graph、snapshot、goal、plan 测试 |
| `agent/tests/fixtures/semantic_planning/goal-material-supply.yaml` | 首个 Goal fixture |
| `agent/tests/fixtures/semantic_planning/plan-material-supply.yaml` | 首个双节点无 edge Plan fixture |

### Modify

| Path | Responsibility |
|---|---|
| `registry/capabilities.yaml` | version 2、`bindingKind`、`factTypeRef` |
| `schemas/capability.schema.json` | v2 条件 schema |
| `scripts/validate_registry_contract.py` | 旧 gate 增加 v2 IO invariant，不删除原安全检查 |
| `scripts/verify-agent-callplan-evidence.sh` | 加入语义规划组合 CLI |
| `agent/tests/test_contract_files.py` | 新 JSON Schema 正反例 |
| `agent/tests/test_registry_contract.py` | v2 Registry validator 回归 |
| `docs/runbooks/10-capability-composition-contract.md` | S1 实施/验证结果与下一步 |
| `docs/runbooks/README.md` | 当前 workstream 和归档链接 |
| `docs/wiki/sap-nexus-agent-implementation-roadmap.md` | S1 状态与 S2 gate |
| `docs/wiki/sap-nexus-agent-technical-architecture.md` | 仅在实现与设计存在差异时同步最终 live contract |
| `openspec/changes/sap-nexus-semantic-planning-foundation/tasks.md` | 每个 Task 验证后勾选 |

---

### Task 1: Registry v2 and Versioned Semantic Schemas

**Files:**
- Create: `ontology/fact-types.yaml`
- Create: `ontology/capability-relations.yaml`
- Create: `schemas/fact-type-catalog.schema.json`
- Create: `schemas/capability-relation.schema.json`
- Create: `schemas/goal-spec.schema.json`
- Create: `schemas/plan-graph.schema.json`
- Create: `schemas/registry-snapshot.schema.json`
- Modify: `registry/capabilities.yaml`
- Modify: `schemas/capability.schema.json`
- Modify: `agent/tests/test_contract_files.py`

**Interfaces:**
- Consumes: 当前三个 active capability 和既有 governance/executor/eval 字段。
- Produces: capability registry v2；Fact Type catalog v1；relation catalog v1；GoalSpec/PlanGraph/Snapshot v1 schemas。

- [x] **Step 1: 先写 Registry v2 和 catalog 的失败测试**

在 `agent/tests/test_contract_files.py` 追加：

~~~python
import yaml


def _load_yaml(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))


def test_capability_registry_v2_declares_fact_binding_contract():
    registry = _load_yaml("registry/capabilities.yaml")
    jsonschema.validate(registry, _load_schema("capability.schema.json"))

    assert registry["version"] == 2
    by_id = {item["capabilityId"]: item for item in registry["capabilities"]}
    expected = {
        "MM.Inventory.GetAvailability": "sapnexus:InventoryAvailabilityFact",
        "MM.PurchaseOrder.GetList": "sapnexus:PurchaseOrderSupplyFact",
        "MM.PR.CreateDraft": "sapnexus:PurchaseRequisitionCreatedFact",
    }
    for capability_id, fact_type_id in expected.items():
        capability = by_id[capability_id]
        assert all(item["bindingKind"] == "identifier" for item in capability["inputs"])
        primary = [item for item in capability["outputs"] if item["evidenceRole"] == "primaryFact"]
        assert [item["factTypeRef"] for item in primary] == [fact_type_id]


def test_initial_fact_type_and_relation_catalogs_validate():
    fact_types = _load_yaml("ontology/fact-types.yaml")
    relations = _load_yaml("ontology/capability-relations.yaml")
    jsonschema.validate(fact_types, _load_schema("fact-type-catalog.schema.json"))
    jsonschema.validate(relations, _load_schema("capability-relation.schema.json"))

    assert {item["factTypeId"] for item in fact_types["factTypes"]} == {
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
        "sapnexus:PurchaseRequisitionCreatedFact",
    }
    assert relations == {"version": 1, "relations": []}
~~~

- [x] **Step 2: 运行测试确认 RED**

Run:

~~~bash
.venv/bin/python -m pytest \
  agent/tests/test_contract_files.py::test_capability_registry_v2_declares_fact_binding_contract \
  agent/tests/test_contract_files.py::test_initial_fact_type_and_relation_catalogs_validate -v
~~~

Expected: FAIL，因为 Registry 仍是 v1，且新 catalog/schema 尚不存在。

- [x] **Step 3: 原子迁移 `capabilities.yaml`**

将顶层 `version` 改为 `2`。每个现有 input 增加：

~~~yaml
        bindingKind: identifier
~~~

三个 primary output 分别增加：

~~~yaml
# MM.Inventory.GetAvailability.availableQuantity
        factTypeRef: sapnexus:InventoryAvailabilityFact
# MM.PurchaseOrder.GetList.purchaseOrders
        factTypeRef: sapnexus:PurchaseOrderSupplyFact
# MM.PR.CreateDraft.prNumber
        factTypeRef: sapnexus:PurchaseRequisitionCreatedFact
~~~

不得修改现有 capability ID、required flag、SAP parameter、executor、binding、eval 或 governance。

- [x] **Step 4: 创建两个 catalog**

`ontology/fact-types.yaml` 使用设计稿 `6.2` 的三个完整条目，字段固定为：

~~~yaml
version: 1
factTypes:
  - factTypeId: sapnexus:InventoryAvailabilityFact
    name: Inventory Availability Fact
    description: Available inventory quantity for a material and plant.
    businessObject: InventoryStock
    predicate: sapnexus:hasInventoryAvailability
    semanticType: sapnexus:InventoryAvailability
    keyedBy:
      - sapnexus:MaterialNumber
      - sapnexus:Plant
  - factTypeId: sapnexus:PurchaseOrderSupplyFact
    name: Purchase Order Supply Fact
    description: Purchase-order supply items for a material and plant.
    businessObject: PurchaseOrder
    predicate: sapnexus:hasPurchaseOrderSupply
    semanticType: sapnexus:PurchaseOrderSupply
    keyedBy:
      - sapnexus:MaterialNumber
      - sapnexus:Plant
  - factTypeId: sapnexus:PurchaseRequisitionCreatedFact
    name: Purchase Requisition Created Fact
    description: Identity of a purchase requisition created by an approved Action.
    businessObject: PurchaseRequisition
    predicate: sapnexus:hasCreatedPurchaseRequisition
    semanticType: sapnexus:PurchaseRequisitionCreated
    keyedBy:
      - sapnexus:PrNumber
~~~

`ontology/capability-relations.yaml` 必须是：

~~~yaml
version: 1
relations: []
~~~

- [x] **Step 5: 实现 JSON Schemas**

`schemas/capability.schema.json`：

- 顶层 `version.const` 改为 `2`。
- `ioField.required` 加入 `bindingKind`。
- `bindingKind.enum` 为 `["identifier", "fact"]`。
- `identifier` 分支通过 `not.required=["satisfiableByFactType"]` 禁止 Fact reference。
- `fact` 分支强制 `satisfiableByFactType`。
- `outputField.properties` 增加 `factTypeRef`。
- `primaryFact` 分支强制 `factTypeRef`。

关键条件必须写成：

~~~json
{
  "allOf": [
    {
      "if": {
        "properties": { "bindingKind": { "const": "fact" } },
        "required": ["bindingKind"]
      },
      "then": { "required": ["satisfiableByFactType"] }
    },
    {
      "if": {
        "properties": { "bindingKind": { "const": "identifier" } },
        "required": ["bindingKind"]
      },
      "then": { "not": { "required": ["satisfiableByFactType"] } }
    }
  ]
}
~~~

其他五个 schema 必须设置 `additionalProperties: false`，并严格实现设计稿 `6`、`8`、`9`、`10`：

| Schema | Required discriminators and unions |
|---|---|
| `fact-type-catalog` | `version=1`；Fact Type 六个 scalar 字段 + 非空唯一 `keyedBy` |
| `capability-relation` | `dependsOn` requires `dependsOnCapabilityId`；`precondition` requires `requiredFactType` |
| `goal-spec` | `goalSpecVersion=1`；mode 两值；unique desired Fact Types；typed scalar constraints |
| `plan-graph` | `planGraphVersion=1`；三种 parameter source；两种 edge；完整 governance projection |
| `registry-snapshot` | `snapshotVersion=1`、`canonicalizationVersion=1`、`sha256:[0-9a-f]{64}`、四个 source manifest entry |

- [x] **Step 6: 补 schema 反例并运行 GREEN**

追加以下测试，使用 `pytest.raises(jsonschema.ValidationError)`：

~~~python
def test_capability_v2_rejects_invalid_binding_variants():
    registry = _load_yaml("registry/capabilities.yaml")
    schema = _load_schema("capability.schema.json")

    identifier_with_fact = json.loads(json.dumps(registry))
    identifier_with_fact["capabilities"][0]["inputs"][0]["satisfiableByFactType"] = (
        "sapnexus:InventoryAvailabilityFact"
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(identifier_with_fact, schema)

    fact_without_reference = json.loads(json.dumps(registry))
    fact_without_reference["capabilities"][0]["inputs"][0]["bindingKind"] = "fact"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(fact_without_reference, schema)

    primary_without_fact = json.loads(json.dumps(registry))
    del primary_without_fact["capabilities"][0]["outputs"][0]["factTypeRef"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(primary_without_fact, schema)
~~~

同时在 import 区加入 `import pytest`。运行：

将 `agent/tests/test_contract_files.py` 中两个 inline Action document 同步为 version `2`：每个 input 增加 `bindingKind: "identifier"`，primary output 增加 `factTypeRef: "sapnexus:PurchaseRequisitionCreatedFact"`。将 `agent/tests/test_registry_contract.py` 中两个 inline capability YAML 同步为 v2 和相同 IO 规则；其中 executor-binding fixture 的 `version: 1` 保持不变。

~~~bash
.venv/bin/python -m pytest agent/tests/test_contract_files.py -v
~~~

Expected: 全部 PASS。

- [x] **Step 7: Review Task 1 checkpoint**

检查 `git diff -- registry/capabilities.yaml schemas ontology`，确认所有现有 input 只增加 `bindingKind`、所有 primary output 只增加已批准 `factTypeRef`，没有 executor/governance 漂移。经用户明确要求后才能提交。

---

### Task 2: Immutable Contracts, Loader, and Registry Snapshot

**Files:**
- Create: `agent/sap_nexus_agent/semantic_planning/__init__.py`
- Create: `agent/sap_nexus_agent/semantic_planning/contracts.py`
- Create: `agent/sap_nexus_agent/semantic_planning/loader.py`
- Create: `agent/sap_nexus_agent/semantic_planning/snapshot.py`
- Create: `agent/tests/test_semantic_planning_contract.py`

**Interfaces:**
- Produces: `load_semantic_sources(repo_root: Path) -> SemanticSourceDocuments`。
- Produces: `canonical_json_bytes(value: Any) -> bytes`。
- Produces: `build_registry_snapshot(sources: SemanticSourceDocuments) -> RegistrySnapshot`。

- [x] **Step 1: 写 loader 和 snapshot 失败测试**

创建 `agent/tests/test_semantic_planning_contract.py`：

~~~python
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import jsonschema

from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.snapshot import (
    build_registry_snapshot,
    canonical_json_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_semantic_schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_loads_exactly_four_snapshot_sources():
    sources = load_semantic_sources(REPO_ROOT)
    assert tuple(sources.documents_by_path()) == (
        "ontology/capability-relations.yaml",
        "ontology/fact-types.yaml",
        "registry/capabilities.yaml",
        "registry/executor-bindings.yaml",
    )


def test_canonical_json_ignores_mapping_order_but_preserves_array_order():
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes({"a": 1, "b": 2})
    assert canonical_json_bytes({"a": [1, 2]}) != canonical_json_bytes({"a": [2, 1]})


def test_registry_snapshot_is_deterministic_and_content_sensitive():
    sources = load_semantic_sources(REPO_ROOT)
    first = build_registry_snapshot(sources)
    second = build_registry_snapshot(sources)
    assert first == second
    assert first.snapshot_id.startswith("sha256:")
    assert len(first.snapshot_id) == 71
    assert tuple(item.path for item in first.sources) == tuple(sources.documents_by_path())
    jsonschema.validate(first.to_dict(), _load_semantic_schema("registry-snapshot.schema.json"))

    changed_capabilities = dict(sources.capabilities)
    changed_capabilities["version"] = 999
    changed = replace(sources, capabilities=changed_capabilities)
    assert build_registry_snapshot(changed).snapshot_id != first.snapshot_id
~~~

- [x] **Step 2: 运行 Task 2 RED**

Run:

~~~bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v
~~~

Expected: FAIL with `ModuleNotFoundError` for `semantic_planning`。

- [x] **Step 3: 实现 immutable contract types**

`contracts.py` 定义以下稳定类型：

~~~python
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class ValidationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class ContractValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class GoalReachabilityReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    reachable_fact_types: tuple[str, ...]
    capability_gaps: tuple[str, ...]


@dataclass(frozen=True)
class PlanValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class SnapshotSource:
    path: str
    document_version: int
    digest: str


@dataclass(frozen=True)
class RegistrySnapshot:
    snapshot_version: int
    canonicalization_version: int
    snapshot_id: str
    sources: tuple[SnapshotSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotVersion": self.snapshot_version,
            "canonicalizationVersion": self.canonicalization_version,
            "snapshotId": self.snapshot_id,
            "sources": [
                {
                    "path": item.path,
                    "documentVersion": item.document_version,
                    "digest": item.digest,
                }
                for item in self.sources
            ],
        }


@dataclass(frozen=True)
class SemanticSourceDocuments:
    capabilities: Mapping[str, Any]
    executor_bindings: Mapping[str, Any]
    fact_types: Mapping[str, Any]
    relations: Mapping[str, Any]

    def documents_by_path(self) -> Mapping[str, Mapping[str, Any]]:
        return MappingProxyType({
            "ontology/capability-relations.yaml": self.relations,
            "ontology/fact-types.yaml": self.fact_types,
            "registry/capabilities.yaml": self.capabilities,
            "registry/executor-bindings.yaml": self.executor_bindings,
        })


def sorted_issues(issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    return tuple(sorted(issues, key=lambda item: (item.path, item.code, item.message)))
~~~

- [x] **Step 4: 实现安全 YAML loader**

`loader.py`：

~~~python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .contracts import SemanticSourceDocuments


class SourceLoadError(ValueError):
    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceLoadError(path, str(exc)) from exc
    if not isinstance(value, dict):
        raise SourceLoadError(path, "document root must be a mapping")
    return value


def load_semantic_sources(repo_root: Path) -> SemanticSourceDocuments:
    return SemanticSourceDocuments(
        capabilities=load_yaml_mapping(repo_root / "registry/capabilities.yaml"),
        executor_bindings=load_yaml_mapping(repo_root / "registry/executor-bindings.yaml"),
        fact_types=load_yaml_mapping(repo_root / "ontology/fact-types.yaml"),
        relations=load_yaml_mapping(repo_root / "ontology/capability-relations.yaml"),
    )
~~~

- [x] **Step 5: 实现 canonical Snapshot**

`snapshot.py`：

~~~python
from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import RegistrySnapshot, SemanticSourceDocuments, SnapshotSource


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_id(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_registry_snapshot(sources: SemanticSourceDocuments) -> RegistrySnapshot:
    documents = sources.documents_by_path()
    source_entries = tuple(
        SnapshotSource(
            path=path,
            document_version=int(document["version"]),
            digest=_sha256_id(document),
        )
        for path, document in documents.items()
    )
    return RegistrySnapshot(
        snapshot_version=1,
        canonicalization_version=1,
        snapshot_id=_sha256_id(dict(documents)),
        sources=source_entries,
    )
~~~

`__init__.py` 只导出本计划中命名的 public types/functions，不导入 orchestrator 或 Gateway 模块。

- [x] **Step 6: 运行 Task 2 GREEN**

~~~bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v
~~~

Expected: 3 tests PASS。

- [x] **Step 7: Review Task 2 checkpoint**

确认 Snapshot 只包含设计稿指定四个路径；实现中没有 timestamp、random ID、filesystem write 或 network call。

---

### Task 3: Contract Validation and Immutable Semantic Graph

**Files:**
- Create: `agent/sap_nexus_agent/semantic_planning/graph.py`
- Create: `agent/sap_nexus_agent/semantic_planning/validation.py`
- Modify: `agent/sap_nexus_agent/semantic_planning/contracts.py`
- Modify: `agent/tests/test_semantic_planning_contract.py`
- Modify: `agent/tests/test_contract_files.py`
- Modify: `scripts/validate_registry_contract.py`
- Modify: `schemas/executor-binding.schema.json`

**Approved scope correction:** `executor-bindings.yaml` 已使用设计权威值 `sap_write`，但既有 schema enum 滞后；经用户确认，本任务同步修正 schema 并增加 contract regression，禁止在 semantic validator 中加入特判。

**Interfaces:**
- Produces: `SemanticGraphCompiler.compile(sources) -> ImmutableSemanticGraph`。
- Produces: `build_semantic_contracts(sources) -> ContractBuildResult`。
- Preserves: `validate_registry_contract(...) -> list[str]` legacy interface。

- [x] **Step 1: 写 graph 和 contract report 失败测试**

追加：

~~~python
from sap_nexus_agent.semantic_planning.contracts import ValidationIssue
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts


def test_compiles_expected_immutable_producer_edges():
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))
    assert result.report.valid is True
    assert result.report.issues == ()
    assert result.graph is not None
    assert result.snapshot is not None
    assert result.graph.producers_by_fact_type["sapnexus:InventoryAvailabilityFact"] == (
        "MM.Inventory.GetAvailability",
    )
    assert result.graph.producers_by_fact_type["sapnexus:PurchaseOrderSupplyFact"] == (
        "MM.PurchaseOrder.GetList",
    )
    assert tuple(edge.relation_type for edge in result.graph.edges) == (
        "producesFactType",
        "producesFactType",
        "producesFactType",
    )
    with pytest.raises(TypeError):
        result.graph.capabilities["MM.Inventory.GetAvailability"]["kind"] = "Action"


def test_contract_issues_are_structured_and_deterministically_sorted():
    sources = load_semantic_sources(REPO_ROOT)
    broken = dict(sources.capabilities)
    capabilities = [dict(item) for item in broken["capabilities"]]
    capabilities[0] = dict(capabilities[0])
    capabilities[0]["outputs"] = [dict(item) for item in capabilities[0]["outputs"]]
    capabilities[0]["outputs"][0]["factTypeRef"] = "sapnexus:UnknownFact"
    broken["capabilities"] = capabilities + [dict(capabilities[0])]

    result = build_semantic_contracts(replace(sources, capabilities=broken))
    assert result.report.valid is False
    assert result.graph is None
    assert result.snapshot is None
    assert list(result.report.issues) == sorted(
        result.report.issues,
        key=lambda item: (item.path, item.code, item.message),
    )
    assert {item.code for item in result.report.issues} >= {
        "DUPLICATE_ID",
        "UNKNOWN_FACT_TYPE",
    }
~~~

- [x] **Step 2: 运行 Task 3 RED**

Run:

~~~bash
.venv/bin/python -m pytest \
  agent/tests/test_semantic_planning_contract.py::test_compiles_expected_immutable_producer_edges \
  agent/tests/test_semantic_planning_contract.py::test_contract_issues_are_structured_and_deterministically_sorted -v
~~~

Expected: FAIL，因为 graph/compiler/result 尚不存在。

- [x] **Step 3: 实现 graph value objects 和 compiler**

`graph.py` 的 public contract：

~~~python
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import SemanticSourceDocuments


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True, order=True)
class SemanticEdge:
    relation_type: str
    source_id: str
    target_id: str


@dataclass(frozen=True)
class ImmutableSemanticGraph:
    capabilities: Mapping[str, Mapping[str, Any]]
    fact_types: Mapping[str, Mapping[str, Any]]
    edges: tuple[SemanticEdge, ...]
    producers_by_fact_type: Mapping[str, tuple[str, ...]]
    consumers_by_fact_type: Mapping[str, tuple[str, ...]]


class SemanticGraphCompiler:
    def compile(self, sources: SemanticSourceDocuments) -> ImmutableSemanticGraph:
        capabilities = {
            item["capabilityId"]: _deep_freeze(item)
            for item in sources.capabilities["capabilities"]
        }
        fact_types = {
            item["factTypeId"]: _deep_freeze(item)
            for item in sources.fact_types["factTypes"]
        }
        edges: set[SemanticEdge] = set()
        for capability_id, capability in capabilities.items():
            for output in capability["outputs"]:
                fact_type_id = output.get("factTypeRef")
                if fact_type_id:
                    edges.add(SemanticEdge("producesFactType", capability_id, fact_type_id))
            for input_field in capability["inputs"]:
                if input_field["bindingKind"] == "fact":
                    edges.add(
                        SemanticEdge(
                            "consumesFactType",
                            capability_id,
                            input_field["satisfiableByFactType"],
                        )
                    )
        for relation in sources.relations["relations"]:
            if relation["relationType"] == "dependsOn":
                target = relation["dependsOnCapabilityId"]
            else:
                target = relation["requiredFactType"]
            edges.add(SemanticEdge(relation["relationType"], relation["capabilityId"], target))

        ordered_edges = tuple(sorted(edges))
        return ImmutableSemanticGraph(
            capabilities=MappingProxyType(capabilities),
            fact_types=MappingProxyType(fact_types),
            edges=ordered_edges,
            producers_by_fact_type=_index_fact_edges(ordered_edges, "producesFactType"),
            consumers_by_fact_type=_index_fact_edges(ordered_edges, "consumesFactType"),
        )


def _index_fact_edges(
    edges: tuple[SemanticEdge, ...],
    relation_type: str,
) -> Mapping[str, tuple[str, ...]]:
    index: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.relation_type == relation_type:
            index[edge.target_id].append(edge.source_id)
    return MappingProxyType({
        fact_type_id: tuple(sorted(set(capability_ids)))
        for fact_type_id, capability_ids in sorted(index.items())
    })
~~~

`_index_fact_edges` 必须返回 `MappingProxyType`，value 为排序后的 tuple。不得在 graph 中暴露可变 list/dict。

- [x] **Step 4: 实现 contract build result 和验证顺序**

在 `contracts.py` 增加：

~~~python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import ImmutableSemanticGraph


@dataclass(frozen=True)
class ContractBuildResult:
    report: ContractValidationReport
    graph: "ImmutableSemanticGraph | None"
    snapshot: RegistrySnapshot | None
~~~

`validation.py` 实现：

~~~python
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .contracts import (
    ContractBuildResult,
    ContractValidationReport,
    SemanticSourceDocuments,
    ValidationIssue,
    sorted_issues,
)
from .graph import SemanticGraphCompiler
from .snapshot import build_registry_snapshot


def build_semantic_contracts(sources: SemanticSourceDocuments) -> ContractBuildResult:
    issues: list[ValidationIssue] = []
    _validate_versions_and_shapes(sources, issues)
    _validate_unique_ids(sources, issues)
    _validate_fact_references(sources, issues)
    _validate_relation_endpoints(sources, issues)
    _validate_dependency_cycles(sources, issues)
    ordered = sorted_issues(issues)
    if ordered:
        return ContractBuildResult(
            report=ContractValidationReport(valid=False, issues=ordered),
            graph=None,
            snapshot=None,
        )
    graph = SemanticGraphCompiler().compile(sources)
    snapshot = build_registry_snapshot(sources)
    return ContractBuildResult(
        report=ContractValidationReport(valid=True, issues=()),
        graph=graph,
        snapshot=snapshot,
    )
~~~

Helper rules必须逐项实现：

- source versions 固定为 capabilities=2，其他三个=1。
- capability/factType/relation/binding IDs 各自唯一；重复报 `DUPLICATE_ID`。
- 每个 capability 的 `executorBinding.bindingId` 必须存在且 type 相同；否则报 `SCHEMA_INVALID`，旧 validator 仍负责更完整的 executor 安全规则。
- input 的 `bindingKind` 条件和 primary output `factTypeRef` 条件。
- 所有 Fact Type/capability relation endpoint 可解析。
- authored relation 只允许 `dependsOn` / `precondition`。
- duplicate `relationId` 或重复 authored semantic edge 报 `DUPLICATE_ID`；重复 derived producer edge 由 compiler 折叠。
- `dependsOn` self-edge 和 cycle 报 `DEPENDENCY_CYCLE`。
- relation endpoint 缺失报 `RELATION_ENDPOINT_NOT_FOUND`；capability IO Fact ref 缺失报 `UNKNOWN_FACT_TYPE`。
- issue path 精确到数组 index，例如 `/capabilities/0/outputs/0/factTypeRef`。

- [x] **Step 5: 扩展 legacy Registry validator 的 v2 invariant**

保留 `scripts/validate_registry_contract.py` 全部现有安全、binding、eval、OWL 规则，只增加：

~~~python
def _validate_semantic_io_fields(capability: CapabilityEntry) -> list[str]:
    errors: list[str] = []
    inputs = capability.raw.get("inputs") or []
    for input_field in inputs:
        name = input_field.get("name", "<unknown>")
        binding_kind = input_field.get("bindingKind")
        if binding_kind not in ("identifier", "fact"):
            errors.append(f"{capability.capability_id}: inputs[{name}].bindingKind is required")
        if binding_kind == "fact" and not input_field.get("satisfiableByFactType"):
            errors.append(
                f"{capability.capability_id}: inputs[{name}].satisfiableByFactType is required"
            )
        if binding_kind == "identifier" and "satisfiableByFactType" in input_field:
            errors.append(
                f"{capability.capability_id}: inputs[{name}] identifier must not declare "
                "satisfiableByFactType"
            )
    outputs = capability.raw.get("outputs") or []
    for output in outputs:
        name = output.get("name", "<unknown>")
        if output.get("evidenceRole") == "primaryFact" and not output.get("factTypeRef"):
            errors.append(
                f"{capability.capability_id}: outputs[{name}].factTypeRef is required"
            )
    return errors
~~~

在现有 `_validate_capability_shape` 返回前调用 `errors.extend(_validate_semantic_io_fields(capability))`。不要改变 `load_registry_contract` 和 `validate_registry_contract` 的 public signature，也不要删除现有检查。

- [x] **Step 6: 增加 negative matrix**

在 test import 区加入 `import pytest`。用以下 helper 构造完整 source mutation：

~~~python
def mutated_sources(sources, mutation):
    capabilities = deepcopy(dict(sources.capabilities))
    relations = deepcopy(dict(sources.relations))
    inventory = capabilities["capabilities"][0]
    purchase_orders = capabilities["capabilities"][1]

    if mutation == "fact-input-without-reference":
        inventory["inputs"][0]["bindingKind"] = "fact"
        inventory["inputs"][0].pop("satisfiableByFactType", None)
    elif mutation == "identifier-with-fact-reference":
        inventory["inputs"][0]["satisfiableByFactType"] = (
            "sapnexus:InventoryAvailabilityFact"
        )
    elif mutation == "primary-output-without-fact-type":
        inventory["outputs"][0].pop("factTypeRef")
    elif mutation == "unknown-relation-capability":
        relations["relations"] = [{
            "relationId": "relation.unknown-capability",
            "relationType": "dependsOn",
            "capabilityId": "MM.Unknown.Read",
            "dependsOnCapabilityId": purchase_orders["capabilityId"],
        }]
    elif mutation == "unknown-precondition-fact":
        relations["relations"] = [{
            "relationId": "relation.unknown-fact",
            "relationType": "precondition",
            "capabilityId": inventory["capabilityId"],
            "requiredFactType": "sapnexus:UnknownFact",
        }]
    elif mutation == "duplicate-authored-relation":
        edge = {
            "relationType": "dependsOn",
            "capabilityId": inventory["capabilityId"],
            "dependsOnCapabilityId": purchase_orders["capabilityId"],
        }
        relations["relations"] = [
            {"relationId": "relation.duplicate-1", **edge},
            {"relationId": "relation.duplicate-2", **edge},
        ]
    elif mutation == "depends-on-cycle":
        relations["relations"] = [
            {
                "relationId": "relation.cycle-1",
                "relationType": "dependsOn",
                "capabilityId": inventory["capabilityId"],
                "dependsOnCapabilityId": purchase_orders["capabilityId"],
            },
            {
                "relationId": "relation.cycle-2",
                "relationType": "dependsOn",
                "capabilityId": purchase_orders["capabilityId"],
                "dependsOnCapabilityId": inventory["capabilityId"],
            },
        ]
    else:
        raise AssertionError(f"unsupported mutation: {mutation}")

    return replace(sources, capabilities=capabilities, relations=relations)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("fact-input-without-reference", "SCHEMA_INVALID"),
        ("identifier-with-fact-reference", "SCHEMA_INVALID"),
        ("primary-output-without-fact-type", "SCHEMA_INVALID"),
        ("unknown-relation-capability", "RELATION_ENDPOINT_NOT_FOUND"),
        ("unknown-precondition-fact", "RELATION_ENDPOINT_NOT_FOUND"),
        ("duplicate-authored-relation", "DUPLICATE_ID"),
        ("depends-on-cycle", "DEPENDENCY_CYCLE"),
    ],
)
def test_contract_negative_matrix(mutation, expected_code):
    sources = mutated_sources(load_semantic_sources(REPO_ROOT), mutation)
    result = build_semantic_contracts(sources)
    assert result.report.valid is False
    assert expected_code in {item.code for item in result.report.issues}
~~~

该 helper 只构造内存文档，不写临时 repo 文件。

- [x] **Step 7: 运行 Task 3 GREEN**

~~~bash
.venv/bin/python -m pytest \
  agent/tests/test_registry_contract.py \
  agent/tests/test_semantic_planning_contract.py -v
~~~

Expected: 全部 PASS，且现有 Registry 安全测试不减少。

- [x] **Step 8: Review Task 3 checkpoint**

确认 `graph.py` 不导入 LLM/Gateway/orchestrator；`capability-relations.yaml` 没有 authored `producesFactType` / `consumesFactType`；旧 validator 的 secret/REST/OWL/eval 检查完整保留。

---

### Task 4: GoalSpec Reachability Validation

**Files:**
- Create: `agent/tests/fixtures/semantic_planning/goal-material-supply.yaml`
- Modify: `agent/sap_nexus_agent/semantic_planning/validation.py`
- Modify: `agent/tests/test_semantic_planning_contract.py`

**Interfaces:**
- Produces: `validate_goal_spec(graph, goal_spec) -> GoalReachabilityReport`。
- Consumes: valid `ImmutableSemanticGraph` and parsed GoalSpec mapping。

- [x] **Step 1: 创建首个 Goal fixture**

~~~yaml
goalSpecVersion: 1
goalId: goal.material-supply.fixture-001
goalType: sapnexus:MaterialSupplySnapshot
executionMode: READ_ONLY
desiredFactTypes:
  - sapnexus:InventoryAvailabilityFact
  - sapnexus:PurchaseOrderSupplyFact
constraints:
  - name: material
    semanticType: sapnexus:MaterialNumber
    value: DEMOA4B
  - name: plant
    semanticType: sapnexus:Plant
    value: "5300"
~~~

- [x] **Step 2: 写 reachability 失败测试**

~~~python
import yaml

from sap_nexus_agent.semantic_planning.validation import validate_goal_spec


def _valid_build():
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))
    assert result.graph is not None and result.snapshot is not None
    return result


def _load_fixture(name: str) -> dict:
    path = REPO_ROOT / "agent/tests/fixtures/semantic_planning" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_material_supply_goal_is_reachable():
    graph = _valid_build().graph
    goal = _load_fixture("goal-material-supply.yaml")
    jsonschema.validate(goal, _load_semantic_schema("goal-spec.schema.json"))
    report = validate_goal_spec(graph, goal)
    assert report.valid is True
    assert report.issues == ()
    assert report.reachable_fact_types == (
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
    )


def test_unknown_fact_is_not_a_capability_gap():
    graph = _valid_build().graph
    goal = _load_fixture("goal-material-supply.yaml")
    goal["desiredFactTypes"] = ["sapnexus:NotPublished"]
    report = validate_goal_spec(graph, goal)
    assert [item.code for item in report.issues] == ["UNKNOWN_FACT_TYPE"]
    assert report.capability_gaps == ()


def test_published_fact_without_active_producer_is_capability_gap():
    graph = _valid_build().graph
    fact_types = dict(graph.fact_types)
    fact_types["sapnexus:PublishedWithoutProducer"] = MappingProxyType({
        "factTypeId": "sapnexus:PublishedWithoutProducer",
        "name": "Published Without Producer",
        "description": "Test-only published fact.",
        "businessObject": "TestObject",
        "predicate": "sapnexus:hasPublishedWithoutProducer",
        "semanticType": "sapnexus:PublishedWithoutProducerValue",
        "keyedBy": ("sapnexus:TestKey",),
    })
    graph = replace(graph, fact_types=MappingProxyType(fact_types))
    report = validate_goal_spec(
        graph,
        {
            "goalSpecVersion": 1,
            "goalId": "goal.gap",
            "goalType": "sapnexus:GapGoal",
            "executionMode": "PLAN_ONLY",
            "desiredFactTypes": ["sapnexus:PublishedWithoutProducer"],
            "constraints": [],
        },
    )
    assert [item.code for item in report.issues] == ["CAPABILITY_GAP"]
    assert report.capability_gaps == ("sapnexus:PublishedWithoutProducer",)
~~~

在 test import 区加入 `from types import MappingProxyType`。该 Fact Type 只存在于测试复制的 graph，不污染正式 catalog。

- [x] **Step 3: 运行 Task 4 RED**

~~~bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -k "goal or reachable or gap" -v
~~~

Expected: FAIL，因为 `validate_goal_spec` 尚不存在。

- [x] **Step 4: 实现 Goal validator**

`validation.py` 增加：

~~~python
def _is_read_only(capability: Mapping[str, Any]) -> bool:
    governance = capability["governance"]
    return (
        capability["kind"] == "Function"
        and governance["sideEffect"] == "none"
        and governance["requiresApproval"] is False
        and governance["approvalPolicy"] == "not_required"
    )


def validate_goal_spec(
    graph: ImmutableSemanticGraph,
    goal_spec: dict[str, Any],
) -> GoalReachabilityReport:
    issues: list[ValidationIssue] = []
    reachable: list[str] = []
    gaps: list[str] = []
    mode = goal_spec.get("executionMode")
    desired = goal_spec.get("desiredFactTypes", [])

    _validate_goal_shape(goal_spec, issues)
    for index, fact_type_id in enumerate(desired):
        path = f"/desiredFactTypes/{index}"
        if fact_type_id not in graph.fact_types:
            issues.append(ValidationIssue(path, "UNKNOWN_FACT_TYPE", f"{fact_type_id} is not published"))
            continue
        active = tuple(
            capability_id
            for capability_id in graph.producers_by_fact_type.get(fact_type_id, ())
            if graph.capabilities[capability_id]["status"] == "active"
        )
        if not active:
            gaps.append(fact_type_id)
            issues.append(ValidationIssue(path, "CAPABILITY_GAP", f"{fact_type_id} has no active producer"))
            continue
        eligible = tuple(
            capability_id
            for capability_id in active
            if mode != "READ_ONLY" or _is_read_only(graph.capabilities[capability_id])
        )
        if not eligible:
            issues.append(
                ValidationIssue(
                    path,
                    "GOVERNANCE_VIOLATION",
                    f"{fact_type_id} has no READ_ONLY-compatible active producer",
                )
            )
            continue
        reachable.append(fact_type_id)

    ordered = sorted_issues(issues)
    return GoalReachabilityReport(
        valid=not ordered,
        issues=ordered,
        reachable_fact_types=tuple(sorted(set(reachable))),
        capability_gaps=tuple(sorted(set(gaps))),
    )
~~~

`_validate_goal_shape` 必须检查 version、mode、空 desired list、重复 desired Fact、重复 constraint name、constraint 必需字段和 scalar value；shape 错误统一 `SCHEMA_INVALID`。

- [x] **Step 5: 增加 READ_ONLY/PLAN_ONLY governance 测试并运行 GREEN**

验证 `sapnexus:PurchaseRequisitionCreatedFact`：

- `READ_ONLY` -> `GOVERNANCE_VIOLATION`。
- `PLAN_ONLY` -> reachable，且不产生 approval/execution。

Run:

~~~bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v
~~~

Expected: 全部 PASS。

- [x] **Step 6: Review Task 4 checkpoint**

确认 `CAPABILITY_GAP` 仅用于 published Fact 无 active producer；unknown Fact 始终是 `UNKNOWN_FACT_TYPE`。

---

### Task 5: PlanGraph Fixture and Deterministic Validation

**Files:**
- Create: `agent/tests/fixtures/semantic_planning/plan-material-supply.yaml`
- Modify: `agent/sap_nexus_agent/semantic_planning/validation.py`
- Modify: `agent/tests/test_semantic_planning_contract.py`

**Interfaces:**
- Produces: `validate_plan_graph(graph, snapshot, goal_spec, plan_graph) -> PlanValidationReport`。
- Consumes: valid graph/snapshot、GoalSpec、hand-authored PlanGraph。

- [x] **Step 1: 创建双节点无 edge fixture**

使用设计稿 `9.2` 的完整 YAML。`snapshotId` 不写固定 example hash；测试加载 fixture 后用 `build.snapshot.snapshot_id` 覆盖该字段：

~~~yaml
planGraphVersion: 1
planId: plan.material-supply.fixture-001
goalId: goal.material-supply.fixture-001
executionMode: READ_ONLY
snapshotId: sha256:0000000000000000000000000000000000000000000000000000000000000000
nodes:
  - nodeId: inventory
    capabilityId: MM.Inventory.GetAvailability
    parameterBindings:
      - parameterName: material
        source:
          kind: goalConstraint
          constraintName: material
      - parameterName: plant
        source:
          kind: goalConstraint
          constraintName: plant
    producesFactTypes:
      - sapnexus:InventoryAvailabilityFact
    governance:
      capabilityKind: Function
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
  - nodeId: purchaseOrders
    capabilityId: MM.PurchaseOrder.GetList
    parameterBindings:
      - parameterName: material
        source:
          kind: goalConstraint
          constraintName: material
      - parameterName: plant
        source:
          kind: goalConstraint
          constraintName: plant
    producesFactTypes:
      - sapnexus:PurchaseOrderSupplyFact
    governance:
      capabilityKind: Function
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
edges: []
topologicalOrder: [inventory, purchaseOrders]
goalOutputs:
  - factTypeId: sapnexus:InventoryAvailabilityFact
    producerNodeId: inventory
  - factTypeId: sapnexus:PurchaseOrderSupplyFact
    producerNodeId: purchaseOrders
~~~

- [x] **Step 2: 写 valid fixture 和关键 bad-case 测试**

~~~python
from copy import deepcopy

from sap_nexus_agent.semantic_planning.validation import validate_plan_graph


def _valid_plan_inputs():
    build = _valid_build()
    goal = _load_fixture("goal-material-supply.yaml")
    plan = _load_fixture("plan-material-supply.yaml")
    plan["snapshotId"] = build.snapshot.snapshot_id
    return build, goal, plan


def test_material_supply_plan_fixture_is_valid_and_has_no_edges():
    build, goal, plan = _valid_plan_inputs()
    jsonschema.validate(plan, _load_semantic_schema("plan-graph.schema.json"))
    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)
    assert report.valid is True
    assert report.issues == ()
    assert plan["edges"] == []


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda plan: plan.update(snapshotId="sha256:" + "0" * 64), "SNAPSHOT_MISMATCH"),
        (lambda plan: plan["nodes"][0].update(capabilityId="MM.Unknown.Read"), "UNKNOWN_CAPABILITY"),
        (
            lambda plan: plan["nodes"].append(deepcopy(plan["nodes"][0])),
            "DUPLICATE_ID",
        ),
        (
            lambda plan: plan["nodes"][0]["governance"].update(sideEffect="sap_write"),
            "PLAN_PROJECTION_MISMATCH",
        ),
        (
            lambda plan: plan["nodes"][0]["parameterBindings"].pop(0),
            "PARAMETER_SOURCE_MISSING",
        ),
        (
            lambda plan: plan["nodes"][0]["parameterBindings"].append(
                deepcopy(plan["nodes"][0]["parameterBindings"][0])
            ),
            "PARAMETER_SOURCE_DUPLICATE",
        ),
        (
            lambda plan: plan["goalOutputs"].pop(),
            "GOAL_OUTPUT_UNSATISFIED",
        ),
        (
            lambda plan: plan.update(bindingId="caller.supplied.binding"),
            "SCHEMA_INVALID",
        ),
    ],
)
def test_plan_fail_closed_matrix(mutate, expected_code):
    build, goal, plan = _valid_plan_inputs()
    mutate(plan)
    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)
    assert expected_code in {item.code for item in report.issues}
~~~

- [x] **Step 3: 运行 Task 5 RED**

~~~bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -k "plan" -v
~~~

Expected: FAIL，因为 `validate_plan_graph` 尚不存在。

- [x] **Step 4: 实现 validation pipeline**

`validate_plan_graph` 固定按以下顺序调用 helper：

~~~python
def validate_plan_graph(
    graph: ImmutableSemanticGraph,
    snapshot: RegistrySnapshot,
    goal_spec: dict[str, Any],
    plan_graph: dict[str, Any],
) -> PlanValidationReport:
    issues: list[ValidationIssue] = []
    _validate_plan_shape(plan_graph, issues)
    _validate_snapshot_and_goal_identity(snapshot, goal_spec, plan_graph, issues)
    node_index = _validate_nodes_and_projections(graph, plan_graph, issues)
    _validate_parameter_sources(graph, goal_spec, node_index, issues)
    _validate_edges(graph, node_index, plan_graph, issues)
    _validate_topological_order(node_index, plan_graph, issues)
    _validate_plan_governance(goal_spec, node_index, issues)
    _validate_goal_outputs(goal_spec, node_index, plan_graph, issues)
    ordered = sorted_issues(issues)
    return PlanValidationReport(valid=not ordered, issues=ordered)
~~~

Helper contract：

- `_validate_plan_shape`：v1、唯一 node/edge ID、union 字段互斥；shape 错误 `SCHEMA_INVALID` / `DUPLICATE_ID`。
- `_validate_plan_shape`：递归拒绝 `bindingId`、`rfcName`、URL、credential、header、executor mapping 等技术字段。
- `_validate_snapshot_and_goal_identity`：snapshot、goalId、executionMode 必须完全相同；snapshot 不同报 `SNAPSHOT_MISMATCH`。
- `_validate_nodes_and_projections`：capability 必须 registered；`producesFactTypes` 和 governance 必须等于 Registry；不等报 `PLAN_PROJECTION_MISMATCH`。
- `_validate_parameter_sources`：required input 恰有一个 source；goal constraint/literal 的 semanticType 必须匹配 input semanticType；literal 只供 identifier 且 value 为 scalar；factField 只供 fact input，并且 `field` 必须是 producer capability 上具有同一 `factTypeRef` 的 output。
- `_validate_edges`：data edge 与 factField 一一对应；dependency edge 必须匹配 authored `dependsOn`，方向为 prerequisite -> dependent。
- `_validate_topological_order`：恰好覆盖每个 node 一次，且所有 edge source index < target index。
- `_validate_plan_governance`：`READ_ONLY` 所有 node 必须通过 `_is_read_only`；不通过报 `GOVERNANCE_VIOLATION`。
- `_validate_goal_outputs`：每个 desired Fact 恰有 producer，且 producer node 的 projection 包含该 Fact；否则 `GOAL_OUTPUT_UNSATISFIED`。

- [x] **Step 5: 增加 data/dependency edge 专用 fixture tests**

在测试内构造 isolated sources：

1. 新增一个 `bindingKind=fact` 的 consumer capability。
2. 添加匹配 `factField` + `data` edge，期望 PASS。
3. 删除 data edge，期望 `EDGE_INCONSISTENT`。
4. 改 Fact Type，期望 `FACT_TYPE_MISMATCH`。
5. 添加 authored `dependsOn`，PlanGraph 使用 prerequisite -> dependent，期望 PASS。
6. 反转 edge 或制造 cycle，分别期望 `EDGE_INCONSISTENT` / `DEPENDENCY_CYCLE`。

断言使用 structured code + exact JSON Pointer path，不用 message substring。

- [x] **Step 6: 运行 Task 5 GREEN**

~~~bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v
~~~

Expected: 全部 PASS，首个 pilot plan 保持 `edges: []`。

- [x] **Step 7: Review Task 5 checkpoint**

确认 validator 不生成、修复或执行 PlanGraph；它只验证传入 fixture。确认任何 technical executor 字段均被 plan schema 的 `additionalProperties: false` 拒绝。

---

### Task 6: Single Release-Gate CLI and Compatibility Regression

**Files:**
- Create: `scripts/validate-semantic-planning-contract.py`
- Modify: `scripts/verify-agent-callplan-evidence.sh`
- Modify: `agent/tests/test_registry_loader.py`
- Modify: `agent/tests/test_semantic_planning_contract.py`

**Interfaces:**
- Produces: `.venv/bin/python scripts/validate-semantic-planning-contract.py`。
- Preserves: current Registry CLI and all Agent/Gateway execution contracts。

- [x] **Step 1: 写 CLI 失败测试**

在 `test_semantic_planning_contract.py` 追加：

~~~python
import subprocess
import sys


def test_semantic_planning_cli_validates_legacy_and_semantic_contracts():
    completed = subprocess.run(
        [sys.executable, "scripts/validate-semantic-planning-contract.py"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Legacy registry contract valid" in completed.stdout
    assert "Semantic planning contract valid" in completed.stdout
    assert "snapshotId=sha256:" in completed.stdout
~~~

- [x] **Step 2: 运行 Task 6 RED**

~~~bash
.venv/bin/python -m pytest \
  agent/tests/test_semantic_planning_contract.py::test_semantic_planning_cli_validates_legacy_and_semantic_contracts -v
~~~

Expected: FAIL，因为 CLI 尚不存在。

- [x] **Step 3: 实现组合 CLI**

`scripts/validate-semantic-planning-contract.py`：

~~~python
#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = REPO_ROOT / "agent"
for path in (str(REPO_ROOT), str(AGENT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from scripts.validate_registry_contract import (  # noqa: E402
    load_registry_contract,
    validate_registry_contract,
)
from sap_nexus_agent.semantic_planning.loader import (  # noqa: E402
    SourceLoadError,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.validation import (  # noqa: E402
    build_semantic_contracts,
)


def main() -> int:
    legacy = load_registry_contract(REPO_ROOT / "registry/capabilities.yaml")
    legacy_errors = validate_registry_contract(legacy, repo_root=REPO_ROOT)
    if legacy_errors:
        for error in legacy_errors:
            print(f"legacy: {error}", file=sys.stderr)
        return 1
    print("Legacy registry contract valid")

    try:
        sources = load_semantic_sources(REPO_ROOT)
    except SourceLoadError as exc:
        print(f"SCHEMA_INVALID {exc.path}: {exc.message}", file=sys.stderr)
        return 1
    result = build_semantic_contracts(sources)
    if not result.report.valid:
        for issue in result.report.issues:
            print(f"{issue.code} {issue.path}: {issue.message}", file=sys.stderr)
        return 1
    assert result.snapshot is not None
    print(f"Semantic planning contract valid: snapshotId={result.snapshot.snapshot_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
~~~

- [x] **Step 4: 加入统一 evidence script**

在 `scripts/verify-agent-callplan-evidence.sh` 的 pytest 之前增加：

~~~bash
"$PYTHON_BIN" scripts/validate-semantic-planning-contract.py
~~~

保留所有现有 pytest、三个 eval 和 OpenSpec 命令。

- [x] **Step 5: 增加现有 runtime compatibility assertions**

在 `agent/tests/test_registry_loader.py` 追加：

~~~python
def test_registry_v2_metadata_does_not_change_runtime_descriptors():
    catalog = load_intent_catalog(str(REPO_ROOT))
    assert tuple(sorted(catalog.capability_ids)) == (
        "MM.Inventory.GetAvailability",
        "MM.PR.CreateDraft",
        "MM.PurchaseOrder.GetList",
    )
    inventory = catalog.find("MM.Inventory.GetAvailability")
    assert inventory is not None
    assert {item.name for item in inventory.inputs} == {"material", "plant", "unit"}
~~~

此测试只证明旧 loader 忽略新增 planning metadata，不把它塞入当前 `CallPlan`。

- [x] **Step 6: 运行 focused 与 full regression**

~~~bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python scripts/validate-semantic-planning-contract.py
.venv/bin/python -m pytest agent/tests/test_contract_files.py -v
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v
.venv/bin/python -m pytest agent/tests/test_registry_loader.py -v
scripts/verify-agent-callplan-evidence.sh
~~~

Expected:

- 两个 CLI exit 0。
- focused pytest 全部 PASS。
- evidence script 中 Agent tests、inventory eval、seed eval、PR eval、OpenSpec 全部 PASS。
- PostHog flush 网络噪音不改变 exit code 和 `7 passed, 0 failed` 的 OpenSpec authoritative result。

- [x] **Step 7: Static boundary scan**

~~~bash
rg -n "gateway_client|orchestrator|llm_client|openai|requests|httpx|sapjco" \
  agent/sap_nexus_agent/semantic_planning
rg -n "bindingId|rfcName|credential|url|headers|executorMapping" \
  agent/tests/fixtures/semantic_planning schemas/goal-spec.schema.json schemas/plan-graph.schema.json
~~~

Expected: 第一条无结果；第二条只允许出现在 schema 的显式禁止测试/说明中，正式 fixtures 无结果。

- [x] **Step 8: Review Task 6 checkpoint**

核对 `git diff --name-only`：不得出现 frontend、Java Gateway、`orchestrator.py`、`call_plan.py`、`reasoning_fact.py` 或 SAP runtime 文件。

---

### Task 7: OpenSpec Evidence, Documentation Sync, and Closeout Gate

**Files:**
- Modify: `openspec/changes/sap-nexus-semantic-planning-foundation/tasks.md`
- Create: `docs/superpowers/reports/2026-07-19-sap-nexus-semantic-planning-foundation-verify.md`
- Modify: `docs/runbooks/10-capability-composition-contract.md`
- Modify: `docs/runbooks/README.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Inspect only: `docs/wiki/sap-nexus-agent-technical-architecture.md`

**Interfaces:**
- Produces: 可审计的 S1 verification report 和 S2 handoff。
- Requires: Task 1-6 全部验证通过；archive 仍需用户确认。

- [x] **Step 1: 更新 OpenSpec task evidence**

仅在对应命令通过后勾选 task，并在 `tasks.md` 记录精确命令。不得用“代码已写”替代验证证据。

- [x] **Step 2: 写 verification report**

报告必须包含：

~~~markdown
# Semantic Planning Foundation Verification Report

## Scope
- S1 contracts, immutable graph, snapshot, GoalSpec/PlanGraph validation only.
- No planner generation, Gateway/SAP execution, frontend, or runtime orchestration.

## Contract Evidence
| Gate | Command | Result |
|---|---|---|
| Legacy Registry | `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` | exit 0 |
| Semantic Planning | `.venv/bin/python scripts/validate-semantic-planning-contract.py` | exit 0 + snapshotId |
| Focused Tests | `.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v` | PASS; observed summary copied below |
| Full Evidence | `scripts/verify-agent-callplan-evidence.sh` | exit 0 |
| OpenSpec | `openspec validate --all --strict` | PASS; observed summary copied below |

## Evidence Output
- Copy the final summary line from the focused pytest command.
- Copy the `Totals: N passed, 0 failed` line from OpenSpec validation.

## Boundary Evidence
- Current selector/orchestrator/CallPlan/ReasoningFact/Gateway/frontend unchanged.
- OpenHarness and graph database are not runtime dependencies.
- First pilot fixture contains two READ nodes and zero edges.

## Residual Scope
- S2: natural language -> GoalSpec candidate, PlanDraft, deterministic PlanCompiler, dry-run.
- S3: read-only execution and Fact lineage aggregation.
~~~

- [x] **Step 3: 同步 runbook 和 roadmap**

- `runbook 10`：S1 状态改为 implemented/verified，记录 snapshot/graph/report contracts；Next Start Here 改为 S2 design。
- `runbooks/README`：链接 OpenSpec archive 和 verification report；Next recommended change 改为 `sap-nexus-planner-dry-run`。
- `implementation-roadmap`：S1 标记完成，S2 仍是 dry-run only，S3 仍是 read-only execution。
- 对照检查 `technical-architecture`；本 change 不修改它。若实现与已批准设计不一致，先修复实现，不用文档漂移掩盖 scope change。

- [x] **Step 4: 运行 closeout verification**

~~~bash
git diff --check
openspec list --json
openspec validate --all --strict
scripts/verify-agent-callplan-evidence.sh
git status --short -- .
~~~

Expected:

- `git diff --check` exit 0。
- OpenSpec strict validation `0 failed`。
- evidence script exit 0。
- status 只包含本 change 的代码、contract、test、OpenSpec 和 docs 文件。

- [x] **Step 5: 用户确认后进入 verify/archive**

先使用 `requesting-code-review` 做实现审查，再使用 `comet-verify`。验证通过后向用户展示证据并请求 archive 确认；只有确认后使用 `comet-archive`。未经用户要求不 commit。

---

## Task Dependency Order

~~~text
Task 1 contracts/catalogs
  -> Task 2 loader/snapshot primitives
  -> Task 3 graph/contract validation
  -> Task 4 goal reachability
  -> Task 5 plan validation
  -> Task 6 combined release gate + regression
  -> Task 7 evidence/docs/verify/archive
~~~

Task 4 和 Task 5 都依赖 Task 3 的 valid graph；Task 6 依赖所有 contract APIs 稳定。不要并行编辑共享的 `validation.py` 或 `test_semantic_planning_contract.py`。

## Definition of Done

- Registry v2 和三个 Fact Type 原子发布。
- relation catalog 只允许非派生关系，首版为空。
- immutable graph 精确导出三条 producer edge。
- Snapshot 对四份 source 做 deterministic canonical SHA-256。
- 三种 report 和全部批准 error codes 有 focused evidence。
- 首个 Goal/Plan fixtures 通过，Plan 保持双 READ node、零 edge。
- current single-capability runtime 与 write approval 行为无回归。
- combined CLI、full evidence script、OpenSpec strict validation 全部 exit 0。
- runbook、roadmap、verification report 与 archive state 同步。
- 没有 LLM planner、Gateway/SAP execution、frontend、graph database、OpenHarness runtime 或 write composition scope leakage。

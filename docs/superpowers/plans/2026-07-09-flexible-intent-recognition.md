---
change: flexible-intent-recognition
design-doc: docs/superpowers/specs/2026-07-09-flexible-intent-recognition-design.md
base-ref: 1598c3dce4572d29bd6bd7a3256fa0d0bf855514
archived-with: 2026-07-09-flexible-intent-recognition
---

# Flexible Intent Recognition 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Agent 意图识别从「库存-only 写死」重构为「从 registry active capability 动态派生闭集」，使已注册的 `MM.PurchaseOrder.GetList` 可通过自然语言触发。

**Architecture:** 新增 `registry_loader.py` 从 `registry/capabilities.yaml` 读取 active capability 构建 `IntentCatalog`；`llm_intent.py` 的 prompt 动态注入能力元数据，LLM 直接选 `capabilityId`（不经 intent 名中转），闭集校验 + required 参数校验；fallback 从 `parse_inventory_intent` 改 `parse_intent`（统一规则解析器，已支持 PO）；`intent.py` 的 `IntentParseResult` 加 `capability_id` 字段，`select_capability` 优先用 `capability_id`；`cli.py` 入口改 `run_query` + 注入 catalog。

**Tech Stack:** Python 3.11+, pytest, PyYAML (已有依赖)

**Design Doc:** `docs/superpowers/specs/2026-07-09-flexible-intent-recognition-design.md`

## Global Constraints

- 不改 `registry/capabilities.yaml` schema 和内容（复用现有 description/inputs/businessObject 字段）
- 不改前端事件流、不改 LLM client、不改下游 fact/narrator/gateway
- 安全失败原则：任何 LLM/registry 异常降级为 unsupported 或 rule fallback，不让 agent 崩溃
- `PYTHONPATH=agent` 是运行测试的前置条件
- `.venv/bin/python` 是项目解释器
- `build_intent_adapter` 的 `catalog` 参数必须可选（默认 `None` 时内部调 `load_intent_catalog()`），否则会破坏 `workbench_output.py` 中的现有调用 `build_intent_adapter(intent_mode)`
- IntentParseResult 加字段必须带默认值 `None`，保持 frozen dataclass 向后兼容

archived-with: 2026-07-09-flexible-intent-recognition
---

## File Structure

| 文件 | 职责 | 改动类型 |
|------|------|----------|
| `agent/sap_nexus_agent/registry_loader.py` | 从 `registry/capabilities.yaml` 派生 `IntentCatalog`（capability 闭集 + 描述符） | 新增 |
| `agent/sap_nexus_agent/intent.py` | `IntentParseResult` 加 `capability_id` 字段 | 小改 |
| `agent/sap_nexus_agent/capability_selector.py` | `select_capability` 优先用 `capability_id` | 小改 |
| `agent/sap_nexus_agent/llm_intent.py` | 动态 prompt + 闭集校验 + fallback 修复 + 别名扩展 | 核心重构 |
| `agent/sap_nexus_agent/cli.py` | 入口改 `run_query` + catalog 注入 | 小改 |
| `agent/tests/test_registry_loader.py` | registry_loader 单元测试 | 新增 |
| `agent/tests/test_llm_intent.py` | LLM 意图层测试更新 | 更新 |
| `agent/tests/test_orchestrator.py` | run_query + LLM adapter PO 集成用例 | 更新 |

**不受影响（不修改）：** `workbench_output.py`（`build_intent_adapter(intent_mode)` 无 catalog 参数仍可用，因 catalog 可选）、`test_intent.py`（规则解析器行为不变）、`orchestrator.py`（`run_query`/`run_inventory_query` 已存在，无需改）、前端。

archived-with: 2026-07-09-flexible-intent-recognition
---

### Task 1: Registry Loader（新增 registry_loader.py）

**Files:**
- Create: `agent/sap_nexus_agent/registry_loader.py`
- Test: `agent/tests/test_registry_loader.py`

**Interfaces:**
- Produces: `InputDescriptor`, `CapabilityDescriptor`, `IntentCatalog` (frozen dataclass), `load_intent_catalog(repo_root=None) -> IntentCatalog`
- `IntentCatalog.capabilities: tuple[CapabilityDescriptor, ...]`
- `IntentCatalog.capability_ids: frozenset[str]` -- 闭集校验 O(1) 查找
- `IntentCatalog.find(capability_id) -> CapabilityDescriptor | None` -- required 参数校验用
- `CapabilityDescriptor.inputs: tuple[InputDescriptor, ...]`
- `InputDescriptor.name: str`, `InputDescriptor.required: bool`, `InputDescriptor.type: str`

^- [x] **Step 1: 编写失败测试**

创建 `agent/tests/test_registry_loader.py`：

```python
from pathlib import Path

from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    InputDescriptor,
    IntentCatalog,
    load_intent_catalog,
)

# 仓库根目录：agent/tests/ 向上两级
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_intent_catalog_returns_active_capabilities():
    catalog = load_intent_catalog(str(REPO_ROOT))

    assert "MM.Inventory.GetAvailability" in catalog.capability_ids
    assert "MM.PurchaseOrder.GetList" in catalog.capability_ids
    assert len(catalog.capabilities) == 2


def test_load_intent_catalog_filters_inactive():
    """catalog 只含 active capability（当前 registry 两个都 active）。"""
    catalog = load_intent_catalog(str(REPO_ROOT))

    for cap in catalog.capabilities:
        assert cap.capability_id in catalog.capability_ids


def test_inventory_descriptor_inputs_parsed():
    catalog = load_intent_catalog(str(REPO_ROOT))
    inv = catalog.find("MM.Inventory.GetAvailability")

    assert inv is not None
    assert inv.domain == "MM"
    assert inv.business_object == "InventoryStock"
    input_names = {inp.name for inp in inv.inputs}
    assert input_names == {"material", "plant", "unit"}
    material = next(inp for inp in inv.inputs if inp.name == "material")
    assert material.required is True
    unit = next(inp for inp in inv.inputs if inp.name == "unit")
    assert unit.required is False


def test_purchase_order_descriptor_inputs_parsed():
    catalog = load_intent_catalog(str(REPO_ROOT))
    po = catalog.find("MM.PurchaseOrder.GetList")

    assert po is not None
    assert po.business_object == "PurchaseOrder"
    input_names = {inp.name for inp in po.inputs}
    assert input_names == {"poNumber", "vendor", "plant", "material"}
    # PO 所有 input 均 optional
    assert all(not inp.required for inp in po.inputs)


def test_find_returns_none_for_unknown_capability():
    catalog = load_intent_catalog(str(REPO_ROOT))

    assert catalog.find("MM.Nonexistent.Capability") is None


def test_load_intent_catalog_walks_up_to_find_registry():
    """无 repo_root 参数时，从 __file__ 向上查找 registry/。"""
    catalog = load_intent_catalog()

    assert "MM.Inventory.GetAvailability" in catalog.capability_ids


def test_load_intent_catalog_returns_empty_when_registry_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv("SAP_NEXUS_AGENT_ROOT", raising=False)
    catalog = load_intent_catalog(str(tmp_path))

    assert catalog.capabilities == ()
    assert catalog.capability_ids == frozenset()


def test_empty_catalog_find_returns_none():
    empty = IntentCatalog(capabilities=(), capability_ids=frozenset())

    assert empty.find("anything") is None
```

^- [x] **Step 2: 运行测试确认失败**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_registry_loader.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'sap_nexus_agent.registry_loader'`

^- [x] **Step 3: 实现 registry_loader.py**

创建 `agent/sap_nexus_agent/registry_loader.py`：

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class InputDescriptor:
    name: str
    semantic_name: str
    required: bool
    type: str


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    name: str
    description: str
    domain: str
    business_object: str
    inputs: tuple[InputDescriptor, ...]


@dataclass(frozen=True)
class IntentCatalog:
    capabilities: tuple[CapabilityDescriptor, ...]
    capability_ids: frozenset[str]

    def find(self, capability_id: str) -> CapabilityDescriptor | None:
        for cap in self.capabilities:
            if cap.capability_id == capability_id:
                return cap
        return None


def _empty_catalog() -> IntentCatalog:
    return IntentCatalog(capabilities=(), capability_ids=frozenset())


def _resolve_registry_path(repo_root: str | None) -> str | None:
    # 1. 显式 repo_root
    if repo_root:
        candidate = Path(repo_root) / "registry" / "capabilities.yaml"
        if candidate.exists():
            return str(candidate)

    # 2. SAP_NEXUS_AGENT_ROOT 环境变量
    env_root = os.environ.get("SAP_NEXUS_AGENT_ROOT")
    if env_root:
        candidate = Path(env_root) / "registry" / "capabilities.yaml"
        if candidate.exists():
            return str(candidate)

    # 3. 从本文件位置向上查找 registry/ 目录
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / "registry" / "capabilities.yaml"
        if candidate.exists():
            return str(candidate)

    # 4. cwd 兜底
    candidate = Path.cwd() / "registry" / "capabilities.yaml"
    if candidate.exists():
        return str(candidate)

    return None


def load_intent_catalog(repo_root: str | None = None) -> IntentCatalog:
    """从 registry/capabilities.yaml 读取 active capability，构建 IntentCatalog。

    找不到 registry 文件时返回空 catalog（不抛异常，LLM 路径自然降级为 unsupported）。
    """
    registry_path = _resolve_registry_path(repo_root)
    if registry_path is None:
        return _empty_catalog()

    try:
        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return _empty_catalog()

    if not isinstance(data, dict):
        return _empty_catalog()

    raw_capabilities = data.get("capabilities") or []
    descriptors: list[CapabilityDescriptor] = []
    for cap in raw_capabilities:
        if not isinstance(cap, dict):
            continue
        if cap.get("status") != "active":
            continue
        inputs = tuple(
            InputDescriptor(
                name=inp["name"],
                semantic_name=inp.get("semanticName", inp["name"]),
                required=bool(inp.get("required", False)),
                type=inp.get("type", "string"),
            )
            for inp in (cap.get("inputs") or [])
            if isinstance(inp, dict) and "name" in inp
        )
        descriptors.append(
            CapabilityDescriptor(
                capability_id=cap["capabilityId"],
                name=cap.get("name", ""),
                description=cap.get("description", ""),
                domain=cap.get("domain", ""),
                business_object=cap.get("businessObject", ""),
                inputs=inputs,
            )
        )

    return IntentCatalog(
        capabilities=tuple(descriptors),
        capability_ids=frozenset(d.capability_id for d in descriptors),
    )
```

^- [x] **Step 4: 运行测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_registry_loader.py -v`
Expected: PASS -- 全部 8 个测试通过

^- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/registry_loader.py agent/tests/test_registry_loader.py
git commit -m "feat: add registry_loader to derive IntentCatalog from active capabilities"
```

archived-with: 2026-07-09-flexible-intent-recognition
---

### Task 2: IntentParseResult 扩展 capability_id + select_capability 优先级

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py` (IntentParseResult dataclass, 第 42-49 行)
- Modify: `agent/sap_nexus_agent/capability_selector.py` (select_capability, 第 36 行)
- Test: `agent/tests/test_intent.py` (回归验证不破坏)

**Interfaces:**
- Consumes: 无（独立改动）
- Produces: `IntentParseResult.capability_id: str | None = None`（新字段，默认 None，向后兼容）
- Produces: `select_capability` 优先 `parse_result.capability_id`，回退 `INTENT_TO_CAPABILITY.get(intent)`

^- [x] **Step 1: 编写失败测试**

在 `agent/tests/test_llm_intent.py` 末尾添加（验证 capability_id 优先级）：

```python
from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.intent import IntentParseResult


def test_select_capability_prefers_capability_id_over_intent():
    result = IntentParseResult(
        intent=None,
        capability_id="MM.PurchaseOrder.GetList",
        parameters={"poNumber": "DEMOPO1"},
        missing_parameters=[],
    )

    selected = select_capability(result)

    assert selected.capability_id == "MM.PurchaseOrder.GetList"
    assert selected.error_type is None


def test_select_capability_falls_back_to_intent_mapping():
    result = IntentParseResult(
        intent="inventory_availability",
        parameters={"material": "DEMOA1", "plant": "1000"},
        missing_parameters=[],
    )

    selected = select_capability(result)

    assert selected.capability_id == "MM.Inventory.GetAvailability"
    assert selected.error_type is None
```

^- [x] **Step 2: 运行测试确认失败**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_select_capability_prefers_capability_id_over_intent -v`
Expected: FAIL -- `TypeError: IntentParseResult ... got an unexpected keyword argument 'capability_id'`

^- [x] **Step 3: intent.py 加 capability_id 字段**

修改 `agent/sap_nexus_agent/intent.py` 第 42-49 行，在 `contains_odata_override` 后加 `capability_id` 字段：

```python
@dataclass(frozen=True)
class IntentParseResult:
    intent: str | None
    parameters: dict[str, str]
    missing_parameters: list[str]
    clarification: str | None = None
    contains_rfc_name: bool = False
    contains_odata_override: bool = False
    capability_id: str | None = None
```

^- [x] **Step 4: capability_selector.py 优先 capability_id**

修改 `agent/sap_nexus_agent/capability_selector.py` 第 36 行：

将：
```python
    capability_id = INTENT_TO_CAPABILITY.get(parse_result.intent)
```

改为：
```python
    capability_id = parse_result.capability_id or INTENT_TO_CAPABILITY.get(parse_result.intent)
```

^- [x] **Step 5: 运行测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_select_capability_prefers_capability_id_over_intent agent/tests/test_llm_intent.py::test_select_capability_falls_back_to_intent_mapping -v`
Expected: PASS

^- [x] **Step 6: 回归验证 test_intent.py 不破坏**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_intent.py -v`
Expected: PASS -- 全部现有测试通过（规则解析器行为不变，仅加字段）

^- [x] **Step 7: 提交**

```bash
git add agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/capability_selector.py agent/tests/test_llm_intent.py
git commit -m "feat: add capability_id to IntentParseResult and prioritize it in select_capability"
```

archived-with: 2026-07-09-flexible-intent-recognition
---

### Task 3: LLM 意图层柔性重构（llm_intent.py 核心重构）

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py` (全文件重构)
- Test: `agent/tests/test_llm_intent.py` (更新现有用例 + 新增 PO 用例)

**Interfaces:**
- Consumes: `IntentCatalog`, `CapabilityDescriptor`, `InputDescriptor`, `load_intent_catalog` from Task 1; `IntentParseResult.capability_id` from Task 2; `parse_intent` from `intent.py`
- Produces:
  - `parse_with_llm(text, client, catalog) -> IntentParseResult`
  - `parse_with_hybrid(text, client=None, *, catalog=None) -> IntentParseResult`
  - `build_intent_adapter(mode, catalog=None) -> Callable[[str], IntentParseResult]`
  - `_messages(text, catalog)` -- 动态注入 active capability
  - `_payload_to_parse_result(payload, catalog)` -- 闭集校验 + required 参数校验
  - `_extract_parameters(raw_parameters, descriptor)` -- 别名归一 + per-capability 白名单
  - `_clarification_for(capability_id, missing)` -- 按能力生成 clarification

**关键设计决策（设计文档未显式提及但为正确性必需）：**
1. `_requires_safe_fallback` 必须改为检查 `capability_id`：LLM 路径填 `capability_id` 不填 `intent`，若仍用 `result.intent is None` 判断 fallback，hybrid 将永远 fallback，LLM 路径形同虚设。
2. `build_intent_adapter(mode, catalog=None)` 的 `catalog` 可选：`workbench_output.py` 调用 `build_intent_adapter(intent_mode)` 无 catalog 参数，必须保持向后兼容。
3. PO capability 所有 inputs 均 `required: false`（registry 定义），LLM 路径 required 校验不会拦截空参数的 PO 查询 -- 此为设计预期，gateway 验证作为安全网。

^- [x] **Step 1: 编写新增 PO LLM 测试（失败 -- catalog 参数尚不存在）**

在 `agent/tests/test_llm_intent.py` 顶部 import 区添加：

```python
from sap_nexus_agent.registry_loader import load_intent_catalog
from sap_nexus_agent.intent import parse_intent
```

在文件末尾添加新测试用例：

```python
# --- Flexible intent: PO via LLM path ---


def test_parse_with_llm_selects_purchase_order():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查询采购订单DEMOPO1", client, catalog)

    assert result.capability_id == "MM.PurchaseOrder.GetList"
    assert result.intent is None
    assert result.parameters == {"poNumber": "DEMOPO1"}
    assert result.missing_parameters == []


def test_parse_with_llm_rejects_capability_not_in_closed_set():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Material.CreateBom",
        "parameters": {"material": "X"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查物料", client, catalog)

    assert result.capability_id is None
    assert result.intent is None
    assert result.parameters == {}


def test_parse_with_llm_normalizes_po_aliases():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"purchaseOrderNumber": "DEMOPO1", "supplier": "DEMOV1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查询采购订单", client, catalog)

    assert result.parameters == {"poNumber": "DEMOPO1", "vendor": "DEMOV1"}


def test_parse_with_llm_drops_unregistered_parameter_for_po():
    """LLM 返回 PO 不支持的参数应被丢弃。"""
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1", "unit": "EA"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("查询采购订单", client, catalog)

    # unit 不在 PO inputs 中，应被丢弃
    assert result.parameters == {"poNumber": "DEMOPO1"}


def test_hybrid_falls_back_to_parse_intent_for_po():
    """hybrid fallback 应使用 parse_intent（支持 PO），非 parse_inventory_intent。"""
    client = FakeLlmClient(unavailable=True)
    catalog = load_intent_catalog()

    result = parse_with_hybrid("查询采购订单DEMOPO1", client, catalog=catalog)

    # parse_intent 识别 PO 关键词 -> intent="purchase_order_list"
    assert result.intent == "purchase_order_list"
    assert result.parameters.get("poNumber") == "DEMOPO1"
    assert result.capability_id is None  # 规则路径不填 capability_id


def test_hybrid_returns_llm_result_when_capability_id_set():
    """LLM 成功返回 capability_id 时不应 fallback（_requires_safe_fallback 修复验证）。"""
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_hybrid("查询采购订单DEMOPO1", client, catalog=catalog)

    # 不应 fallback 到 parse_intent
    assert result.capability_id == "MM.PurchaseOrder.GetList"
    assert result.intent is None


def test_llm_prompt_injects_purchase_order_capability():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA1", "plant": "1000"},
        "missingParameters": [],
        "clarification": None,
    })

    parse_with_llm("查库存", client, catalog)

    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "MM.PurchaseOrder.GetList" in system_prompt
    assert "MM.Inventory.GetAvailability" in system_prompt
    # 不再写死库存 only
    assert "inventory intent" not in system_prompt
```

^- [x] **Step 2: 运行新测试确认失败**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_parse_with_llm_selects_purchase_order -v`
Expected: FAIL -- `TypeError: parse_with_llm() takes 2 positional arguments but 3 were given`

^- [x] **Step 3: 重写 llm_intent.py**

将 `agent/sap_nexus_agent/llm_intent.py` 全文件替换为：

```python
from __future__ import annotations

import json
from typing import Protocol

from sap_nexus_agent.intent import (
    IntentParseResult,
    _detect_odata_override,
    parse_intent,
)
from sap_nexus_agent.llm_client import LlmUnavailable, OpenAiCompatibleLlmClient
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    InputDescriptor,
    IntentCatalog,
    load_intent_catalog,
)


class JsonLlmClient(Protocol):
    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 400) -> dict[str, object]:
        ...


def parse_with_llm(text: str, client: JsonLlmClient, catalog: IntentCatalog) -> IntentParseResult:
    try:
        payload = client.chat_json(_messages(text, catalog), temperature=0.0, max_tokens=400)
    except (LlmUnavailable, json.JSONDecodeError, ValueError, TypeError):
        raise LlmUnavailable("LLM intent parsing unavailable")
    return _payload_to_parse_result(payload, catalog)


def parse_with_hybrid(text: str, client: JsonLlmClient | None = None, *, catalog: IntentCatalog | None = None) -> IntentParseResult:
    if catalog is None:
        catalog = load_intent_catalog()
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        result = parse_with_llm(text, llm_client, catalog)
        if _requires_safe_fallback(result):
            return parse_intent(text)
        return result
    except LlmUnavailable:
        return parse_intent(text)


def build_intent_adapter(mode: str, catalog: IntentCatalog | None = None):
    if catalog is None:
        catalog = load_intent_catalog()
    normalized = mode.lower()
    if normalized == "rule":
        return parse_intent
    if normalized == "llm":
        return lambda text: _parse_llm_only(text, catalog)
    if normalized == "hybrid":
        return lambda text: parse_with_hybrid(text, catalog=catalog)
    raise ValueError(f"Unsupported intent mode: {mode}")


def _parse_llm_only(text: str, catalog: IntentCatalog) -> IntentParseResult:
    try:
        return parse_with_llm(text, OpenAiCompatibleLlmClient(), catalog)
    except LlmUnavailable:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])


def _requires_safe_fallback(result: IntentParseResult) -> bool:
    if result.contains_rfc_name or result.contains_odata_override:
        return True
    # LLM path fills capability_id; rule path fills intent.
    # Fall back only when neither is set (unsupported / ambiguous).
    return result.capability_id is None and result.intent is None


def _messages(text: str, catalog: IntentCatalog) -> list[dict[str, str]]:
    capabilities_desc = "\n".join(
        f"- capabilityId: {c.capability_id}\n"
        f"  description: {c.description}\n"
        f"  inputs:\n{_format_inputs(c.inputs)}"
        for c in catalog.capabilities
    )
    return [
        {
            "role": "system",
            "content": (
                "You extract SAP Nexus read-only query intent as strict JSON. "
                "Select exactly one capabilityId from the registered closed set below, "
                "and extract parameters from the user query. "
                "If none matches, set capabilityId=null. "
                "Never output rfcName or raw SAP BAPI/RFC names. "
                "Return keys: capabilityId, parameters, missingParameters, clarification.\n\n"
                f"Registered capabilities:\n{capabilities_desc}"
            ),
        },
        {"role": "user", "content": text},
    ]


def _format_inputs(inputs: tuple[InputDescriptor, ...]) -> str:
    if not inputs:
        return "    (none)"
    lines = []
    for inp in inputs:
        req = "required" if inp.required else "optional"
        lines.append(f"    - {inp.name} ({inp.type}, {req})")
    return "\n".join(lines)


def _payload_to_parse_result(payload: dict[str, object], catalog: IntentCatalog) -> IntentParseResult:
    if not isinstance(payload, dict):
        raise LlmUnavailable("LLM payload is not an object")

    contains_rfc_name = any(str(key).lower() == "rfcname" for key in payload)
    # Reuse the rule-path OData override detector over the serialized payload so
    # the LLM path forms the same double-layer defense (Agent rejects first,
    # Java guard rejects again). Catches override fields in keys or values.
    contains_odata_override = _detect_odata_override(json.dumps(payload, ensure_ascii=False))
    if contains_rfc_name or contains_odata_override:
        return IntentParseResult(
            intent=None,
            parameters={},
            missing_parameters=[],
            contains_rfc_name=contains_rfc_name,
            contains_odata_override=contains_odata_override,
        )

    capability_id = payload.get("capabilityId")
    if not capability_id or capability_id not in catalog.capability_ids:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])

    descriptor = catalog.find(str(capability_id))
    if descriptor is None:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])

    raw_parameters = payload.get("parameters") or {}
    parameters = _extract_parameters(raw_parameters, descriptor)

    missing = [inp.name for inp in descriptor.inputs if inp.required and inp.name not in parameters]
    clarification = _clarification_for(str(capability_id), missing)

    return IntentParseResult(
        intent=None,
        capability_id=str(capability_id),
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
    )


def _extract_parameters(raw_parameters: object, descriptor: CapabilityDescriptor) -> dict[str, str]:
    if not isinstance(raw_parameters, dict):
        return {}
    allowed = {inp.name for inp in descriptor.inputs}
    parameters: dict[str, str] = {}
    for key, value in raw_parameters.items():
        normalized = _parameter_key(str(key))
        if normalized and normalized in allowed and value is not None and str(value).strip():
            parameters[normalized] = str(value).strip()
    return parameters


def _clarification_for(capability_id: str, missing: list[str]) -> str | None:
    if capability_id == "MM.Inventory.GetAvailability":
        if missing == ["material"]:
            return "请提供要查询的物料编号。"
        if missing == ["plant"]:
            return "请提供要查询的工厂。"
        if missing:
            return "请提供要查询的物料编号和工厂。"
        return None
    if missing:
        return f"请提供以下参数：{', '.join(missing)}。"
    return None


_ALIASES = {
    # inventory
    "material": "material",
    "materialNumber": "material",
    "materialCode": "material",
    "matnr": "material",
    "plant": "plant",
    "plantCode": "plant",
    "werks": "plant",
    "unit": "unit",
    "uom": "unit",
    "unitOfMeasure": "unit",
    # purchase order
    "poNumber": "poNumber",
    "purchaseOrderNumber": "poNumber",
    "ebeln": "poNumber",
    "vendor": "vendor",
    "supplier": "vendor",
    "lifnr": "vendor",
}


def _parameter_key(key: str) -> str | None:
    return _ALIASES.get(key.strip())
```

^- [x] **Step 4: 运行新测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_llm_intent.py::test_parse_with_llm_selects_purchase_order agent/tests/test_llm_intent.py::test_parse_with_llm_rejects_capability_not_in_closed_set agent/tests/test_llm_intent.py::test_parse_with_llm_normalizes_po_aliases agent/tests/test_llm_intent.py::test_parse_with_llm_drops_unregistered_parameter_for_po agent/tests/test_llm_intent.py::test_hybrid_falls_back_to_parse_intent_for_po agent/tests/test_llm_intent.py::test_hybrid_returns_llm_result_when_capability_id_set agent/tests/test_llm_intent.py::test_llm_prompt_injects_purchase_order_capability -v`
Expected: PASS -- 全部 7 个新测试通过

^- [x] **Step 5: 更新现有库存测试以适配新签名**

现有测试需做以下改动（LLM 路径现在填 `capability_id` 不填 `intent`，且 `parse_with_llm` / `parse_with_hybrid` 需传 `catalog`）：

**a) `test_parse_with_llm_happy_path_returns_inventory_parse_result`** -- 加 catalog 参数 + 断言改 capability_id：

将整个测试函数替换为：

```python
def test_parse_with_llm_happy_path_returns_inventory_parse_result():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA1", "plant": "1000", "unit": "EA"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("帮我查一下 DEMOA1 在 1000 的库存", client, catalog)

    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.intent is None
    assert result.parameters == {"material": "DEMOA1", "plant": "1000", "unit": "EA"}
    assert result.missing_parameters == []
    assert client.calls
```

**b) `test_parse_with_llm_missing_plant_returns_clarification`** -- 加 catalog + 断言改 capability_id：

将整个测试函数替换为：

```python
def test_parse_with_llm_missing_plant_returns_clarification():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA1"},
        "missingParameters": ["plant"],
        "clarification": "请提供要查询的工厂。",
    })

    result = parse_with_llm("查一下 DEMOA1 的可用量", client, catalog)

    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.intent is None
    assert result.parameters == {"material": "DEMOA1"}
    assert result.missing_parameters == ["plant"]
    assert result.clarification == "请提供要查询的工厂。"
```

**c) `test_parse_with_llm_accepts_semantic_parameter_aliases_from_real_model`** -- 加 catalog + 断言改：

将整个测试函数替换为：

```python
def test_parse_with_llm_accepts_semantic_parameter_aliases_from_real_model():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"materialNumber": "DEMOA1", "plantCode": "1000"},
        "missingParameters": [],
        "clarification": None,
    })

    result = parse_with_llm("请帮我查一下 DEMOA1 在 1000 的可用库存", client, catalog)

    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.missing_parameters == []
```

**d) `test_parse_with_llm_rejects_rfc_name_output`** -- 加 catalog + intent 断言改 None：

将整个测试函数替换为：

```python
def test_parse_with_llm_rejects_rfc_name_output():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "rfcName": "BAPI_MATERIAL_AVAILABILITY",
        "parameters": {"material": "DEMOA1", "plant": "1000"},
    })

    result = parse_with_llm("查库存", client, catalog)

    assert result.contains_rfc_name is True
    assert result.intent is None
```

**e) `test_parse_with_llm_unknown_capability_is_unsupported`** -- 加 catalog：

将整个测试函数替换为：

```python
def test_parse_with_llm_unknown_capability_is_unsupported():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Purchase.CreateRequisition",
        "parameters": {"material": "DEMOA1", "plant": "1000"},
    })

    result = parse_with_llm("查库存", client, catalog)

    assert result.intent is None
    assert result.capability_id is None
    assert result.parameters == {}
```

**f) `test_hybrid_falls_back_to_rule_parser_when_llm_unavailable`** -- 加 catalog 参数：

将 `parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client)` 改为 `parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=load_intent_catalog())`

**g) `test_hybrid_falls_back_to_rule_parser_when_llm_json_is_malformed`** -- 同上加 catalog：

将 `parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client)` 改为 `parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=load_intent_catalog())`

**h) `test_hybrid_falls_back_to_rule_parser_when_llm_outputs_rfc_name`** -- 加 catalog + payload 加 capabilityId：

将整个测试函数替换为：

```python
def test_hybrid_falls_back_to_rule_parser_when_llm_outputs_rfc_name():
    catalog = load_intent_catalog()
    client = FakeLlmClient({
        "capabilityId": "MM.Inventory.GetAvailability",
        "rfcName": "BAPI_MATERIAL_AVAILABILITY",
        "parameters": {"material": "WRONG", "plant": "9999"},
    })

    result = parse_with_hybrid("DEMOA1 在 1000 还有多少可用库存？", client, catalog=catalog)

    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.contains_rfc_name is False
```

**i) `test_llm_mode_unavailable_returns_structured_unsupported_result`** -- 无需改动（`build_intent_adapter("llm")` catalog 默认 None 内部加载，断言不变）

**j) OData override 测试组**（`test_parse_with_llm_payload_with_odata_url_sets_override_flag` 等 4 个）-- 加 catalog 参数：

每个 `parse_with_llm("查库存", client)` 改为 `parse_with_llm("查库存", client, load_intent_catalog())`，并从 payload 中移除 `"intent"` 键（保留 `"capabilityId": "MM.Inventory.GetAvailability"`）。

`test_hybrid_falls_back_to_rule_parser_when_llm_outputs_odata_override` 中的 `parse_with_hybrid("...", client)` 改为 `parse_with_hybrid("...", client, catalog=load_intent_catalog())`，payload 加 `"capabilityId": "MM.Inventory.GetAvailability"` 并移除 `"intent"` 键。

^- [x] **Step 6: 运行全部 test_llm_intent.py 确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_llm_intent.py -v`
Expected: PASS -- 全部测试通过（新 7 个 + 更新后的现有测试 + Task 2 的 2 个 select_capability 测试）

^- [x] **Step 7: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat: refactor llm_intent to dynamic capability closed-set with PO support"
```

archived-with: 2026-07-09-flexible-intent-recognition
---

### Task 4: CLI 入口统一（cli.py）

**Files:**
- Modify: `agent/sap_nexus_agent/cli.py` (全文件小改)
- Test: 无新增测试（CLI 手动验证在 Task 6）

**Interfaces:**
- Consumes: `load_intent_catalog` from Task 1; `build_intent_adapter(mode, catalog)` from Task 3; `run_query` from `orchestrator.py` (已存在)
- Produces: CLI 入口使用 `run_query` + catalog 注入

^- [x] **Step 1: 修改 cli.py**

将 `agent/sap_nexus_agent/cli.py` 全文件替换为：

```python
from __future__ import annotations

import argparse
import json

from sap_nexus_agent.gateway_client import GatewayClient
from sap_nexus_agent.llm_intent import build_intent_adapter
from sap_nexus_agent.orchestrator import run_query
from sap_nexus_agent.registry_loader import load_intent_catalog
from sap_nexus_agent.workbench_output import outcome_to_workbench_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SAP Nexus Agent read-only SAP query")
    parser.add_argument("query", help="Chinese read-only SAP query (inventory, purchase order, etc.)")
    parser.add_argument("--gateway-url", default="http://localhost:8080")
    parser.add_argument("--intent-mode", choices=("hybrid", "llm", "rule"), default="hybrid")
    parser.add_argument("--json", action="store_true", help="Print structured JSON for Workbench runtime adapter")
    args = parser.parse_args(argv)

    catalog = load_intent_catalog()
    intent_adapter = build_intent_adapter(args.intent_mode, catalog)
    outcome = run_query(
        args.query,
        GatewayClient(args.gateway_url),
        intent_adapter=intent_adapter,
    )
    if args.json:
        print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
    else:
        print(outcome.response_text or outcome.message or "未生成响应。")
    return 0 if outcome.status in {"success", "clarification"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

^- [x] **Step 2: 验证 CLI 可导入不报错**

Run: `PYTHONPATH=agent .venv/bin/python -c "from sap_nexus_agent.cli import main; print('OK')"`
Expected: 输出 `OK`

^- [x] **Step 3: 确认 workbench_output.py 不受影响**

Run: `PYTHONPATH=agent .venv/bin/python -c "from sap_nexus_agent.workbench_output import run_workbench_query; print('OK')"`
Expected: 输出 `OK`（`build_intent_adapter(intent_mode)` 无 catalog 参数仍可用，因 catalog 可选）

^- [x] **Step 4: 提交**

```bash
git add agent/sap_nexus_agent/cli.py
git commit -m "feat: switch CLI entry to run_query with catalog-injected intent adapter"
```

archived-with: 2026-07-09-flexible-intent-recognition
---

### Task 5: 编排器集成测试（test_orchestrator.py 补 PO LLM 用例）

**Files:**
- Modify: `agent/tests/test_orchestrator.py` (新增 1 个集成用例)
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `run_query` from `orchestrator.py`; `parse_with_hybrid` from Task 3; `load_intent_catalog` from Task 1; `FakePoGatewayClient` (已存在于测试文件中)

^- [x] **Step 1: 编写失败测试**

在 `agent/tests/test_orchestrator.py` 顶部 import 区添加：

```python
from sap_nexus_agent.llm_intent import parse_with_hybrid
from sap_nexus_agent.registry_loader import load_intent_catalog
```

在文件末尾（`test_run_query_inventory_via_run_inventory_query_backward_compat` 之后）添加：

```python
# ---------------------------------------------------------------------------
# run_query via LLM intent adapter (flexible intent recognition)
# ---------------------------------------------------------------------------


class _FakePoLlmClient:
    """Fake LLM client returning a PO capability selection."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def chat_json(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages})
        return self._payload


def test_run_query_via_llm_adapter_selects_purchase_order():
    """run_query 经 LLM adapter（catalog + fake client）选 PO 全链路。"""
    catalog = load_intent_catalog()
    fake_client = _FakePoLlmClient({
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameters": {"poNumber": "DEMOPO1"},
        "missingParameters": [],
        "clarification": None,
    })
    adapter = lambda text: parse_with_hybrid(text, client=fake_client, catalog=catalog)

    gateway = FakePoGatewayClient()
    outcome = run_query("查询采购订单DEMOPO1", gateway, intent_adapter=adapter)

    assert outcome.status == "success"
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.PurchaseOrder.GetList"
    assert outcome.call_plan.parameters == {"poNumber": "DEMOPO1"}
    assert gateway.validate_calls == [("MM.PurchaseOrder.GetList", {"poNumber": "DEMOPO1"})]
    assert gateway.execute_calls == [("MM.PurchaseOrder.GetList", {"poNumber": "DEMOPO1"})]
    assert outcome.facts is not None
    assert len(outcome.facts) == 2
    assert "4500000001" in outcome.response_text
```

^- [x] **Step 2: 运行新测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_run_query_via_llm_adapter_selects_purchase_order -v`
Expected: PASS

^- [x] **Step 3: 运行全部 test_orchestrator.py 确认不破坏**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_orchestrator.py -v`
Expected: PASS -- 全部测试通过（新 1 个 + 现有全部）

^- [x] **Step 4: 提交**

```bash
git add agent/tests/test_orchestrator.py
git commit -m "test: add run_query via LLM adapter PO integration test"
```

archived-with: 2026-07-09-flexible-intent-recognition
---

### Task 6: 全量验证与端到端

**Files:**
- 无文件修改（验证任务）

^- [x] **Step 1: 运行全部 pytest**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q`
Expected: 全部通过，0 failures

^- [x] **Step 2: 运行 PO eval**

Run: `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/purchase_order_cases.json`
Expected: 全部 eval case 通过

^- [x] **Step 3: 运行 registry contract 校验**

Run: `.venv/bin/python scripts/validate_registry_contract.py registry/capabilities.yaml`
Expected: 通过（registry schema 未改，不应受影响）

^- [x] **Step 4: 运行 openspec 校验**

Run: `openspec validate --all --strict`
Expected: 通过

^- [x] **Step 5: 运行 verify-agent-callplan-evidence 脚本**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: 通过

^- [x] **Step 6: 端到端 CLI 直测（需 gateway 运行）**

Run: `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli "查询采购订单DEMOPO1" --gateway-url http://localhost:8080`
Expected: 返回采购订单列表（非 `当前仅支持已注册的只读能力...`）

> 注：此步骤需要 SAP gateway 运行。若 gateway 不可用，确认 CLI 不再返回 `unsupported` 错误即可（应返回 gateway 连接错误而非意图识别错误）。

^- [x] **Step 7: 确认 git 状态干净**

Run: `git status --short`
Expected: 无未提交改动（所有改动已在 Task 1-5 中提交）

archived-with: 2026-07-09-flexible-intent-recognition
---

## Self-Review

### 1. Spec coverage（设计文档需求 -> 计划任务映射）

| 设计文档需求 | 计划任务 | 状态 |
|---|---|---|
| 3.1 registry_loader.py 新增 | Task 1 | ✅ |
| 3.2 intent.py 加 capability_id | Task 2 Step 3 | ✅ |
| 3.3 capability_selector.py 优先 capability_id | Task 2 Step 4 | ✅ |
| 3.4 _messages 动态注入 | Task 3 Step 3 | ✅ |
| 3.4 _payload_to_parse_result 闭集校验 | Task 3 Step 3 | ✅ |
| 3.4 _extract_parameters 别名归一 + per-capability 白名单 | Task 3 Step 3 | ✅ |
| 3.4 别名表扩展含 PO | Task 3 Step 3 (_ALIASES) | ✅ |
| 3.4 fallback 改 parse_intent | Task 3 Step 3 | ✅ |
| 3.4 build_intent_adapter(mode, catalog) | Task 3 Step 3 | ✅ |
| 3.4 _requires_safe_fallback 修复 | Task 3 Step 3 | ✅ (关键修复) |
| 3.5 cli.py run_query + catalog | Task 4 | ✅ |
| 3.5 help 文案去 inventory-only | Task 4 Step 1 | ✅ |
| 5 测试: test_registry_loader.py | Task 1 | ✅ |
| 5 测试: test_llm_intent.py 更新 | Task 3 Step 5 | ✅ |
| 5 测试: test_orchestrator.py 更新 | Task 5 | ✅ |
| 5 测试: test_intent.py 不破坏 | Task 2 Step 6 | ✅ |
| 6 验证全量 | Task 6 | ✅ |

### 2. Placeholder scan

无 TBD/TODO/placeholder。每个步骤含完整代码或精确修改指令。

### 3. Type consistency

- `IntentCatalog` / `CapabilityDescriptor` / `InputDescriptor` -- Task 1 定义，Task 3 使用，签名一致 ✅
- `load_intent_catalog(repo_root=None) -> IntentCatalog` -- Task 1 定义，Task 3/4/5 调用 ✅
- `IntentParseResult.capability_id: str | None = None` -- Task 2 定义，Task 3 填充，Task 2 select_capability 读取 ✅
- `parse_with_llm(text, client, catalog)` -- Task 3 定义，Task 3/5 调用 ✅
- `parse_with_hybrid(text, client=None, *, catalog=None)` -- Task 3 定义，Task 3/5 调用 ✅
- `build_intent_adapter(mode, catalog=None)` -- Task 3 定义，Task 4 调用，workbench_output.py 调用 ✅
- `_extract_parameters(raw_parameters, descriptor)` -- Task 3 定义并使用 ✅
- `_clarification_for(capability_id, missing)` -- Task 3 定义并使用 ✅


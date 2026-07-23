---
archived-with: 2026-07-09-llm-grounded-narration
status: final
---
# LLM-Grounded Flexible Narration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 narrator 从纯模板拼接重构为 LLM grounded 柔性叙事 + 模板 fallback，inventory 和 PO 叙事都走 LLM 主路径，LLM 不可用时降级到既有模板。

**Architecture:** narrator 内部按 capability businessObject 派生叙事指引（`narration_guidance`），构造 system 约束 + guidance + fact 字段的 prompt，调 `chat_text` 生成自然语言，经 `redact_sensitive` 过滤后返回；`LlmUnavailable` 时 fallback 到提取的模板函数。orchestrator 仅显式传 `capability_id`，改动最小。

**Tech Stack:** Python 3.11+, OpenAI SDK（DeepSeek 网关），pytest，registry_loader IntentCatalog

## Global Constraints

- READ 路径不得调用 `BAPI_TRANSACTION_COMMIT`/`BAPI_TRANSACTION_ROLLBACK`（本变更不涉及）
- narrator 不得编造记录/数值/字段/凭据/SAP 表名/BAPI/RFC 名 -- 由 `_SYSTEM_CONSTRAINT` prompt 约束 + fallback 模板兜底
- 任何 LLM 异常必须降级模板，不让 agent 崩溃
- LLM 输出经 `redact_sensitive` 过滤敏感信息
- 空列表 PO 直接返回「无匹配记录。」不调 LLM
- 不改 registry schema / OData service / 前端 / 意图识别 / fact builder / LLM 认证机制
- 复用 `registry_loader.load_intent_catalog()` 派生指引，不重复读 registry
- commit message 结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`

---

## File Structure

| 文件 | 职责 | 改动类型 |
|---|---|---|
| `agent/sap_nexus_agent/llm_client.py` | 加 `chat_text` 方法，返回纯文本 content | Modify |
| `agent/sap_nexus_agent/narrator.py` | LLM 主路径 + 指引派生 + 模板 fallback 提取 | Modify (重构) |
| `agent/sap_nexus_agent/orchestrator.py` | 显式传 `capability_id`（最小） | Modify |
| `agent/tests/conftest.py` | autouse fixture 隔离真实 LLM（防 `.env` 污染单元测试） | Create |
| `agent/tests/test_reasoning_narrator.py` | LLM/fallback/防幻觉/空/redact 用例 | Modify |
| `agent/tests/test_orchestrator.py` | narrator LLM 路径集成（注入 fake client） | Modify |

**关键设计决策：**
- `_template_inventory` / `_template_po` 提取自既有拼接逻辑，保持输出与原模板完全一致（fallback 确定性）
- narrator 测试用本地 `FakeNarratorLlmClient`（实现 `chat_text`），不依赖网络
- `conftest.py` autouse fixture 设置空 `LLM_API_KEY`/`LLM_BASE_URL`，使 `OpenAiCompatibleLlmClient()` 构造时抛 `LlmUnavailable`，保护所有未注入 fake 的测试走 fallback 模板路径（确定性）
- orchestrator 不加 `client` 参数（遵循「改动最小」）；orchestrator LLM 集成测试通过 monkeypatch `narrator.OpenAiCompatibleLlmClient` 注入 fake

---

### Task 1: `OpenAiCompatibleLlmClient.chat_text`

为 LLM client 加纯文本对话方法，复用 chat_json 的请求/重试/超时模式但返回 `choices[0].message.content` 字符串。

**Files:**
- Modify: `agent/sap_nexus_agent/llm_client.py`（在 `chat_json` 方法后追加 `chat_text`）
- Test: `agent/tests/test_reasoning_narrator.py`（通过 narrator 间接验证；llm_client 本身依赖网络不做单测）

**Interfaces:**
- Produces: `OpenAiCompatibleLlmClient.chat_text(messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 400) -> str`；不可用时抛 `LlmUnavailable`

^- [x] **Step 1: 在 `chat_json` 方法后追加 `chat_text` 方法**

在 `agent/sap_nexus_agent/llm_client.py` 的 `chat_json` 方法之后（第 108 行 `raise LlmUnavailable("LLM JSON call failed") from exc` 之后）追加：

```python
    def chat_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 400) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.settings.timeout_intent,
            )
            content = response.choices[0].message.content
            if not content:
                raise LlmUnavailable("LLM returned empty text content")
            return content
        except (self._api_connection_error, TimeoutError) as exc:
            raise LlmUnavailable("LLM connection failed") from exc
        except self._api_status_error as exc:
            raise LlmUnavailable(f"LLM API status error: {getattr(exc, 'status_code', 'unknown')}") from exc
        except Exception as exc:
            raise LlmUnavailable("LLM text call failed") from exc
```

注意：不设 `response_format`（纯文本，非 JSON）；错误处理与 `chat_json` 一致。

^- [x] **Step 2: 确认现有 chat_json 测试不破坏**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_llm_intent.py -q`
Expected: PASS（所有现有意图测试通过，chat_json 未改动）

^- [x] **Step 3: 确认全量测试仍通过（chat_text 尚未被调用）**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q`
Expected: PASS（20 narrator + 全部 orchestrator/llm_intent 测试通过）

^- [x] **Step 4: Commit**

```bash
git add agent/sap_nexus_agent/llm_client.py
git commit -m "feat(narrator): add chat_text to OpenAiCompatibleLlmClient for text narration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `conftest.py` 隔离真实 LLM

创建 autouse fixture，使所有单元测试中 `OpenAiCompatibleLlmClient()` 构造时抛 `LlmUnavailable`，走 fallback 模板路径。这防止本地 `.env`（含真实 LLM 凭据）污染测试导致非确定性。

**原理：** `load_dotenv()` 默认 `override=False`，不覆盖已存在的环境变量。fixture 用 `monkeypatch.setenv("LLM_API_KEY", "")` 设置空值后，`load_dotenv` 不会覆盖，`settings.available` 为 `False`，`OpenAiCompatibleLlmClient()` 构造时抛 `LlmUnavailable`。

**Files:**
- Create: `agent/tests/conftest.py`
- Test: 运行全量测试确认现有断言精确模板的测试仍通过

**Interfaces:**
- Produces: autouse fixture `_isolate_llm_env`，对 `agent/tests/` 下所有测试生效

^- [x] **Step 1: 创建 conftest.py**

创建 `agent/tests/conftest.py`：

```python
"""Shared test fixtures for sap_nexus_agent unit tests.

Prevents unit tests from hitting the real LLM gateway by ensuring
LLM_API_KEY / LLM_BASE_URL are empty, so OpenAiCompatibleLlmClient()
raises LlmUnavailable and narrator/orchestrator fall back to templates.

Tests that need the LLM path inject a fake client explicitly and do not
rely on OpenAiCompatibleLlmClient() construction.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
```

^- [x] **Step 2: 运行全量测试确认现有模板断言不被破坏**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q`
Expected: PASS（所有测试通过；断言精确模板字符串的 `test_narrate_fact_uses_only_fact_fields`、`test_gateway_shaped_success_uses_call_plan_parameters_for_fact_context`、`test_run_query_inventory_regression` 等因 fallback 路径仍输出精确模板而通过）

^- [x] **Step 3: Commit**

```bash
git add agent/tests/conftest.py
git commit -m "test: add conftest fixture to isolate unit tests from real LLM

Prevents .env credentials from making narrator tests non-deterministic;
all non-fake-client tests now deterministically fall back to templates.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: narrator 内部辅助 — 模板提取 + guidance 派生 + prompt 构建

提取既有模板拼接为 `_template_inventory`/`_template_po`；新增 `narration_guidance`、三个 guidance 常量、`_SYSTEM_CONSTRAINT`、`_build_messages`/`_build_po_messages`。本任务只加内部辅助函数和常量，不改 `narrate_fact`/`narrate_purchase_order_facts` 签名（下两个 task 改）。

**Files:**
- Modify: `agent/sap_nexus_agent/narrator.py`（加 import、常量、辅助函数）
- Test: `agent/tests/test_reasoning_narrator.py`（加 guidance/build_messages 单测）

**Interfaces:**
- Consumes: `load_intent_catalog()` from `registry_loader`（已存在）；`ReasoningFact`（已存在）
- Produces:
  - `_template_inventory(fact: ReasoningFact) -> str`
  - `_template_po(facts: list[ReasoningFact], total_count: int | None) -> str`
  - `narration_guidance(capability_id: str) -> str`
  - `_build_messages(fact: ReasoningFact, capability_id: str) -> list[dict[str, str]]`
  - `_build_po_messages(facts: list[ReasoningFact], total_count: int | None) -> list[dict[str, str]]`

^- [x] **Step 1: 写 guidance 派生的失败测试**

在 `agent/tests/test_reasoning_narrator.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Flexible narration guidance derivation (LLM-grounded narration)
# ---------------------------------------------------------------------------

from sap_nexus_agent.narrator import narration_guidance


def test_narration_guidance_inventory():
    guidance = narration_guidance("MM.Inventory.GetAvailability")
    assert "库存" in guidance
    assert "可用库存" in guidance


def test_narration_guidance_purchase_order():
    guidance = narration_guidance("MM.PurchaseOrder.GetList")
    assert "采购订单" in guidance


def test_narration_guidance_unknown_capability_returns_generic():
    guidance = narration_guidance("MM.NonExistent.Capability")
    assert "事实" in guidance or "字段" in guidance
```

^- [x] **Step 2: 运行测试确认失败**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py::test_narration_guidance_inventory -v`
Expected: FAIL with `ImportError: cannot import name 'narration_guidance'`

^- [x] **Step 3: 在 narrator.py 加 import 和常量**

在 `agent/sap_nexus_agent/narrator.py` 顶部 import 区追加（在现有 `from sap_nexus_agent.reasoning_fact import ReasoningFact` 之后）：

```python
from sap_nexus_agent.llm_client import LlmUnavailable, OpenAiCompatibleLlmClient
from sap_nexus_agent.registry_loader import load_intent_catalog
```

在 `class NarrativeGuardError(ValueError): pass` 之后追加模块常量：

```python
_SYSTEM_CONSTRAINT = (
    "你是一个 SAP 业务结论叙事器。只能使用下方提供的事实字段及其值生成中文叙事，"
    "不得编造任何记录、数值或字段，不得猜测，不得添加未提供的信息，"
    "不得输出 SAP 表名、BAPI/RFC 名或凭据。"
)

_INVENTORY_GUIDANCE = (
    "用给定物料的可用库存事实生成一句中文结论，说明物料在工厂的可用库存量与单位。"
)

_PO_GUIDANCE = (
    "用给定的采购订单条目事实生成中文归纳，列出关键订单（采购订单号、供应商、物料、工厂、数量、单位），"
    "多条时归纳总结。"
)

_GENERIC_GUIDANCE = "用给定事实字段的值生成自然语言中文陈述，只陈述字段中存在的数据。"
```

^- [x] **Step 4: 实现 `narration_guidance`**

在常量之后追加：

```python
def narration_guidance(capability_id: str) -> str:
    """按 businessObject 派生叙事指引；未知能力用通用 fact-based 指引。"""
    catalog = load_intent_catalog()
    descriptor = catalog.find(capability_id)
    business_object = descriptor.business_object if descriptor else ""
    if business_object == "InventoryStock":
        return _INVENTORY_GUIDANCE
    if business_object == "PurchaseOrder":
        return _PO_GUIDANCE
    return _GENERIC_GUIDANCE
```

^- [x] **Step 5: 运行 guidance 测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py::test_narration_guidance_inventory agent/tests/test_reasoning_narrator.py::test_narration_guidance_purchase_order agent/tests/test_reasoning_narrator.py::test_narration_guidance_unknown_capability_returns_generic -v`
Expected: PASS（3 个 guidance 测试通过）

^- [x] **Step 6: 写 `_build_messages` / `_build_po_messages` 的失败测试**

在 `agent/tests/test_reasoning_narrator.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Prompt message construction
# ---------------------------------------------------------------------------

from sap_nexus_agent.narrator import _build_messages, _build_po_messages


def test_build_messages_inventory_contains_system_constraint_and_fact_fields():
    fact = build_availability_fact("agent-1", successful_execution())
    messages = _build_messages(fact, "MM.Inventory.GetAvailability")

    assert messages[0]["role"] == "system"
    assert "不得编造" in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "库存" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "DEMOA1" in messages[2]["content"]
    assert "1000" in messages[2]["content"]
    assert "12" in messages[2]["content"]
    assert "EA" in messages[2]["content"]


def test_build_po_messages_contains_constraint_and_evidence():
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    messages = _build_po_messages(facts, total_count=1)

    assert messages[0]["role"] == "system"
    assert "不得编造" in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "采购订单" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "4500000001" in messages[2]["content"]
    assert "DEMOV1" in messages[2]["content"]
```

^- [x] **Step 7: 运行确认失败**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py::test_build_messages_inventory_contains_system_constraint_and_fact_fields -v`
Expected: FAIL with `ImportError: cannot import name '_build_messages'`

^- [x] **Step 8: 实现 `_build_messages` 和 `_build_po_messages`**

在 `narration_guidance` 之后追加：

```python
def _build_messages(fact: ReasoningFact, capability_id: str) -> list[dict[str, str]]:
    guidance = narration_guidance(capability_id)
    user_content = (
        f"物料: {fact.material}\n"
        f"工厂: {fact.plant}\n"
        f"可用库存: {fact.value}\n"
        f"单位: {fact.unit}\n"
    )
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]


def _build_po_messages(facts: list[ReasoningFact], total_count: int | None) -> list[dict[str, str]]:
    guidance = narration_guidance("MM.PurchaseOrder.GetList")
    lines: list[str] = []
    for fact in facts[:_PO_LIMIT]:
        ev = fact.evidence[0] if fact.evidence else {}
        lines.append(
            f"采购订单: {ev.get('purchaseOrder', '')}，"
            f"供应商: {ev.get('supplier', '')}，"
            f"物料: {ev.get('material', '')}，"
            f"工厂: {ev.get('plant', '')}，"
            f"数量: {ev.get('orderQuantity', '')} {ev.get('purchaseOrderUnit', '')}"
        )
    user_content = "\n".join(lines)
    if total_count is not None:
        user_content += f"\n总记录数: {total_count}"
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]
```

^- [x] **Step 9: 运行 build_messages 测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py::test_build_messages_inventory_contains_system_constraint_and_fact_fields agent/tests/test_reasoning_narrator.py::test_build_po_messages_contains_constraint_and_evidence -v`
Expected: PASS

^- [x] **Step 10: 提取 `_template_inventory` 和 `_template_po`（不改 narrate_fact 签名）**

在 `_build_po_messages` 之后追加（提取既有拼接逻辑，输出与原模板完全一致）：

```python
def _template_inventory(fact: ReasoningFact) -> str:
    """Deterministic template fallback for inventory narration."""
    return f"物料 {fact.material} 在工厂 {fact.plant} 的可用库存为 {fact.value} {fact.unit}。"


def _template_po(facts: list[ReasoningFact], total_count: int | None) -> str:
    """Deterministic template fallback for PO narration; raises guard on missing evidence."""
    lines: list[str] = []
    for fact in facts[:_PO_LIMIT]:
        evidence = fact.evidence[0] if fact.evidence else {}
        missing = [
            field
            for field in _PO_REQUIRED_EVIDENCE
            if field not in evidence or evidence[field] is None
        ]
        if missing:
            raise NarrativeGuardError(
                f"ReasoningFact missing evidence fields for PO narration: {', '.join(missing)}"
            )
        lines.append(
            f"采购订单 {evidence['purchaseOrder']}："
            f"供应商 {evidence['supplier']}，"
            f"物料 {evidence['material']}，"
            f"工厂 {evidence['plant']}，"
            f"数量 {evidence['orderQuantity']} {evidence['purchaseOrderUnit']}。"
        )
    truncated = len(facts) > _PO_LIMIT or (
        total_count is not None and total_count > _PO_LIMIT
    )
    if truncated:
        lines.append("（仅返回前 50 条。）")
    return "\n".join(lines)
```

^- [x] **Step 11: 运行全量 narrator 测试确认不破坏现有行为**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -q`
Expected: PASS（现有 20 + 新 5 个测试通过；`narrate_fact`/`narrate_purchase_order_facts` 仍用原逻辑，模板提取尚未接入）

^- [x] **Step 12: Commit**

```bash
git add agent/sap_nexus_agent/narrator.py agent/tests/test_reasoning_narrator.py
git commit -m "feat(narrator): add guidance derivation, prompt builders, template extraction

- narration_guidance(capability_id) derives guidance by businessObject
- _SYSTEM_CONSTRAINT + _INVENTORY/_PO/_GENERIC_GUIDANCE constants
- _build_messages/_build_po_messages construct system+guidance+user prompt
- _template_inventory/_template_po extracted from existing concatenation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `narrate_fact` LLM 主路径 + fallback

重构 `narrate_fact`：签名加 `capability_id`/`client` 参数；先检查 fact 字段不足（抛 guard，不调 LLM）；LLM 主路径 `chat_text` + `redact_sensitive`；`LlmUnavailable` fallback `_template_inventory`。

**Files:**
- Modify: `agent/sap_nexus_agent/narrator.py`（重构 `narrate_fact`）
- Test: `agent/tests/test_reasoning_narrator.py`（加 LLM/fallback/guard 测试）

**Interfaces:**
- Consumes: `_build_messages`、`_template_inventory`（Task 3 产出）；`OpenAiCompatibleLlmClient`、`LlmUnavailable`（Task 1 + 既有）
- Produces: `narrate_fact(fact: ReasoningFact, *, capability_id: str = "MM.Inventory.GetAvailability", client=None) -> str`

^- [x] **Step 1: 写 LLM 主路径 + fake client 测试**

在 `agent/tests/test_reasoning_narrator.py` 的 `_build_po_messages` 测试之后追加：

```python
# ---------------------------------------------------------------------------
# narrate_fact LLM path + fallback (Task 4)
# ---------------------------------------------------------------------------


class FakeNarratorLlmClient:
    """Fake LLM client implementing chat_text for narrator tests."""

    def __init__(self, text="LLM 生成的库存叙事。", unavailable=False):
        self.text = text
        self.unavailable = unavailable
        self.calls = []

    def chat_text(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        if self.unavailable:
            raise LlmUnavailable("model gateway unavailable")
        return self.text


from sap_nexus_agent.llm_client import LlmUnavailable


def test_narrate_fact_llm_path_returns_generated_text():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(text="物料 DEMOA1 在 1000 当前可用 12 EA。")

    result = narrate_fact(fact, client=fake)

    assert result == "物料 DEMOA1 在 1000 当前可用 12 EA。"
    assert len(fake.calls) == 1
    assert fake.calls[0]["temperature"] == 0.0


def test_narrate_fact_llm_path_passes_capability_id_to_guidance():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient()

    narrate_fact(fact, capability_id="MM.Inventory.GetAvailability", client=fake)

    messages = fake.calls[0]["messages"]
    assert "库存" in messages[1]["content"]


def test_narrate_fact_llm_unavailable_falls_back_to_template():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(unavailable=True)

    result = narrate_fact(fact, client=fake)

    assert result == "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。"


def test_narrate_fact_no_client_falls_back_to_template():
    """Without injected client, OpenAiCompatibleLlmClient() raises LlmUnavailable (conftest)."""
    fact = build_availability_fact("agent-1", successful_execution())

    result = narrate_fact(fact)

    assert result == "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。"
```

^- [x] **Step 2: 运行确认 LLM 路径测试失败（narrate_fact 签名未改）**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py::test_narrate_fact_llm_path_returns_generated_text -v`
Expected: FAIL with `TypeError: narrate_fact() got an unexpected keyword argument 'client'`

^- [x] **Step 3: 重构 `narrate_fact`**

将 `agent/sap_nexus_agent/narrator.py` 中的 `narrate_fact` 函数替换为：

```python
def narrate_fact(
    fact: ReasoningFact,
    *,
    capability_id: str = "MM.Inventory.GetAvailability",
    client=None,
) -> str:
    missing = [
        name
        for name, value in {
            "material": fact.material,
            "plant": fact.plant,
            "value": fact.value,
            "unit": fact.unit,
        }.items()
        if value is None or value == ""
    ]
    if missing:
        raise NarrativeGuardError(f"ReasoningFact missing fields for narration: {', '.join(missing)}")
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_messages(fact, capability_id), temperature=0.0, max_tokens=200
        )
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_inventory(fact)
```

^- [x] **Step 4: 运行 narrate_fact 全部测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -k "narrate_fact" -v`
Expected: PASS（`test_narrate_fact_uses_only_fact_fields` 走 fallback 模板精确匹配；`test_narrator_rejects_missing_quantity` 抛 guard；4 个新 LLM/fallback 测试通过）

^- [x] **Step 5: 运行全量 narrator 测试确认不破坏**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -q`
Expected: PASS

^- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/narrator.py agent/tests/test_reasoning_narrator.py
git commit -m "feat(narrator): narrate_fact LLM main path with template fallback

- signature: narrate_fact(fact, *, capability_id, client=None)
- LLM path: chat_text(_build_messages) + redact_sensitive
- LlmUnavailable -> _template_inventory (deterministic fallback)
- fact fields missing -> NarrativeGuardError (unchanged behavior)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `narrate_purchase_order_facts` LLM 主路径 + fallback

重构 `narrate_purchase_order_facts`：签名加 `client` 参数；空列表直接返回「无匹配记录。」不调 LLM；非空 LLM 主路径 + `LlmUnavailable` fallback `_template_po`（含既有 guard）。

**Files:**
- Modify: `agent/sap_nexus_agent/narrator.py`（重构 `narrate_purchase_order_facts`）
- Test: `agent/tests/test_reasoning_narrator.py`（加 PO LLM/fallback/空列表测试）

**Interfaces:**
- Consumes: `_build_po_messages`、`_template_po`（Task 3 产出）
- Produces: `narrate_purchase_order_facts(facts: list[ReasoningFact], *, total_count: int | None = None, client=None) -> str`

^- [x] **Step 1: 写 PO LLM 主路径 + fake client 测试**

在 `agent/tests/test_reasoning_narrator.py` 的 narrate_fact 测试之后追加：

```python
# ---------------------------------------------------------------------------
# narrate_purchase_order_facts LLM path + fallback (Task 5)
# ---------------------------------------------------------------------------


def test_narrate_po_facts_llm_path_returns_generated_text():
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient(text="共 1 条采购订单，订单 4500000001 由供应商 DEMOV1 供应。")

    result = narrate_purchase_order_facts(facts, total_count=1, client=fake)

    assert "4500000001" in result
    assert "DEMOV1" in result
    assert len(fake.calls) == 1


def test_narrate_po_facts_llm_unavailable_falls_back_to_template():
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient(unavailable=True)

    result = narrate_purchase_order_facts(facts, total_count=1, client=fake)

    assert "4500000001" in result
    assert "DEMOV1" in result
    assert "采购订单 4500000001" in result


def test_narrate_po_facts_empty_list_does_not_call_llm():
    fake = FakeNarratorLlmClient()

    result = narrate_purchase_order_facts([], client=fake)

    assert result == "无匹配记录。"
    assert len(fake.calls) == 0


def test_narrate_po_facts_no_client_falls_back_to_template():
    """Without injected client, falls back to template (conftest isolates LLM)."""
    items = [_po_item(po="4500000001", supplier="DEMOV1")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))

    result = narrate_purchase_order_facts(facts)

    assert "采购订单 4500000001" in result
```

^- [x] **Step 2: 运行确认 PO LLM 路径测试失败**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py::test_narrate_po_facts_llm_path_returns_generated_text -v`
Expected: FAIL with `TypeError: narrate_purchase_order_facts() got an unexpected keyword argument 'client'`

^- [x] **Step 3: 重构 `narrate_purchase_order_facts`**

将 `agent/sap_nexus_agent/narrator.py` 中的 `narrate_purchase_order_facts` 函数替换为：

```python
def narrate_purchase_order_facts(
    facts: list[ReasoningFact],
    *,
    total_count: int | None = None,
    client=None,
) -> str:
    """Grounded narrative for a list of purchase-order-item facts.

    - Empty list -> "无匹配记录。" (not an error, no LLM call).
    - Non-empty: LLM main path (chat_text + redact_sensitive).
    - LlmUnavailable -> template concatenation (guard raises on missing evidence).
    - More than 50 items (or totalCount > 50) -> truncation notice (template path).
    """
    if not facts:
        return "无匹配记录。"

    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_po_messages(facts, total_count), temperature=0.0, max_tokens=400
        )
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_po(facts, total_count)
```

^- [x] **Step 4: 运行 PO narrate 全部测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -k "po" -v`
Expected: PASS（现有 PO 模板测试走 fallback；4 个新 LLM/fallback/空列表测试通过）

^- [x] **Step 5: 运行全量 narrator 测试确认不破坏**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -q`
Expected: PASS

^- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/narrator.py agent/tests/test_reasoning_narrator.py
git commit -m "feat(narrator): narrate_purchase_order_facts LLM main path with fallback

- signature adds client=None; empty list short-circuits (no LLM)
- LLM path: chat_text(_build_po_messages) + redact_sensitive
- LlmUnavailable -> _template_po (guard raises on missing evidence)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: orchestrator 接入 + 现有测试保护

orchestrator 显式传 `capability_id` 调 `narrate_fact`；确认现有 orchestrator 测试（含精确模板断言）因 conftest fallback 仍通过。

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`（`_finalize_inventory` 第 146 行、`_finalize_purchase_order` 第 178 行）
- Test: `agent/tests/test_orchestrator.py`（现有测试不改，确认通过）

**Interfaces:**
- Consumes: `narrate_fact(fact, capability_id=...)`、`narrate_purchase_order_facts(facts, total_count=...)`（Task 4/5 产出）

^- [x] **Step 1: 修改 `_finalize_inventory` 显式传 capability_id**

在 `agent/sap_nexus_agent/orchestrator.py` 第 146 行，将：

```python
        response_text = narrate_fact(fact)
```

改为：

```python
        response_text = narrate_fact(fact, capability_id="MM.Inventory.GetAvailability")
```

^- [x] **Step 2: 确认 `_finalize_purchase_order` 调用签名兼容**

`_finalize_purchase_order` 第 178 行 `narrate_purchase_order_facts(facts, total_count=total_count)` 不需改动（`client` 默认 `None`，走 fallback）。确认不改。

^- [x] **Step 3: 运行全量 orchestrator 测试确认现有断言通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_orchestrator.py -q`
Expected: PASS（`test_gateway_shaped_success_uses_call_plan_parameters_for_fact_context` 精确模板断言通过；`test_run_query_inventory_regression` 精确模板断言通过；`test_run_query_po_list_success` token 断言通过；`test_run_query_po_empty_list_success` 「无匹配记录」通过；`test_run_query_via_llm_adapter_selects_purchase_order` token 断言通过）

^- [x] **Step 4: 运行全量测试确认无回归**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q`
Expected: PASS

^- [x] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/orchestrator.py
git commit -m "feat(orchestrator): pass capability_id explicitly to narrate_fact

Minimal change: _finalize_inventory passes capability_id for guidance
derivation; _finalize_purchase_order unchanged (client defaults to None).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: orchestrator LLM 路径集成 + 防幻觉/redact 测试

通过 monkeypatch `narrator.OpenAiCompatibleLlmClient` 注入 fake client，测试 orchestrator 全链路 LLM 叙事；补 prompt 防幻觉约束断言 + redact 过滤断言。

**Files:**
- Modify: `agent/tests/test_orchestrator.py`（加 LLM 路径集成测试）
- Modify: `agent/tests/test_reasoning_narrator.py`（加 redact + 防幻觉断言）

**Interfaces:**
- Consumes: Task 4/5/6 产出的 narrator + orchestrator

^- [x] **Step 1: 写 orchestrator inventory LLM 路径集成测试**

在 `agent/tests/test_orchestrator.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# orchestrator LLM narration path (Task 7)
# ---------------------------------------------------------------------------

from unittest.mock import patch


class _FakeNarratorClient:
    """Fake LLM client for orchestrator-level narration tests."""

    def __init__(self, text="LLM 叙事结论。", unavailable=False):
        self.text = text
        self.unavailable = unavailable
        self.calls = []

    def chat_text(self, messages, *, temperature=0.0, max_tokens=400):
        self.calls.append({"messages": messages})
        if self.unavailable:
            from sap_nexus_agent.llm_client import LlmUnavailable
            raise LlmUnavailable("model gateway unavailable")
        return self.text


def test_run_query_inventory_llm_narration_full_path():
    """orchestrator -> narrate_fact LLM path with injected fake client."""
    gateway = FakeGatewayClient()
    fake_llm = _FakeNarratorClient(text="物料 DEMOA1 在工厂 1000 可用库存为 12 EA。")

    with patch("sap_nexus_agent.narrator.OpenAiCompatibleLlmClient", return_value=fake_llm):
        outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.response_text == "物料 DEMOA1 在工厂 1000 可用库存为 12 EA。"
    assert len(fake_llm.calls) == 1


def test_run_query_po_llm_narration_full_path():
    """orchestrator -> narrate_purchase_order_facts LLM path with injected fake client."""
    gateway = FakePoGatewayClient()
    fake_llm = _FakeNarratorClient(text="共 2 条采购订单记录。")

    with patch("sap_nexus_agent.narrator.OpenAiCompatibleLlmClient", return_value=fake_llm):
        outcome = run_query("查供应商 DEMOV1 的采购订单", gateway)

    assert outcome.status == "success"
    assert outcome.response_text == "共 2 条采购订单记录。"
    assert len(fake_llm.calls) == 1


def test_run_query_inventory_llm_unavailable_falls_back_to_template():
    """When LLM is unavailable, orchestrator falls back to template narration."""
    gateway = FakeGatewayClient()
    fake_llm = _FakeNarratorClient(unavailable=True)

    with patch("sap_nexus_agent.narrator.OpenAiCompatibleLlmClient", return_value=fake_llm):
        outcome = run_inventory_query("DEMOA1 在 1000 还有多少可用库存？", gateway)

    assert outcome.status == "success"
    assert outcome.response_text == "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。"
```

^- [x] **Step 2: 运行 orchestrator LLM 集成测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_orchestrator.py::test_run_query_inventory_llm_narration_full_path agent/tests/test_orchestrator.py::test_run_query_po_llm_narration_full_path agent/tests/test_orchestrator.py::test_run_query_inventory_llm_unavailable_falls_back_to_template -v`
Expected: PASS

^- [x] **Step 3: 写 redact 过滤 + 防幻觉约束测试**

在 `agent/tests/test_reasoning_narrator.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Anti-hallucination + redact on LLM output (Task 7)
# ---------------------------------------------------------------------------


def test_narrate_fact_llm_output_redacts_sensitive_info():
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient(text="库存为 12 EA。password=secret token=abc")

    result = narrate_fact(fact, client=fake)

    assert "secret" not in result
    assert "abc" not in result
    assert "12" in result


def test_narrate_po_facts_llm_output_redacts_sensitive_info():
    items = [_po_item(po="4500000001")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient(text="订单 4500000001。host=internal .env")

    result = narrate_purchase_order_facts(facts, client=fake)

    assert "internal" not in result
    assert ".env" not in result
    assert "4500000001" in result


def test_narrate_fact_prompt_system_constraint_forbids_fabrication():
    """System prompt must contain anti-fabrication constraint."""
    fact = build_availability_fact("agent-1", successful_execution())
    fake = FakeNarratorLlmClient()

    narrate_fact(fact, client=fake)

    system_content = fake.calls[0]["messages"][0]["content"]
    assert "不得编造" in system_content
    assert "不得猜测" in system_content
    assert "BAPI" in system_content or "RFC" in system_content


def test_narrate_po_facts_prompt_system_constraint_forbids_fabrication():
    items = [_po_item(po="4500000001")]
    facts = build_purchase_order_facts("agent-po-1", _po_execution_result(items))
    fake = FakeNarratorLlmClient()

    narrate_purchase_order_facts(facts, client=fake)

    system_content = fake.calls[0]["messages"][0]["content"]
    assert "不得编造" in system_content
```

^- [x] **Step 4: 运行防幻觉/redact 测试确认通过**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -k "redact or fabrication or constraint" -v`
Expected: PASS（4 个测试通过）

^- [x] **Step 5: 运行全量测试确认无回归**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q`
Expected: PASS（所有 narrator + orchestrator + llm_intent 测试通过）

^- [x] **Step 6: Commit**

```bash
git add agent/tests/test_orchestrator.py agent/tests/test_reasoning_narrator.py
git commit -m "test(narrator): orchestrator LLM integration + anti-hallucination + redact

- orchestrator LLM path via monkeypatch OpenAiCompatibleLlmClient
- fallback template still works when LLM unavailable
- prompt system constraint asserts 'no fabrication' / 'no guessing'
- LLM output redacts password/token/host/.env

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 验证与端到端

运行全部验证命令，确认 spec/eval/evidence 通过；端到端 CLI 直测库存 + PO 返回 LLM 自然语言结论。

**Files:**
- 无代码改动（仅运行验证命令）

^- [x] **Step 1: 全量 pytest**

Run: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q`
Expected: PASS（全部测试通过，无失败）

^- [x] **Step 2: eval 库存用例**

Run: `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`
Expected: 通过（eval 不依赖 narrator 输出格式，但确认无崩溃）

^- [x] **Step 3: eval PO 用例**

Run: `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/purchase_order_cases.json`
Expected: 通过

^- [x] **Step 4: openspec validate**

Run: `openspec validate --all --strict`
Expected: 通过（无 validation 错误）

^- [x] **Step 5: verify-agent-callplan-evidence**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: 通过

^- [x] **Step 6: 端到端 CLI 库存查询（需 LLM 配置）**

Run: `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli "查一下 DEMOA1 在 1000 的可用库存"`
Expected: 返回 LLM 生成的自然语言结论（非固定模板格式 `物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。`，而是 LLM 措辞变体；若 LLM 不可用则 fallback 到模板）

^- [x] **Step 7: 端到端 CLI PO 查询（需 LLM 配置）**

Run: `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli "查询采购订单 DEMOPO1"`
Expected: 返回 LLM 生成的自然语言结论（非逐条模板格式）

^- [x] **Step 8: git status 确认工作区干净**

Run: `git status --short`
Expected: 无未提交改动（所有改动已在 Task 1-7 commit）

^- [x] **Step 9: 最终 commit（如有遗漏的验证产物）**

```bash
git status --short
# 若有遗漏文件:
# git add <files>
# git commit -m "chore: verification artifacts" 
```

---

## Self-Review

**1. Spec coverage:**

| 设计要求 | 覆盖任务 |
|---|---|
| `chat_text` 方法（复用 chat_json 逻辑返回 text） | Task 1 |
| `narration_guidance(capability_id)` 按 businessObject 派生 | Task 3 |
| `_INVENTORY_GUIDANCE`/`_PO_GUIDANCE`/`_GENERIC_GUIDANCE` 常量 | Task 3 |
| `_SYSTEM_CONSTRAINT` 严格约束 | Task 3 |
| `_build_messages`/`_build_po_messages` | Task 3 |
| `narrate_fact` LLM 主路径 + fallback + guard | Task 4 |
| `narrate_purchase_order_facts` 空列表短路 + LLM + fallback | Task 5 |
| `_template_inventory`/`_template_po` 提取 | Task 3 |
| orchestrator 显式传 capability_id | Task 6 |
| redact_sensitive 过滤 LLM 输出 | Task 7 |
| 防幻觉 prompt 约束断言 | Task 7 |
| orchestrator LLM 集成测试 | Task 7 |
| 现有 fallback 不破坏 | Task 2 (conftest) + Task 6 |
| 全量 pytest + eval + openspec + evidence + 端到端 | Task 8 |

无遗漏。

**2. Placeholder scan:** 无 TBD/TODO/"implement later"；所有步骤含完整代码或确切命令。

**3. Type consistency:**
- `narrate_fact(fact, *, capability_id="MM.Inventory.GetAvailability", client=None)` — Task 4 定义，Task 6 调用一致
- `narrate_purchase_order_facts(facts, *, total_count=None, client=None)` — Task 5 定义，Task 6 确认不改
- `narration_guidance(capability_id: str) -> str` — Task 3 定义，Task 3/4 调用一致
- `_build_messages(fact, capability_id)` / `_build_po_messages(facts, total_count)` — Task 3 定义，Task 4/5 调用一致
- `_template_inventory(fact)` / `_template_po(facts, total_count)` — Task 3 定义，Task 4/5 调用一致
- `FakeNarratorLlmClient.chat_text(messages, *, temperature, max_tokens)` — Task 4 定义，Task 5/7 复用一致
- `FakeLlmClient`（test_llm_intent.py）不加 `chat_text`（intent 测试不需要）

类型与签名一致，无冲突。

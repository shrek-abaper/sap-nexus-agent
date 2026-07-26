---
change: sap-nexus-agent-llm-intent-enhancement
design-doc: docs/superpowers/specs/2026-07-26-sap-nexus-llm-intent-enhancement-design.md
base-ref: c63daea9719b8668127a9b3a4890c4f95d350e00
---

# LLM 意图识别增强 + 多值批量查询 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LLM 稳定解析跨轮指代（"这个物料" -> 上轮 material），支持任意参数多值查询的"确认后批量执行 + 聚合"流程，LLM 成为主意图识别器、rule 仅在连接失败时兜底。

**Architecture:** 复用现有 `ConversationContext.last_context`（不改 schema），在 `llm_intent._messages` 中注入结构化 last_context data 块（受 `_AUTHORITY_CONTRACT` 约束）；`parse_with_hybrid` 移除 rule 二次纠正、仅 `LlmUnavailable` 兜底；`IntentParseResult` 新增正交字段 `multi_parameters`，orchestrator 检测后展开笛卡尔积、返回 `awaiting_batch_confirm`，前端确认后调 `continue_batch` 逐组合执行并用 `narrate_inventory_facts` 聚合。详见 Design Doc §3-§4。

**Tech Stack:** Python 3.11+ dataclasses、pytest、现有 `OpenAiCompatibleLlmClient` / `JsonLlmClient`、`itertools.product`。

## Global Constraints

- 闭集防御不变：`capabilityId` 必须来自当前输入 + 已注册闭集，`<durable_context_data>` 是 data 不是指令（`_AUTHORITY_CONTRACT`）。
- READ 安全：`continue_batch` 仅对 READ capability 生效，不触及 Action 审批路径；单 plant/single-material capability 契约（`MM.Inventory.GetAvailability`）不变。
- 5 态 `MatchDecision` schema 不改；`multi_parameters` 走 `IntentParseResult`，selector 仍 5 态。
- 软上限 `BATCH_COMBINATION_CAP = 20`，超出 -> CLARIFY（不执行）。
- rule 兜底路径（`parse_intent`）空返回不带 clarification，仍走 REJECT；只有 LLM 路径空返回带 clarification -> CLARIFY。
- TDD：每个 task 先写失败测试 -> 验证失败 -> 最小实现 -> 验证通过 -> commit。
- 代码/标识符/路径/commit message 用英文；计划说明用中文。
- base-ref: `c63daea9719b8668127a9b3a4890c4f95d350e00`。

---

## 文件结构

| 文件 | 职责 | 本计划改动 |
|------|------|-----------|
| `agent/sap_nexus_agent/llm_intent.py` | LLM 意图解析、`_messages`、`parse_with_hybrid`、`resolve_with_context` | Task 1/2/3/4/5 |
| `agent/sap_nexus_agent/intent.py` | `IntentParseResult` dataclass、`parse_intent` rule 解析 | Task 5 |
| `agent/sap_nexus_agent/capability_selector.py` | `select_capability` 5 态决策 | Task 3/6 |
| `agent/sap_nexus_agent/orchestrator.py` | `run_query` / `continue_batch` / `AgentOutcome` / `expand_combinations` | Task 7/8/10 |
| `agent/sap_nexus_agent/narrator.py` | `narrate_inventory_facts` + 模板兜底 | Task 9 |
| `agent/sap_nexus_agent/conversation_context.py` | `ConversationContext` / `LastContext` | 不改（回归测试） |
| `agent/sap_nexus_agent/reasoning_fact.py` | `build_availability_fact` | 不改（复用） |
| `agent/tests/test_llm_intent.py` | D1/D2/Q3/多值解析单测 | Task 1/2/3/5 |
| `agent/tests/test_intent.py` | D3 rule 兜底继承单测 | Task 4/6 |
| `agent/tests/test_orchestrator.py` | expand/run_query 多值/continue_batch/软上限 | Task 7/8/10/12 |
| `agent/tests/test_reasoning_narrator.py` | `narrate_inventory_facts` 单测 | Task 9 |
| `agent/tests/test_conversation_context.py` | LastContext round-trip 回归 | Task 11 |

---

## Task 1: `_messages` 注入 `last_context` data 块

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py:112-166`（`_AUTHORITY_CONTRACT` 之后、`_messages` 函数体）
- Test: `agent/tests/test_llm_intent.py`

**Interfaces:**
- Consumes: `ConversationContext.last_context: LastContext | None`（已存在，字段 `capability_id`/`parameters`/`missing_parameters`/`decision_type`）
- Produces: `_messages` 在 `context.last_context` 非空时多返回一个 `<durable_context_data>` user 块；新增 `_format_last_context_block(lc) -> dict[str, str]`

- [x] **Step 1: 写失败测试**

追加到 `agent/tests/test_llm_intent.py`：

```python
from sap_nexus_agent.conversation_context import ConversationContext, LastContext, Turn
from sap_nexus_agent.llm_intent import _messages, _format_last_context_block
from sap_nexus_agent.registry_loader import load_intent_catalog


def test_messages_injects_last_context_block():
    catalog = load_intent_catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "5100"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    msgs = _messages("这个物料在1000的库存", catalog, context=ctx)

    # authority + last_context block + base_system + base_user
    assert len(msgs) == 4
    assert msgs[0]["role"] == "system"
    assert "<durable_context_data>" in msgs[1]["content"]
    assert "DEMOA2" in msgs[1]["content"]
    assert "MM.Inventory.GetAvailability" in msgs[1]["content"]
    assert "SELECT" in msgs[1]["content"]
    assert msgs[2]["role"] == "system"
    assert msgs[3]["role"] == "user"


def test_messages_without_context_returns_baseline():
    catalog = load_intent_catalog()
    msgs = _messages("DEMOA2 在 5100 的库存", catalog, context=None)
    assert msgs == [msgs[0], msgs[-1]]
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"


def test_format_last_context_block_structure():
    lc = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2"},
        missing_parameters=["plant"],
        decision_type="CLARIFY",
    )
    block = _format_last_context_block(lc)
    assert block["role"] == "user"
    assert "<durable_context_data>" in block["content"]
    assert "MM.Inventory.GetAvailability" in block["content"]
    assert "DEMOA2" in block["content"]
    assert "CLARIFY" in block["content"]
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_llm_intent.py::test_messages_injects_last_context_block -v`
Expected: FAIL with `ImportError: cannot import name '_format_last_context_block'`

- [x] **Step 3: 最小实现**

在 `agent/sap_nexus_agent/llm_intent.py` 的 `_AUTHORITY_CONTRACT` 定义之后（约 line 117）、`_format_history` 之前，新增：

```python
def _format_last_context_block(lc: "LastContext") -> dict[str, str]:
    """Format last_context as a <durable_context_data> user block (data, not instruction)."""
    return {
        "role": "user",
        "content": (
            "<durable_context_data>\n上轮决策:\n"
            f"  capability: {lc.capability_id}\n"
            f"  parameters: {lc.parameters}\n"
            f"  decision: {lc.decision_type}\n"
            "</durable_context_data>"
        ),
    }
```

在文件顶部 `TYPE_CHECKING` 块（已有 `ConversationContext` import 处）补 `LastContext` import：

```python
if TYPE_CHECKING:
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext, Turn
```

（若 `Turn` 已 import 则只补 `LastContext`；保持与现有 import 风格一致。）

替换 `_messages` 函数体（line 126-166）为：

```python
def _messages(
    text: str,
    catalog: IntentCatalog,
    *,
    context: "ConversationContext | None" = None,
) -> list[dict[str, object]]:
    capabilities_desc = "\n".join(
        f"- capabilityId: {c.capability_id}\n"
        f"  description: {c.description}\n"
        f"  inputs:\n{_format_inputs(c.inputs)}"
        for c in catalog.capabilities
    )
    base_system = {
        "role": "system",
        "content": (
            "You extract SAP Nexus read-only query intent as strict JSON. "
            "Detect all matching capabilities from the registered closed set below. "
            "- If exactly one capability matches with required parameters, return it as capabilityId. "
            "- If more than one capability matches, return an escalation with all matched candidates. "
            "- If ambiguous (weak match across multiple capabilities without a clear primary), return options. "
            "- Never introduce capabilityIds outside the closed set. "
            "Never output rfcName or raw SAP BAPI/RFC names. "
            "Return keys: capabilityId, candidates, escalation, parameters, missingParameters, clarification.\n\n"
            f"Registered capabilities:\n{capabilities_desc}"
        ),
    }
    base_user = {"role": "user", "content": text}

    if context is None or (context.last_context is None and not context.history):
        return [base_system, base_user]

    authority = {"role": "system", "content": _AUTHORITY_CONTRACT}
    blocks: list[dict[str, object]] = []
    if context.last_context is not None:
        blocks.append(_format_last_context_block(context.last_context))
    if context.history:
        # 近 3 轮滑窗：1 轮 = user + assistant = 2 条 Turn，3 轮 = 6 条 Turn。
        recent = context.history[-6:]
        blocks.append({
            "role": "user",
            "content": f"<durable_context_data>\n{_format_history(recent)}\n</durable_context_data>",
        })
    return [authority, *blocks, base_system, base_user]
```

- [x] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_llm_intent.py::test_messages_injects_last_context_block tests/test_llm_intent.py::test_messages_without_context_returns_baseline tests/test_llm_intent.py::test_format_last_context_block_structure -v`
Expected: 3 PASS

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent): inject last_context data block into _messages"
```

---

## Task 2: `parse_with_hybrid` LLM 为主，rule 仅 `LlmUnavailable` 兜底

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py:56-74`（`parse_with_hybrid`）
- Test: `agent/tests/test_llm_intent.py`

**Interfaces:**
- Consumes: Task 1 的 `_messages` 注入 last_context
- Produces: `parse_with_hybrid` 仅在 `LlmUnavailable` 时调 `parse_intent(text, context=context)`，LLM 有效结果直接返回

- [x] **Step 1: 写失败测试**

追加到 `agent/tests/test_llm_intent.py`：

```python
from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.llm_client import LlmUnavailable
from sap_nexus_agent.llm_intent import parse_with_hybrid
from sap_nexus_agent.match_decision import MatchedIntent


class _StubJsonClient:
    """Stub JsonLlmClient returning a preset payload."""
    def __init__(self, payload):
        self._payload = payload
        self.call_count = 0

    def chat_json(self, messages, **kwargs):
        self.call_count += 1
        return self._payload


class _RaisingJsonClient:
    """Stub JsonLlmClient that always raises LlmUnavailable."""
    def chat_json(self, messages, **kwargs):
        raise LlmUnavailable("connection refused")


def test_parse_with_hybrid_uses_llm_result_directly():
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "1000"},
    }
    client = _StubJsonClient(payload)
    result = parse_with_hybrid("DEMOA2 在 1000 的库存", client=client)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters == {"material": "DEMOA2", "plant": "1000"}
    assert client.call_count == 1


def test_parse_with_hybrid_falls_back_to_rule_on_llm_unavailable():
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    result = parse_with_hybrid("查下这个物料在1000的库存", client=_RaisingJsonClient(), context=ctx)
    # rule 兜底应走 parse_intent(text, context=context) -> resolve_with_context（Task 4 实现继承）
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters.get("plant") == "1000"


def test_parse_with_hybrid_empty_llm_return_does_not_invoke_rule(monkeypatch):
    """LLM 空返回时不再回退 rule（D2）；clarification 由 Task 3 填充。"""
    rule_calls = []
    original_parse_intent = __import__("sap_nexus_agent.intent", fromlist=["parse_intent"]).parse_intent

    def spy_parse_intent(text, context=None):
        rule_calls.append(text)
        return original_parse_intent(text, context=context)

    monkeypatch.setattr("sap_nexus_agent.llm_intent.parse_intent", spy_parse_intent)

    payload = {"capabilityId": None, "parameters": {}}
    client = _StubJsonClient(payload)
    result = parse_with_hybrid("完全不匹配的无关文本", client=client)
    assert client.call_count == 1
    assert rule_calls == []  # rule 未被调用
    assert result.capability_id is None
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_llm_intent.py::test_parse_with_hybrid_empty_llm_return_does_not_invoke_rule -v`
Expected: FAIL（当前 `parse_with_hybrid` 在 `_requires_safe_fallback` 时调用 `parse_intent`，`rule_calls` 非空）

- [x] **Step 3: 最小实现**

替换 `parse_with_hybrid`（line 56-74）为：

```python
def parse_with_hybrid(
    text: str,
    client: JsonLlmClient | None = None,
    *,
    catalog: IntentCatalog | None = None,
    context: "ConversationContext | None" = None,
) -> IntentParseResult:
    if catalog is None:
        catalog = load_intent_catalog()
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        return parse_with_llm(text, llm_client, catalog, context=context)
    except LlmUnavailable:
        return parse_intent(text, context=context)
```

> 说明：移除 `_requires_safe_fallback` -> rule 回退分支。`_requires_safe_fallback` 函数本身保留（`_parse_llm_only` 等内部仍可能引用），但其调用点删除。

- [x] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_llm_intent.py::test_parse_with_hybrid_uses_llm_result_directly tests/test_llm_intent.py::test_parse_with_hybrid_falls_back_to_rule_on_llm_unavailable tests/test_llm_intent.py::test_parse_with_hybrid_empty_llm_return_does_not_invoke_rule -v`
Expected: 3 PASS

> 注：`test_parse_with_hybrid_falls_back_to_rule_on_llm_unavailable` 完整通过依赖 Task 4 的 material 继承；若 Task 4 未完成，该断言可能因 `parameters.get("plant")` 失败。建议本 task 先让前两个测试通过，第三个测试在 Task 4 后回归。如需本 task 独立通过，可临时只断言 `result.capability_id == "MM.Inventory.GetAvailability"`。

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py
git commit -m "feat(llm-intent): LLM as primary, rule fallback only on LlmUnavailable"
```

---

## Task 3: LLM 空返回填充 generic clarification，selector 发 CLARIFY

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py:177-288`（`_payload_to_parse_result` 的 3 个空返回路径）
- Modify: `agent/sap_nexus_agent/capability_selector.py:130-135`（第 6 步 REJECT 前加 clarification 判断）
- Test: `agent/tests/test_llm_intent.py`、`agent/tests/test_capability_selector.py`

**Interfaces:**
- Consumes: Task 2 的 `parse_with_hybrid`（LLM 空返回直接用）
- Produces: LLM 路径空返回的 `IntentParseResult.clarification` 非 None；`select_capability` 第 6 步前判断 `clarification and not capability_id` -> CLARIFY

- [x] **Step 1: 写失败测试**

追加到 `agent/tests/test_llm_intent.py`：

```python
from sap_nexus_agent.llm_intent import _payload_to_parse_result
from sap_nexus_agent.registry_loader import load_intent_catalog


def test_payload_empty_capabilityId_fills_clarification():
    catalog = load_intent_catalog()
    result = _payload_to_parse_result({"capabilityId": None, "parameters": {}}, catalog)
    assert result.capability_id is None
    assert result.clarification is not None
    assert "物料" in result.clarification or "工厂" in result.clarification or "明确" in result.clarification


def test_payload_unknown_capability_fills_clarification():
    catalog = load_intent_catalog()
    result = _payload_to_parse_result({"capabilityId": "MM.Bogus.Capability"}, catalog)
    assert result.capability_id is None
    assert result.clarification is not None


def test_payload_all_candidates_unknown_fills_clarification():
    catalog = load_intent_catalog()
    payload = {"candidates": [{"capabilityId": "MM.Bogus.A"}, {"capabilityId": "MM.Bogus.B"}]}
    result = _payload_to_parse_result(payload, catalog)
    assert result.capability_id is None
    assert result.clarification is not None
```

追加到 `agent/tests/test_capability_selector.py`：

```python
from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.intent import IntentParseResult


def test_select_emits_clarify_when_llm_clarification_present():
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        clarification="无法识别查询意图，请明确物料、工厂等信息",
        capability_id=None,
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "CLARIFY"
    assert decision.rationale == "无法识别查询意图，请明确物料、工厂等信息"


def test_select_emits_reject_when_no_clarification():
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        clarification=None,
        capability_id=None,
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "REJECT"
    assert decision.error_type == "UNSUPPORTED_INTENT"
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_llm_intent.py::test_payload_empty_capabilityId_fills_clarification tests/test_capability_selector.py::test_select_emits_clarify_when_llm_clarification_present -v`
Expected: FAIL（当前空返回 `clarification=None`，selector 走 REJECT）

- [x] **Step 3: 最小实现**

在 `agent/sap_nexus_agent/llm_intent.py` 顶部常量区新增：

```python
_LLM_EMPTY_CLARIFICATION = "无法识别查询意图，请明确物料、工厂等信息"
```

修改 `_payload_to_parse_result` 的 3 个空返回路径（line 256、261、265），将：

```python
return IntentParseResult(intent=None, parameters={}, missing_parameters=[])
```

替换为：

```python
return IntentParseResult(
    intent=None,
    parameters={},
    missing_parameters=[],
    clarification=_LLM_EMPTY_CLARIFICATION,
)
```

（共 3 处：all candidates unknown 路径、single capabilityId unknown 路径、descriptor None 路径。）

修改 `agent/sap_nexus_agent/capability_selector.py` 第 6 步（line 130-135），在最终 REJECT 前插入：

```python
    # 6. No match -> REJECT(UNSUPPORTED_INTENT). LLM 路径空返回带 clarification 时发 CLARIFY
    #    (rule 路径空返回无 clarification，仍走 REJECT)。
    if parse_result.clarification and not parse_result.capability_id:
        return MatchDecision(
            decision_type="CLARIFY",
            capability_id=None,
            parameters={},
            missing_parameters=[],
            rationale=parse_result.clarification,
        )

    return MatchDecision(
        decision_type="REJECT",
        error_type="UNSUPPORTED_INTENT",
        rationale="当前仅支持已注册的能力（库存可用量查询、采购订单列表、采购申请草稿创建）。",
    )
```

- [x] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_llm_intent.py tests/test_capability_selector.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [x] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/sap_nexus_agent/capability_selector.py agent/tests/test_llm_intent.py agent/tests/test_capability_selector.py
git commit -m "feat(intent): LLM empty return emits CLARIFY instead of REJECT"
```

---

## Task 4: `resolve_with_context` 主关键词分支继承 `last_context` material

**Files:**
- Modify: `agent/sap_nexus_agent/llm_intent.py:407-412`（`resolve_with_context` 主关键词分支）
- Test: `agent/tests/test_intent.py`

**Interfaces:**
- Consumes: `ConversationContext.last_context.parameters`（已存在）
- Produces: rule 兜底时，主关键词 + 提取不到 material + last_context 有 material -> 继承 material

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_intent.py`：

```python
from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.intent import parse_intent


def test_rule_fallback_inherits_material_on_primary_keyword():
    """LLM 不可用 rule 兜底：主关键词 + 提取不到 material + last_context 有 -> 继承。"""
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "5100"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    result = parse_intent("查下这个物料在1000的库存", context=ctx)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters.get("material") == "DEMOA2"
    assert result.parameters.get("plant") == "1000"


def test_rule_fallback_does_not_inherit_when_new_material_present():
    """有新物料时不继承 last_context material。"""
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "5100"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    result = parse_intent("查 DEMOA4 在 1000 的库存", context=ctx)
    assert result.parameters.get("material") == "DEMOA4"
    assert result.parameters.get("plant") == "1000"


def test_rule_fallback_no_inherit_without_last_context():
    """无 last_context 时主关键词分支正常走单轮（不继承）。"""
    ctx = ConversationContext(last_context=None, history=None)
    result = parse_intent("查下这个物料在1000的库存", context=ctx)
    assert result.capability_id is None or result.missing_parameters == ["material"]
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_intent.py::test_rule_fallback_inherits_material_on_primary_keyword -v`
Expected: FAIL（当前主关键词分支 `return parse_intent(text)` 丢弃 context，`material` 缺失）

- [ ] **Step 3: 最小实现**

修改 `agent/sap_nexus_agent/llm_intent.py` 的 `resolve_with_context`（line 410-412），将：

```python
    # New turn if utterance contains any primary keyword.
    if _contains_any_primary_keyword(text):
        return parse_intent(text)
```

替换为：

```python
    # New turn if utterance contains any primary keyword. Rule fallback path
    # (D3): if the extractor cannot extract material but last_context has one,
    # inherit it so anaphora ("这个物料") still resolves under rule fallback.
    if _contains_any_primary_keyword(text):
        parsed = parse_intent(text)
        if (
            "material" not in parsed.parameters
            and context.last_context.parameters.get("material")
        ):
            parsed.parameters["material"] = context.last_context.parameters["material"]
        return parsed
```

> 说明：`IntentParseResult` 是 frozen dataclass。需用 `dataclasses.replace` 或先 `dict(parsed.parameters)` 再构造新实例。由于 `parameters: dict[str, str]` 是可变对象且 frozen dataclass 仅阻止重新绑定属性、不阻止修改可变属性，`parsed.parameters["material"] = ...` 在运行时可工作（与 `resolve_with_context` 现有 `merged = {**...}` 风格略不同但等价）。若需严格不可变，改为：

```python
    if _contains_any_primary_keyword(text):
        parsed = parse_intent(text)
        if (
            "material" not in parsed.parameters
            and context.last_context.parameters.get("material")
        ):
            from dataclasses import replace
            new_params = dict(parsed.parameters)
            new_params["material"] = context.last_context.parameters["material"]
            parsed = replace(parsed, parameters=new_params)
        return parsed
```

推荐用 `dataclasses.replace` 版本（严格不可变）。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_intent.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/llm_intent.py agent/tests/test_intent.py
git commit -m "feat(intent): rule fallback inherits last_context material on primary keyword"
```

---

## Task 5: `IntentParseResult.multi_parameters` + LLM 解析 `multiParameters` + base_system 多值指引

**Files:**
- Modify: `agent/sap_nexus_agent/intent.py:79-99`（`IntentParseResult` 加字段）
- Modify: `agent/sap_nexus_agent/llm_intent.py:138-151`（`_messages` base_system 加多值指引）、`177-288`（`_payload_to_parse_result` 解析 `multiParameters`）
- Test: `agent/tests/test_llm_intent.py`

**Interfaces:**
- Consumes: 无
- Produces: `IntentParseResult.multi_parameters: dict[str, list[str]]`（默认 `{}`）；`_payload_to_parse_result` 填充 `multi_parameters`；base_system 含通用多值指引

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_llm_intent.py`：

```python
def test_payload_parses_multi_parameters():
    catalog = load_intent_catalog()
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {},
        "multiParameters": {"plant": ["5200", "1000"], "material": ["DEMOA2", "DEMOA4"]},
    }
    result = _payload_to_parse_result(payload, catalog)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.multi_parameters == {
        "plant": ["5200", "1000"],
        "material": ["DEMOA2", "DEMOA4"],
    }


def test_payload_multi_parameters_defaults_empty():
    catalog = load_intent_catalog()
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2", "plant": "5100"},
    }
    result = _payload_to_parse_result(payload, catalog)
    assert result.multi_parameters == {}


def test_payload_multi_parameters_ignores_non_list_values():
    catalog = load_intent_catalog()
    payload = {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {},
        "multiParameters": {"plant": "5200"},
    }
    result = _payload_to_parse_result(payload, catalog)
    assert result.multi_parameters == {}


def test_messages_base_system_contains_multi_value_guidance():
    catalog = load_intent_catalog()
    msgs = _messages("DEMOA2 和 DEMOA4 在 5200、1000 的库存", catalog, context=None)
    system_content = msgs[0]["content"]
    assert "multiParameters" in system_content
    assert "数组" in system_content or "array" in system_content.lower()
```

追加到 `agent/tests/test_intent.py`：

```python
def test_intent_parse_result_has_multi_parameters_field():
    from sap_nexus_agent.intent import IntentParseResult
    result = IntentParseResult(intent=None, parameters={}, missing_parameters=[])
    assert result.multi_parameters == {}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_llm_intent.py::test_payload_parses_multi_parameters tests/test_intent.py::test_intent_parse_result_has_multi_parameters_field -v`
Expected: FAIL（`IntentParseResult` 无 `multi_parameters` 字段；`_payload_to_parse_result` 未解析 `multiParameters`）

- [ ] **Step 3: 最小实现**

修改 `agent/sap_nexus_agent/intent.py` 的 `IntentParseResult`（line 79-99），在 `is_ambiguous` 字段后追加：

```python
    is_ambiguous: bool = False
    # Multi-value parameters (Design Doc §4.2): any parameter can carry multiple
    # values. Orthogonal to ``parameters`` (single-valued). Default empty for
    # backward compatibility.
    multi_parameters: dict[str, list[str]] = field(default_factory=dict)
```

修改 `agent/sap_nexus_agent/llm_intent.py` 的 `_messages` base_system content（line 140-149），在 `Return keys: ...` 行之前追加多值指引：

```python
    base_system = {
        "role": "system",
        "content": (
            "You extract SAP Nexus read-only query intent as strict JSON. "
            "Detect all matching capabilities from the registered closed set below. "
            "- If exactly one capability matches with required parameters, return it as capabilityId. "
            "- If more than one capability matches, return an escalation with all matched candidates. "
            "- If ambiguous (weak match across multiple capabilities without a clear primary), return options. "
            "- Never introduce capabilityIds outside the closed set. "
            "Never output rfcName or raw SAP BAPI/RFC names. "
            "- If the user mentions multiple values for a parameter (e.g. multiple plants or materials), "
            "put that parameter in the multiParameters object as a string array, not in parameters. "
            "Single-valued parameters remain in parameters. "
            "Return keys: capabilityId, candidates, escalation, parameters, multiParameters, missingParameters, clarification.\n\n"
            f"Registered capabilities:\n{capabilities_desc}"
        ),
    }
```

修改 `_payload_to_parse_result`（line 177-288），在函数开头（`contains_rfc_name`/`contains_odata_override` 检查之后、`candidates_raw` 之前）新增 `multi_parameters` 解析：

```python
    raw_multi = payload.get("multiParameters") or {}
    multi_parameters: dict[str, list[str]] = {
        str(k): [str(v) for v in vals]
        for k, vals in raw_multi.items()
        if isinstance(vals, list)
    }
```

然后在所有 `return IntentParseResult(...)` 调用中追加 `multi_parameters=multi_parameters` 参数（单 capabilityId 命中路径、单 candidate 命中路径、multi-intent 路径、3 个空返回路径）。例：

```python
    return IntentParseResult(
        intent=None,
        capability_id=str(capability_id),
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
        matched_intents=[...],
        multi_parameters=multi_parameters,
    )
```

> 注意：rfcName/OData 注入拒绝路径（line 187-193）不携带 multi_parameters（保持空），因为它返回 `IntentParseResult(intent=None, parameters={}, missing_parameters=[], contains_rfc_name=..., contains_odata_override=...)`，默认 `multi_parameters={}` 即可，无需显式传。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_llm_intent.py tests/test_intent.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/llm_intent.py agent/tests/test_llm_intent.py agent/tests/test_intent.py
git commit -m "feat(intent): add multi_parameters field, parse multiParameters, base_system guidance"
```

---

## Task 6: `select_capability` 视 `multi_parameters` 满足 required 参数

**Files:**
- Modify: `agent/sap_nexus_agent/capability_selector.py:106-128`（missing 判定 + SELECT 分支）
- Test: `agent/tests/test_capability_selector.py`

**Interfaces:**
- Consumes: Task 5 的 `IntentParseResult.multi_parameters`
- Produces: required 参数在 `parameters` 或 `multi_parameters` 即算齐全 -> SELECT；`MatchDecision.parameters` 仍只含单值 `parameters`

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_capability_selector.py`：

```python
def test_select_satisfied_by_multi_parameters():
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        capability_id="MM.Inventory.GetAvailability",
        multi_parameters={"plant": ["5200", "1000"], "material": ["DEMOA2"]},
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "SELECT"
    assert decision.capability_id == "MM.Inventory.GetAvailability"
    assert decision.parameters == {}  # multi_parameters 不进 MatchDecision.parameters
    assert decision.missing_parameters is None or decision.missing_parameters == []


def test_select_clarify_when_multi_parameters_partial():
    """multi_parameters 只覆盖部分 required -> 仍 CLARIFY。"""
    parse_result = IntentParseResult(
        intent=None,
        parameters={},
        missing_parameters=[],
        capability_id="MM.Inventory.GetAvailability",
        multi_parameters={"plant": ["5200"]},  # material 缺失
    )
    decision = select_capability(parse_result)
    assert decision.decision_type == "CLARIFY"
    assert "material" in (decision.missing_parameters or [])
```

> 注：上述测试假设 inventory descriptor 的 required inputs 含 `material` + `plant`。若实际 descriptor 有差异，按实际 required 字段调整。可在测试前用 `load_intent_catalog().find("MM.Inventory.GetAvailability").inputs` 确认。

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_capability_selector.py::test_select_satisfied_by_multi_parameters -v`
Expected: FAIL（当前 missing 判定只看 `parameters`，`material`/`plant` 在 `multi_parameters` 时算 missing -> CLARIFY）

- [ ] **Step 3: 最小实现**

修改 `agent/sap_nexus_agent/capability_selector.py` 第 4 步 missing 判定（line 106-118），在 `if parse_result.missing_parameters:` 之前，把 missing 计算改为同时考虑 `multi_parameters`。

但注意：`missing_parameters` 是 `IntentParseResult` 上预先算好的字段（由 `_payload_to_parse_result` / `_build_inventory_result` 填充）。selector 当前直接读 `parse_result.missing_parameters`，不重新计算。

因此需要在 selector 中重新计算 missing（覆盖 parse_result 的预计算值）。修改第 4 步：

```python
    # 4. Single intent missing required parameters -> CLARIFY.
    #    multi_parameters 也算 provided（Design Doc §4.3）：required 参数在
    #    parameters 或 multi_parameters 中即算齐全。
    provided = set(parse_result.parameters.keys()) | set(parse_result.multi_parameters.keys())
    capability_id_for_missing = parse_result.capability_id
    if not capability_id_for_missing and parse_result.matched_intents:
        capability_id_for_missing = parse_result.matched_intents[0].capability_id
    missing: list[str] = []
    if capability_id_for_missing:
        # Lazy import to get descriptor inputs.
        from sap_nexus_agent.registry_loader import load_intent_catalog
        descriptor = load_intent_catalog().find(capability_id_for_missing)
        if descriptor is not None:
            missing = [
                inp.name
                for inp in descriptor.inputs
                if inp.required and inp.name not in provided
            ]
    if missing:
        clarify_cap_id = capability_id_for_missing
        if not clarify_cap_id:
            clarify_cap_id = INTENT_TO_CAPABILITY.get(parse_result.intent)
        return MatchDecision(
            decision_type="CLARIFY",
            capability_id=clarify_cap_id,
            parameters=dict(parse_result.parameters),
            missing_parameters=missing,
            rationale=parse_result.clarification or "请补充缺失的参数",
        )
```

> 说明：lazy `load_intent_catalog()` 每次调用有 IO 开销但保证闭集一致；与现有 `INTENT_TO_CAPABILITY` fallback 链保持一致。SELECT 分支（第 5 步）`parameters=dict(parse_result.parameters)` 不变（不含 multi_parameters，orchestrator 从 `parsed.multi_parameters` 读）。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_capability_selector.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/capability_selector.py agent/tests/test_capability_selector.py
git commit -m "feat(selector): treat multi_parameters as satisfying required inputs"
```

---

## Task 7: `expand_combinations` + `AgentOutcome.combinations` + `BATCH_COMBINATION_CAP`

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py:46-74`（常量 + AgentOutcome 字段）
- Modify: `agent/sap_nexus_agent/orchestrator.py`（新增 `expand_combinations` 函数）
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 5 的 `IntentParseResult.multi_parameters`
- Produces: `expand_combinations(base, multi) -> list[dict[str, str]]`（笛卡尔积）；`AgentOutcome.combinations: list[dict[str, str]] | None`；`BATCH_COMBINATION_CAP = 20`

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_orchestrator.py`：

```python
from sap_nexus_agent.orchestrator import AgentOutcome, expand_combinations, BATCH_COMBINATION_CAP


def test_expand_combinations_single_key():
    base = {"material": "DEMOA2", "unit": "EA"}
    multi = {"plant": ["5200", "1000"]}
    combos = expand_combinations(base, multi)
    assert combos == [
        {"material": "DEMOA2", "unit": "EA", "plant": "5200"},
        {"material": "DEMOA2", "unit": "EA", "plant": "1000"},
    ]


def test_expand_combinations_multi_key_cartesian():
    base = {"unit": "EA"}
    multi = {"plant": ["5200", "1000"], "material": ["DEMOA2", "DEMOA4"]}
    combos = expand_combinations(base, multi)
    assert len(combos) == 4
    assert {"plant": "5200", "material": "DEMOA2", "unit": "EA"} in combos
    assert {"plant": "1000", "material": "DEMOA4", "unit": "EA"} in combos


def test_expand_combinations_empty_multi():
    assert expand_combinations({"material": "DEMOA2"}, {}) == [{"material": "DEMOA2"}]


def test_batch_combination_cap_constant():
    assert BATCH_COMBINATION_CAP == 20


def test_agent_outcome_has_combinations_field():
    outcome = AgentOutcome(status="awaiting_batch_confirm", combinations=[{"plant": "5200"}])
    assert outcome.combinations == [{"plant": "5200"}]
    outcome2 = AgentOutcome(status="success")
    assert outcome2.combinations is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_orchestrator.py::test_expand_combinations_single_key tests/test_orchestrator.py::test_batch_combination_cap_constant -v`
Expected: FAIL with `ImportError: cannot import name 'expand_combinations'`

- [ ] **Step 3: 最小实现**

在 `agent/sap_nexus_agent/orchestrator.py` 顶部 import 区（line 1-43 之后）新增：

```python
import itertools
```

在常量区（line 46-49 之后）新增：

```python
# Soft cap for multi-value combination expansion (Design Doc §4.4). Exceeding
# this emits CLARIFY instead of awaiting_batch_confirm.
BATCH_COMBINATION_CAP = 20
```

在 `AgentOutcome` dataclass（line 52-74）的 `dry_run` 字段后追加：

```python
    dry_run: DryRunResult | None = None
    # Multi-value batch (Design Doc §4.4): combinations awaiting user confirm.
    # Populated only for status="awaiting_batch_confirm".
    combinations: list[dict[str, str]] | None = None
```

在 `AgentOutcome` 之后、`run_query` 之前新增函数：

```python
def expand_combinations(
    base: dict[str, str],
    multi: dict[str, list[str]],
) -> list[dict[str, str]]:
    """Cartesian product of multi-valued parameters over a base dict.

    Generic over parameter names (Design Doc §4.4). Single key -> N combos;
    multi key -> Cartesian product. Empty ``multi`` -> single ``base`` combo.
    """
    if not multi:
        return [dict(base)]
    keys = list(multi.keys())
    value_lists = [multi[k] for k in keys]
    combos: list[dict[str, str]] = []
    for values in itertools.product(*value_lists):
        combo = dict(base)
        combo.update(dict(zip(keys, values)))
        combos.append(combo)
    return combos
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_orchestrator.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat(orchestrator): add expand_combinations, AgentOutcome.combinations, BATCH_COMBINATION_CAP"
```

---

## Task 8: `run_query` SELECT 分支多值检测 -> `awaiting_batch_confirm` / 软上限 CLARIFY

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py:162-216`（`run_query` SELECT 分支，在 `create_call_plan` 之前插入多值检测）
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 6 的 selector SELECT + `parsed.multi_parameters`；Task 7 的 `expand_combinations` / `BATCH_COMBINATION_CAP` / `AgentOutcome.combinations`
- Produces: 多值非空 -> expand -> 软上限检查 -> `awaiting_batch_confirm`（不执行 Gateway）；超上限 -> CLARIFY

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_orchestrator.py`：

```python
from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.match_decision import MatchedIntent


def _multi_value_adapter(multi_parameters):
    """Stub adapter returning a preset multi_parameters IntentParseResult."""
    def _adapter(text, context=None):
        return IntentParseResult(
            intent=None,
            parameters={"unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"unit": "EA"},
                missing=[],
            )],
            multi_parameters=multi_parameters,
        )
    return _adapter


def test_run_query_multi_value_emits_awaiting_batch_confirm():
    gateway = FakeGatewayClient()
    adapter = _multi_value_adapter({"plant": ["5200", "1000"], "material": ["DEMOA2", "DEMOA4"]})
    outcome = run_query("DEMOA2 和 DEMOA4 在 5200、1000 的库存", gateway, intent_adapter=adapter)
    assert outcome.status == "awaiting_batch_confirm"
    assert outcome.combinations is not None
    assert len(outcome.combinations) == 4
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []
    assert outcome.call_plan is not None
    assert outcome.call_plan.capability_id == "MM.Inventory.GetAvailability"


def test_run_query_multi_value_over_cap_emits_clarify():
    gateway = FakeGatewayClient()
    # 21 个 plant 组合 > cap 20
    plants = [f"P{i:03d}" for i in range(21)]
    adapter = _multi_value_adapter({"plant": plants, "material": ["DEMOA2"]})
    outcome = run_query("查 DEMOA2 在多个工厂的库存", gateway, intent_adapter=adapter)
    assert outcome.status == "clarification"
    assert "组合数" in (outcome.response_text or "")
    assert outcome.combinations is None
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []


def test_run_query_single_value_still_executes():
    """单值回归：multi_parameters 空 -> 走原 execute 路径。"""
    gateway = FakeGatewayClient()
    adapter = _multi_value_adapter({})
    # 单值 adapter 把 material/plant 放 parameters
    def _single_adapter(text, context=None):
        return IntentParseResult(
            intent=None,
            parameters={"material": "DEMOA2", "plant": "5100", "unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "plant": "5100", "unit": "EA"},
                missing=[],
            )],
            multi_parameters={},
        )
    outcome = run_query("DEMOA2 在 5100 的库存", gateway, intent_adapter=_single_adapter)
    assert outcome.status == "success"
    assert outcome.fact is not None
    assert len(gateway.execute_calls) == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_orchestrator.py::test_run_query_multi_value_emits_awaiting_batch_confirm -v`
Expected: FAIL（当前 SELECT 分支直接 create_call_plan -> validate -> execute，不识别 multi_parameters）

- [ ] **Step 3: 最小实现**

修改 `agent/sap_nexus_agent/orchestrator.py` 的 `run_query` SELECT 分支（line 162-169），将：

```python
    # SELECT -> CallPlan -> Gateway validate/execute (existing path).
    capability_id = decision.capability_id
    parameters = dict(decision.parameters or parsed.parameters)
    if capability_id == INVENTORY_CAPABILITY_ID:
        parameters.setdefault("unit", "EA")

    kind = "Action" if capability_id in ACTION_CAPABILITY_IDS else "Function"
    call_plan = create_call_plan(capability_id, parameters, kind=kind)
```

替换为：

```python
    # SELECT -> CallPlan -> Gateway validate/execute (existing path).
    capability_id = decision.capability_id
    parameters = dict(decision.parameters or parsed.parameters)
    if capability_id == INVENTORY_CAPABILITY_ID:
        parameters.setdefault("unit", "EA")

    # Multi-value detection (Design Doc §4.4): expand combinations and await
    # user confirmation before any Gateway call.
    if parsed.multi_parameters:
        combinations = expand_combinations(parameters, parsed.multi_parameters)
        if len(combinations) > BATCH_COMBINATION_CAP:
            return AgentOutcome(
                status="clarification",
                response_text=f"组合数 {len(combinations)} 过多，请缩小范围（如减少物料或工厂）。",
                match_decision=decision,
            )
        kind = "Action" if capability_id in ACTION_CAPABILITY_IDS else "Function"
        call_plan = create_call_plan(capability_id, parameters, kind=kind)
        combos_desc = "; ".join(
            f"material={c.get('material')}, plant={c.get('plant')}" for c in combinations
        )
        return AgentOutcome(
            status="awaiting_batch_confirm",
            response_text=f"将查询 {len(combinations)} 个组合：{combos_desc}，请确认。",
            call_plan=call_plan,
            combinations=combinations,
            match_decision=decision,
        )

    kind = "Action" if capability_id in ACTION_CAPABILITY_IDS else "Function"
    call_plan = create_call_plan(capability_id, parameters, kind=kind)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_orchestrator.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat(orchestrator): multi-value SELECT emits awaiting_batch_confirm, cap emits CLARIFY"
```

---

## Task 9: `narrate_inventory_facts`（LLM 主 + 模板兜底 + guard）

**Files:**
- Modify: `agent/sap_nexus_agent/narrator.py`（新增 `narrate_inventory_facts` + `_build_inventory_batch_messages` + `_template_inventory_batch` + `_assert_inventory_fields`）
- Test: `agent/tests/test_reasoning_narrator.py`

**Interfaces:**
- Consumes: `ReasoningFact`（已存在，含 material/plant/value/unit）
- Produces: `narrate_inventory_facts(facts, *, failures=None, client=None) -> str`；LLM 不可用 -> 模板兜底；空 facts + 无 failures -> "无匹配记录。"

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_reasoning_narrator.py`：

```python
from sap_nexus_agent.narrator import narrate_inventory_facts, NarrativeGuardError
from sap_nexus_agent.reasoning_fact import ReasoningFact


def _inv_fact(material, plant, value, unit="EA"):
    return ReasoningFact(
        fact_id=f"fact-{material}-{plant}",
        agent_trace_id="trace-1",
        trace_id="trace-1",
        gateway_trace_id="gw-1",
        domain="MM",
        business_object="InventoryStock",
        predicate="availableQuantity",
        value=value,
        unit=unit,
        deterministic=True,
        confidence=1.0,
        source={"capabilityId": "MM.Inventory.GetAvailability"},
        evidence=[{"field": "availableQuantity", "value": value}],
        material=material,
        plant=plant,
    )


class _StubTextClient:
    def __init__(self, text):
        self._text = text

    def chat_text(self, messages, **kwargs):
        return self._text


class _RaisingTextClient:
    def chat_text(self, messages, **kwargs):
        from sap_nexus_agent.llm_client import LlmUnavailable
        raise LlmUnavailable("down")


def test_narrate_inventory_facts_empty():
    assert narrate_inventory_facts([]) == "无匹配记录。"


def test_narrate_inventory_facts_llm_main():
    facts = [_inv_fact("DEMOA2", "5200", 176), _inv_fact("DEMOA2", "1000", 0)]
    text = narrate_inventory_facts(facts, client=_StubTextClient("5200: 176 EA; 1000: 0 EA"))
    assert "5200" in text and "176" in text
    assert "1000" in text and "0" in text


def test_narrate_inventory_facts_template_fallback_single_material():
    facts = [_inv_fact("DEMOA2", "5200", 176), _inv_fact("DEMOA2", "1000", 0)]
    text = narrate_inventory_facts(facts, client=_RaisingTextClient())
    # 单物料模板："在工厂 5200 为 176 EA；在工厂 1000 为 0 EA"
    assert "5200" in text and "176" in text
    assert "1000" in text and "0" in text
    assert "DEMOA2" in text


def test_narrate_inventory_facts_template_fallback_multi_material():
    facts = [_inv_fact("DEMOA2", "5200", 176), _inv_fact("DEMOA4", "1000", 5)]
    text = narrate_inventory_facts(facts, client=_RaisingTextClient())
    assert "DEMOA2" in text
    assert "DEMOA4" in text
    assert "5200" in text and "176" in text
    assert "1000" in text and "5" in text


def test_narrate_inventory_facts_partial_failure():
    facts = [_inv_fact("DEMOA2", "5200", 176)]
    failures = [{"parameters": {"material": "DEMOA2", "plant": "1000"}, "error": "SAP_ERROR"}]
    text = narrate_inventory_facts(facts, failures=failures, client=_RaisingTextClient())
    assert "5200" in text
    assert "1000" in text  # 失败工厂被标注
    assert "失败" in text


def test_narrate_inventory_facts_guard_on_missing_fields():
    bad = ReasoningFact(
        fact_id="bad", agent_trace_id="t", trace_id="t", gateway_trace_id="g",
        domain="MM", business_object="InventoryStock", predicate="availableQuantity",
        value=None, unit=None, deterministic=True, confidence=1.0,
        source={}, evidence=[], material=None, plant=None,
    )
    try:
        narrate_inventory_facts([bad], client=_RaisingTextClient())
        assert False, "expected NarrativeGuardError"
    except NarrativeGuardError:
        pass
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_reasoning_narrator.py::test_narrate_inventory_facts_empty -v`
Expected: FAIL with `ImportError: cannot import name 'narrate_inventory_facts'`

- [ ] **Step 3: 最小实现**

在 `agent/sap_nexus_agent/narrator.py` 的 `narrate_purchase_order_facts` 之后（约 line 224 之后）新增：

```python
# ---------------------------------------------------------------------------
# Inventory batch narrative (multi-value aggregation, Design Doc §4.5)
# ---------------------------------------------------------------------------


def _assert_inventory_fields(facts: list[ReasoningFact]) -> None:
    """Reject incomplete facts before narration, regardless of LLM availability."""
    for fact in facts:
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
            raise NarrativeGuardError(
                f"ReasoningFact missing fields for inventory narration: {', '.join(missing)}"
            )


def _build_inventory_batch_messages(
    facts: list[ReasoningFact],
    failures: list[dict] | None,
) -> list[dict[str, str]]:
    guidance = narration_guidance("MM.Inventory.GetAvailability")
    lines: list[str] = []
    for fact in facts:
        lines.append(
            f"物料: {fact.material}，工厂: {fact.plant}，"
            f"可用库存: {fact.value} {fact.unit}"
        )
    if failures:
        for fail in failures:
            params = fail.get("parameters", {})
            lines.append(
                f"查询失败: 物料 {params.get('material', '')}，"
                f"工厂 {params.get('plant', '')}，错误: {fail.get('error', '')}"
            )
    user_content = "\n".join(lines)
    return [
        {"role": "system", "content": _SYSTEM_CONSTRAINT},
        {"role": "system", "content": guidance},
        {"role": "user", "content": user_content},
    ]


def _template_inventory_batch(
    facts: list[ReasoningFact],
    failures: list[dict] | None,
) -> str:
    """Deterministic template fallback for batch inventory narration."""
    materials = {fact.material for fact in facts}
    lines: list[str] = []
    if len(materials) <= 1:
        # 单物料：对齐 spec "5200: 176 EA; 1000: 0 EA"
        material = next(iter(materials), None)
        if material:
            lines.append(f"物料 {material}：")
        plant_lines = [
            f"在工厂 {fact.plant} 为 {fact.value} {fact.unit}" for fact in facts
        ]
        lines.append("；".join(plant_lines) + "。")
    else:
        # 多物料：每条含 material
        for fact in facts:
            lines.append(
                f"物料 {fact.material} 在工厂 {fact.plant} 为 {fact.value} {fact.unit}；"
            )
        lines[-1] = lines[-1].rstrip("；") + "。"
    if failures:
        for fail in failures:
            params = fail.get("parameters", {})
            lines.append(f"工厂 {params.get('plant', '')} 查询失败。")
    return "".join(lines) if len(materials) <= 1 else "\n".join(lines)


def narrate_inventory_facts(
    facts: list[ReasoningFact],
    *,
    failures: list[dict] | None = None,
    client=None,
) -> str:
    """Grounded narrative for a list of inventory facts (multi-value aggregation).

    - Empty facts + no failures -> "无匹配记录。" (no LLM call).
    - Non-empty: LLM main path (chat_text + redact_sensitive).
    - LlmUnavailable -> template fallback (guard raises on missing fields).
    - Partial failures appended as annotations.
    """
    if not facts and not failures:
        return "无匹配记录。"

    _assert_inventory_fields(facts)

    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(
            _build_inventory_batch_messages(facts, failures), temperature=0.0, max_tokens=400
        )
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_inventory_batch(facts, failures)
```

> 说明：`narration_guidance` / `_SYSTEM_CONSTRAINT` / `OpenAiCompatibleLlmClient` / `redact_sensitive` / `LlmUnavailable` 均已在 narrator.py 现有 import 中。`NarrativeGuardError` 已定义在文件顶部。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_reasoning_narrator.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/narrator.py agent/tests/test_reasoning_narrator.py
git commit -m "feat(narrator): add narrate_inventory_facts with LLM main + template fallback"
```

---

## Task 10: `continue_batch` 逐组合 validate+execute + 部分失败聚合

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`（新增 `continue_batch` 函数，类比 `continue_action`）
- Modify: `agent/sap_nexus_agent/orchestrator.py` 顶部 import `narrate_inventory_facts`
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 7 的 `AgentOutcome.combinations`；Task 9 的 `narrate_inventory_facts`；`build_availability_fact`（已存在）；`create_call_plan` / `narrate_failure`（已存在）
- Produces: `continue_batch(call_plan, combinations, gateway, *, decision=None) -> AgentOutcome`；逐组合 validate+execute+build_availability_fact；部分失败不全局失败；全失败 -> failure outcome

- [ ] **Step 1: 写失败测试**

追加到 `agent/tests/test_orchestrator.py`：

```python
from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.orchestrator import continue_batch


class _BatchFakeGateway:
    """Gateway stub: validate always ok; execute returns preset result per (material, plant)."""
    def __init__(self, exec_map):
        self._exec_map = exec_map
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        return ValidationResult(
            trace_id="gw-v", capability_id=capability_id, success=True,
            error_type="NONE", messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, parameters))
        key = (parameters.get("material"), parameters.get("plant"))
        return self._exec_map.get(key, ExecutionResult(
            trace_id="gw-x", capability_id=capability_id, success=False,
            executor={"type": "JCO_RFC"}, return_messages=[],
            data={}, duration_ms=0, error_type="SAP_ERROR",
        ))


def _exec_ok(material, plant, qty):
    return ExecutionResult(
        trace_id=f"gw-{material}-{plant}", capability_id="MM.Inventory.GetAvailability",
        success=True, executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
        return_messages=[], data={"availableQuantity": qty, "unit": "EA"},
        duration_ms=5, error_type="NONE",
    )


def test_continue_batch_all_success():
    call_plan = create_call_plan("MM.Inventory.GetAvailability", {"unit": "EA"})
    combos = [
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
        {"material": "DEMOA2", "plant": "1000", "unit": "EA"},
    ]
    gw = _BatchFakeGateway({
        ("DEMOA2", "5200"): _exec_ok("DEMOA2", "5200", 176),
        ("DEMOA2", "1000"): _exec_ok("DEMOA2", "1000", 0),
    })
    outcome = continue_batch(call_plan, combos, gw)
    assert outcome.status == "success"
    assert outcome.facts is not None
    assert len(outcome.facts) == 2
    assert len(gw.execute_calls) == 2
    assert "5200" in outcome.response_text and "176" in outcome.response_text


def test_continue_batch_partial_failure():
    call_plan = create_call_plan("MM.Inventory.GetAvailability", {"unit": "EA"})
    combos = [
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
        {"material": "DEMOA2", "plant": "1000", "unit": "EA"},
    ]
    gw = _BatchFakeGateway({
        ("DEMOA2", "5200"): _exec_ok("DEMOA2", "5200", 176),
        # 1000 缺失 -> default failure
    })
    outcome = continue_batch(call_plan, combos, gw)
    assert outcome.status == "success"  # 部分失败不全局失败
    assert outcome.facts is not None
    assert len(outcome.facts) == 1
    assert "1000" in outcome.response_text  # 失败工厂被标注


def test_continue_batch_all_failure():
    call_plan = create_call_plan("MM.Inventory.GetAvailability", {"unit": "EA"})
    combos = [
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
    ]
    gw = _BatchFakeGateway({})  # 全部 default failure
    outcome = continue_batch(call_plan, combos, gw)
    assert outcome.status == "failure"
    assert outcome.facts == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_orchestrator.py::test_continue_batch_all_success -v`
Expected: FAIL with `ImportError: cannot import name 'continue_batch'`

- [ ] **Step 3: 最小实现**

在 `agent/sap_nexus_agent/orchestrator.py` 顶部 narrator import（line 25-30）追加 `narrate_inventory_facts`：

```python
from sap_nexus_agent.narrator import (
    NarrativeGuardError,
    narrate_fact,
    narrate_failure,
    narrate_inventory_facts,
    narrate_purchase_order_facts,
)
```

在 `expand_combinations` 之后（或 `run_query` 之后）新增 `continue_batch`：

```python
def continue_batch(
    call_plan: CallPlan,
    combinations: list[dict[str, str]],
    gateway: GatewayClientProtocol,
    *,
    decision: MatchDecision | None = None,
) -> AgentOutcome:
    """Execute a confirmed multi-value batch (Design Doc §4.4).

    Per combination: validate -> execute -> build_availability_fact.
    Partial failures are annotated, not global. All-failed -> failure outcome.
    READ-only: no approval flow (analogous to continue_action but without
    ApprovalRecord).
    """
    facts: list[ReasoningFact] = []
    failures: list[dict] = []
    for combo in combinations:
        validation = gateway.validate(call_plan.capability_id, combo)
        if not validation.success:
            failures.append({"parameters": combo, "error": validation.error_type})
            continue
        execution = gateway.execute(call_plan.capability_id, combo)
        if not execution.success:
            failures.append({"parameters": combo, "error": execution.error_type})
            continue
        fact = build_availability_fact(call_plan.agent_trace_id, execution, combo)
        if fact is not None:
            facts.append(fact)

    if not facts and failures:
        return AgentOutcome(
            status="failure",
            message="全部组合查询失败",
            response_text=narrate_failure(failures[0]["error"], []),
            call_plan=call_plan,
            error_type=failures[0]["error"],
            facts=[],
            match_decision=decision,
        )

    try:
        response_text = narrate_inventory_facts(facts, failures=failures)
    except NarrativeGuardError:
        response_text = "批量查询完成，但部分结果缺少可叙事字段。"

    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        facts=facts,
        match_decision=decision,
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_orchestrator.py -v`
Expected: 全部 PASS（含新测试 + 既有回归）

- [ ] **Step 5: 提交**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/tests/test_orchestrator.py
git commit -m "feat(orchestrator): add continue_batch for confirmed multi-value execution"
```

---

## Task 11: `openspec validate` + pytest 回归

**Files:**
- 无源码改动；验证 Task 1-10 的产物一致性

**Interfaces:**
- Consumes: Task 1-10 全部
- Produces: 验证报告（openspec strict 通过 + pytest 全绿）

- [ ] **Step 1: 运行 openspec validate**

Run: `openspec list --json && openspec validate --all --strict`
Expected: `sap-nexus-agent-llm-intent-enhancement` 列出；validate 全部 PASS（无 schema 错误）

- [ ] **Step 2: 运行 pytest 全量回归**

Run: `cd agent && python -m pytest tests/ -v`
Expected: 全部 PASS。重点检查：
- 指代解析（Task 1/4）：`test_messages_injects_last_context_block`、`test_rule_fallback_inherits_material_on_primary_keyword`
- LLM 为主（Task 2）：`test_parse_with_hybrid_uses_llm_result_directly`、`test_parse_with_hybrid_empty_llm_return_does_not_invoke_rule`
- 空返回 CLARIFY（Task 3）：`test_select_emits_clarify_when_llm_clarification_present`
- 多值（Task 5-8）：`test_payload_parses_multi_parameters`、`test_select_satisfied_by_multi_parameters`、`test_run_query_multi_value_emits_awaiting_batch_confirm`、`test_run_query_multi_value_over_cap_emits_clarify`
- 批量（Task 9-10）：`test_narrate_inventory_facts_*`、`test_continue_batch_*`
- LLM 不可用兜底（Task 2/4）：`test_parse_with_hybrid_falls_back_to_rule_on_llm_unavailable`
- 软上限（Task 8）：`test_run_query_multi_value_over_cap_emits_clarify`

- [ ] **Step 3: 运行 conversation_context 回归**

Run: `cd agent && python -m pytest tests/test_conversation_context.py -v`
Expected: PASS（LastContext round-trip 不变；本 change 不改 conversation_context.py）

- [ ] **Step 4: 运行 verify-agent-callplan-evidence 脚本**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: PASS（callplan 证据链完整）

- [ ] **Step 5: 提交（如有修复）**

若回归发现遗漏，按 systematic-debugging skill 修复后提交：

```bash
git add -A
git commit -m "test: regression fixes for llm-intent-enhancement"
```

若无修复，本 task 无 commit。

---

## Task 12: e2e 3 轮（SELECT -> awaiting_batch_confirm -> 批量聚合）

**Files:**
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 1-10 全部
- Produces: 3 轮端到端测试，覆盖 Design Doc §3.2 流程

- [ ] **Step 1: 写 e2e 测试**

追加到 `agent/tests/test_orchestrator.py`：

```python
from sap_nexus_agent.conversation_context import ConversationContext, LastContext


def test_e2e_three_turn_multi_value_batch():
    """Design Doc §3.2 / tasks.md 5.3 e2e 3 轮。

    Turn 1: "DEMOA2 在 5100 的库存" -> SELECT -> success -> last_context
    Turn 2: "这个物料在5200、1000的库存分别是多少" -> awaiting_batch_confirm
    Turn 3: 用户确认 -> continue_batch -> 批量结果
    """

    # --- Turn 1: 单值 SELECT ---
    def turn1_adapter(text, context=None):
        return IntentParseResult(
            intent=None,
            parameters={"material": "DEMOA2", "plant": "5100", "unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "plant": "5100", "unit": "EA"},
                missing=[],
            )],
            multi_parameters={},
        )

    gw1 = FakeGatewayClient(execution=ExecutionResult(
        trace_id="gw-t1", capability_id="MM.Inventory.GetAvailability",
        success=True, executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
        return_messages=[],
        data={"availableQuantity": 200, "unit": "EA", "material": "DEMOA2", "plant": "5100"},
        duration_ms=5, error_type="NONE",
    ))
    outcome1 = run_query("DEMOA2 在 5100 的库存", gw1, intent_adapter=turn1_adapter)
    assert outcome1.status == "success"
    assert outcome1.fact is not None
    assert outcome1.fact.material == "DEMOA2"
    # 构造 last_context（workbench 层职责，此处模拟）
    last_context = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "5100"},
        missing_parameters=[],
        decision_type="SELECT",
    )

    # --- Turn 2: 多值 awaiting_batch_confirm ---
    def turn2_adapter(text, context=None):
        # 模拟 LLM 解析"这个物料"=last_context material + 多 plant
        return IntentParseResult(
            intent=None,
            parameters={"material": "DEMOA2", "unit": "EA"},
            missing_parameters=[],
            capability_id="MM.Inventory.GetAvailability",
            matched_intents=[MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "unit": "EA"},
                missing=[],
            )],
            multi_parameters={"plant": ["5200", "1000"]},
        )

    gw2 = FakeGatewayClient()  # Turn 2 不应触达 Gateway
    ctx2 = ConversationContext(last_context=last_context, history=None)
    outcome2 = run_query(
        "这个物料在5200、1000的库存分别是多少", gw2,
        intent_adapter=turn2_adapter, context=ctx2,
    )
    assert outcome2.status == "awaiting_batch_confirm"
    assert outcome2.combinations is not None
    assert len(outcome2.combinations) == 2
    assert gw2.validate_calls == []
    assert gw2.execute_calls == []
    assert outcome2.call_plan is not None

    # --- Turn 3: 用户确认 -> continue_batch ---
    gw3 = _BatchFakeGateway({
        ("DEMOA2", "5200"): _exec_ok("DEMOA2", "5200", 176),
        ("DEMOA2", "1000"): _exec_ok("DEMOA2", "1000", 0),
    })
    outcome3 = continue_batch(outcome2.call_plan, outcome2.combinations, gw3)
    assert outcome3.status == "success"
    assert outcome3.facts is not None
    assert len(outcome3.facts) == 2
    # 聚合 narrative 含两个工厂结果
    assert "5200" in outcome3.response_text
    assert "176" in outcome3.response_text
    assert "1000" in outcome3.response_text
    assert "0" in outcome3.response_text
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_orchestrator.py::test_e2e_three_turn_multi_value_batch -v`
Expected: 若 Task 1-10 全部完成，应 PASS。若失败，按 systematic-debugging 定位（常见：`_BatchFakeGateway` / `_exec_ok` helper 未在本文件定义 -- 确保已由 Task 10 测试引入）。

- [ ] **Step 3: 验证通过**

Run: `cd agent && python -m pytest tests/test_orchestrator.py::test_e2e_three_turn_multi_value_batch -v`
Expected: PASS

- [ ] **Step 4: 运行全量回归确认无副作用**

Run: `cd agent && python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add agent/tests/test_orchestrator.py
git commit -m "test(orchestrator): e2e 3-turn multi-value batch (SELECT -> awaiting_batch_confirm -> continue_batch)"
```

---

## Self-Review 清单

**Spec coverage**（spec.md 场景 -> task）：
- `Route single inventory intent to SELECT` -> 既有路径（Task 8 单值回归测试覆盖）
- `Route single purchase order intent to SELECT` -> 既有路径（不改）
- `Multi-goal utterance escalates to planner` -> 既有路径（不改）
- `LLM resolves anaphora via last_context` -> Task 1（_messages 注入）+ Task 12 e2e Turn 2
- `Rule fallback inherits material on primary keyword` -> Task 4
- `LLM empty return emits CLARIFY` -> Task 3
- `Multi-value parameter emits SELECT with multi_parameters` -> Task 5 + Task 6
- `Multi-value query emits awaiting_batch_confirm` -> Task 7 + Task 8 + Task 12 Turn 2
- `Confirmed multi-value batch executes and aggregates` -> Task 10 + Task 12 Turn 3
- `Multi-value partial failure` -> Task 10（`test_continue_batch_partial_failure`）
- `Multi-value combination cap` -> Task 8（`test_run_query_multi_value_over_cap_emits_clarify`）

**tasks.md 5 section 覆盖**：
- Section 1（_messages last_context）-> Task 1
- Section 2（LLM 为主 + 空返回 CLARIFY）-> Task 2 + Task 3
- Section 3（resolve_with_context 继承 material）-> Task 4
- Section 4（多值 + 确认 + 批量 + 软上限）-> Task 5-10
- Section 5（验证）-> Task 11 + Task 12

**类型一致性**：
- `multi_parameters: dict[str, list[str]]` 在 Task 5（IntentParseResult）-> Task 6（selector）-> Task 7（expand_combinations 入参）-> Task 8（run_query 读取）全链路一致
- `combinations: list[dict[str, str]]` 在 Task 7（AgentOutcome）-> Task 8（awaiting_batch_confirm 填充）-> Task 10（continue_batch 入参）-> Task 12（e2e 传递）全链路一致
- `expand_combinations(base, multi)` 签名在 Task 7 定义、Task 8 调用一致
- `continue_batch(call_plan, combinations, gateway, *, decision=None)` 签名在 Task 10 定义、Task 12 调用一致
- `narrate_inventory_facts(facts, *, failures=None, client=None)` 签名在 Task 9 定义、Task 10 调用一致

**无 placeholder**：所有 step 含完整代码 / 完整命令 / 预期输出。

---

## 执行交接

**计划已保存至 `docs/superpowers/plans/2026-07-26-sap-nexus-llm-intent-enhancement.md`。两种执行方式：**

**1. Subagent-Driven（推荐）** - 每个 task 派发独立 subagent，task 间审查，快速迭代

**2. Inline Execution** - 在当前会话用 executing-plans 批量执行，检查点审查

**请选择执行方式。**

> 若选 Subagent-Driven：REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`，每 task 一个 fresh subagent + 两阶段审查。
> 若选 Inline：REQUIRED SUB-SKILL: `superpowers:executing-plans`，批量执行 + 检查点。

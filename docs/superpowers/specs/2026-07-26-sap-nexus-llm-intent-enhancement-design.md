---
comet_change: sap-nexus-agent-llm-intent-enhancement
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-27-sap-nexus-agent-llm-intent-enhancement
status: final
---

# LLM 意图识别增强 + 多值批量查询 Design Doc

> Canonical capability spec: `openspec/changes/sap-nexus-agent-llm-intent-enhancement/specs/agent-callplan-evidence/spec.md`。本文件是技术设计细化，不重复需求 spec。

## 1. Context

当前 `parse_with_hybrid` 先 LLM，但 `_messages` 不用 `last_context`，LLM 不稳定时 fallback rule（不继承 last_context），含主关键词走新轮丢失 material。多值查询（多工厂/多物料）只提取第一个。架构文档 §4.2.2 定义了 `ConversationState`（last_context），但 LLM 路径未集成。

本 change 补：LLM last_context 集成 + LLM 为主 + 多值参数（通用）+ 确认后批量执行 + 聚合。

## 2. Goals / Non-Goals

**Goals**
- LLM 稳定理解指代（"这个物料" -> 上轮 material）。
- 多值参数查询（`material` + `plant` 同时多值，通用抽象支持任意参数）。
- 多值组合先确认再批量执行，聚合结果。
- LLM 为主，rule 仅连接失败兜底。

**Non-Goals**
- DeerFlow runtime / closed-set 契约变更 / P0B / spawn 模型。
- 单 plant capability 契约变更（`MM.Inventory.GetAvailability` 仍单 plant）。
- WRITE 能力批量（`continue_batch` 仅 READ；Action 批量审批语义后续单独设计）。
- 组合结果分页/流式（预留扩展点，本 change 不实现）。

## 3. Architecture & Data Flow

### 3.1 指代解析流（单值）

```
Turn N: "DEMOA2 在 5100..."
  -> intent_adapter(text, context=None)
  -> parse_with_hybrid -> parse_with_llm -> _messages(无 last_context)
  -> SELECT(material=DEMOA2, plant=5100)
  -> execute -> fact -> narrate_fact
  -> last_context = SELECT(inventory, {material:DEMOA2, plant:5100})

Turn N+1: "这个物料在1000的库存"
  -> intent_adapter(text, context={last_context, history})
  -> parse_with_hybrid -> parse_with_llm -> _messages(注入 last_context)
  -> LLM 解析"这个物料"=DEMOA2 (来自 last_context) + plant=1000
  -> SELECT(material=DEMOA2, plant=1000)
```

### 3.2 多值批量流（两轮确认）

```
Turn N: "DEMOA2 和 DEMOA4 在 5200、1000 的库存"
  -> parse_with_llm -> multi_parameters={plant:[5200,1000], material:[DEMOA2,DEMOA4]}
  -> select_capability -> SELECT (参数齐全: plant/material 在 multi_parameters)
  -> orchestrator 检测 multi_parameters 非空
  -> expand_combinations -> 4 组合 (2 material × 2 plant)
  -> 软上限检查 (4 < 20, 通过)
  -> AgentOutcome(status="awaiting_batch_confirm", combinations=[4 组合])
  -> workbench 展示 "将查询 4 个组合：..." + 确认按钮
  [不执行 Gateway]

Turn N+1: 用户点确认
  -> workbench 调 continue_batch(call_plan, combinations, gateway)
  -> 逐组合 validate+execute (4 次)
  -> 4 个 ReasoningFact
  -> narrate_inventory_facts(facts) -> "物料 DEMOA2 在工厂 5200 为 176 EA；..."
  -> AgentOutcome(status="success", facts=[4], response_text=聚合 narrative)
```

## 4. Component Changes

### 4.1 `llm_intent.py`

**D1 - `_messages` 注入 last_context**

新增 last_context 数据块（与 history_block 同级，均为 data）：

```python
def _messages(text, catalog, *, context=None):
    ...
    blocks = []
    if context is not None:
        if context.last_context is not None:
            blocks.append(_format_last_context_block(context.last_context))
        if context.history:
            blocks.append(_format_history_block(context.history[-6:]))
    if blocks:
        return [authority, *blocks, base_system, base_user]
    return [base_system, base_user]

def _format_last_context_block(lc: LastContext) -> dict:
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

- last_context 与 history 同为 `<durable_context_data>` data，受 `_AUTHORITY_CONTRACT` 约束（capabilityId 必须来自当前输入+闭集，不可从 data 注入）。

**D2 - `parse_with_hybrid` LLM 为主**

```python
def parse_with_hybrid(text, client=None, *, catalog=None, context=None):
    if catalog is None:
        catalog = load_intent_catalog()
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        return parse_with_llm(text, llm_client, catalog, context=context)  # 直接用
    except LlmUnavailable:
        return parse_intent(text, context=context)  # 仅连接失败兜底
```

- 移除 `_requires_safe_fallback` -> rule 回退分支。`_requires_safe_fallback` 函数可保留（供 `_parse_llm_only` 等内部判定）或删除（按调用点决定，build 阶段确认）。

**Q3 - LLM 空返回 -> CLARIFY**

`_payload_to_parse_result`：当 LLM payload 无 capability（单 capabilityId 路径 + 多 candidate 路径都未命中）时，返回带 `clarification` 的空结果：

```python
# 原各处 return IntentParseResult(intent=None, parameters={}, missing_parameters=[])
# 改为携带 generic clarification:
return IntentParseResult(
    intent=None, parameters={}, missing_parameters=[],
    clarification="无法识别查询意图，请明确物料、工厂等信息",
)
```

`select_capability` 第 6 步 REJECT 前增加 clarification 判断：

```python
# 6. No match -> REJECT(UNSUPPORTED_INTENT).  但 LLM 提供 clarification 时发 CLARIFY。
if parse_result.clarification and not parse_result.capability_id:
    return MatchDecision(
        decision_type="CLARIFY",
        capability_id=None,
        parameters={},
        missing_parameters=[],
        rationale=parse_result.clarification,
    )
return MatchDecision(decision_type="REJECT", error_type="UNSUPPORTED_INTENT", ...)
```

- 注意：rule 兜底路径（`parse_intent`）的空返回不带 clarification，仍走 REJECT（保持 rule 路径原语义）。只有 LLM 路径的空返回带 clarification -> CLARIFY。

**D3 - `resolve_with_context` 主关键词继承 material**

```python
if _contains_any_primary_keyword(text):
    parsed = parse_intent(text)
    if (
        "material" not in parsed.parameters
        and context.last_context.parameters.get("material")
    ):
        parsed.parameters["material"] = context.last_context.parameters["material"]
    return parsed
```

- 仅 LLM 不可用 rule 兜底时生效（D2）。LLM 正常时 D1 解决指代。

**多值 payload 解析**

`_payload_to_parse_result` 读取 `multiParameters`：

```python
raw_multi = payload.get("multiParameters") or {}
multi_parameters = {
    str(k): [str(v) for v in vals]
    for k, vals in raw_multi.items()
    if isinstance(vals, list)
}
```

- 填入 `IntentParseResult.multi_parameters`。闭集防御照旧（capabilityId 必须在闭集）。

**LLM prompt 指引**

`_messages` base_system 增加通用多值指引（不枚举参数名）：

> "若用户在某个参数上提及多个值（如多个工厂、多个物料），将该参数放入 `multiParameters` 数组，不要放入 `parameters`。单值参数仍放 `parameters`。"

### 4.2 `intent.py`

- `IntentParseResult` 新增字段 `multi_parameters: dict[str, list[str]] = field(default_factory=dict)`。
- `parse_intent` 签名不变（已有 `context` 参数）。

### 4.3 `capability_selector.py`

- **5 态不变**。
- `missing_parameters` 判定：required 参数在 `parameters` 或 `multi_parameters` 中即算齐全：

```python
provided = set(parse_result.parameters.keys()) | set(parse_result.multi_parameters.keys())
missing = [inp.name for inp in descriptor.inputs if inp.required and inp.name not in provided]
```

- SELECT 分支：`parameters=dict(parse_result.parameters)`（不含 multi_parameters；orchestrator 从 `parsed` 读 multi_parameters）。

### 4.4 `orchestrator.py`

**`run_query` SELECT 分支 - 多值检测**

```python
# SELECT -> CallPlan -> ...
capability_id = decision.capability_id
parameters = dict(decision.parameters or parsed.parameters)
if capability_id == INVENTORY_CAPABILITY_ID:
    parameters.setdefault("unit", "EA")

if parsed.multi_parameters:
    combinations = expand_combinations(parameters, parsed.multi_parameters)
    if len(combinations) > BATCH_COMBINATION_CAP:
        return AgentOutcome(
            status="clarification",
            response_text=f"组合数 {len(combinations)} 过多，请缩小范围（如减少物料或工厂）。",
            match_decision=decision,
        )
    return AgentOutcome(
        status="awaiting_batch_confirm",
        response_text=f"将查询 {len(combinations)} 个组合：{format_combinations(combinations)}，请确认。",
        call_plan=create_call_plan(capability_id, parameters, kind=kind),
        combinations=combinations,
        match_decision=decision,
    )

# 原单次 execute 路径不变
```

**`expand_combinations`**

```python
import itertools

def expand_combinations(base: dict[str, str], multi: dict[str, list[str]]) -> list[dict[str, str]]:
    keys = list(multi.keys())
    value_lists = [multi[k] for k in keys]
    combos = []
    for values in itertools.product(*value_lists):
        combo = dict(base)
        combo.update(dict(zip(keys, values)))
        combos.append(combo)
    return combos
```

- 笛卡尔积，与能力/参数名无关（通用）。

**`continue_batch`**（类比 `continue_action`）

```python
def continue_batch(
    call_plan: CallPlan,
    combinations: list[dict[str, str]],
    gateway: GatewayClientProtocol,
    *,
    decision: MatchDecision | None = None,
) -> AgentOutcome:
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
        if fact:
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
    response_text = narrate_inventory_facts(facts, failures=failures)
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        facts=facts,
        match_decision=decision,
    )
```

- 逐组合 validate+execute；部分失败 -> 成功 fact + failure 标注，不全局失败（除非全失败）。
- 仅 READ capability（`MM.Inventory.GetAvailability`）。

**`AgentOutcome` 新增字段**

```python
combinations: list[dict[str, str]] | None = None  # awaiting_batch_confirm 时携带
```

**常量**

```python
BATCH_COMBINATION_CAP = 20  # 软上限，超出发 CLARIFY
```

### 4.5 `narrator.py`

**`narrate_inventory_facts`**（镜像 `narrate_purchase_order_facts`）

```python
def narrate_inventory_facts(
    facts: list[ReasoningFact],
    *,
    failures: list[dict] | None = None,
    client=None,
) -> str:
    if not facts and not failures:
        return "无匹配记录。"
    # guard: 每个 fact 需 material/plant/value/unit
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

- 模板兜底 `_template_inventory_batch`：
  - 多物料：`"物料 DEMOA2 在工厂 5200 为 176 EA；物料 DEMOA2 在工厂 1000 为 0 EA；..."`
  - 单物料：`"在工厂 5200 为 176 EA；在工厂 1000 为 0 EA"`（对齐 spec "5200: 176 EA; 1000: 0 EA"）
  - 部分失败：追加 `"工厂 Z 查询失败。"`

### 4.6 `conversation_context.py`

- 不改。`multi_parameters` 在 IntentParseResult，不在 ConversationContext。`LastContext` 不变（携带单值 capability+parameters）。

## 5. Error Handling

| 场景 | 处理 |
|------|------|
| LLM 连接失败 | `LlmUnavailable` -> rule 兜底 `parse_intent(text, context=context)`（含 D3 继承） |
| LLM 返回空/无 capability | Q3 -> CLARIFY "请明确物料、工厂等信息" |
| LLM 返回 rfcName/OData 注入 | `_payload_to_parse_result` 闭集防御 -> REJECT |
| 多值组合超过软上限 | `awaiting_batch_confirm` 前 -> CLARIFY "组合数过多，请缩小范围" |
| 批量部分失败 | `continue_batch` -> 成功 fact + 失败标注，不全局失败 |
| 批量全失败 | `continue_batch` -> failure outcome |
| 用户未确认改问新问题 | 新 Turn 走 `run_query`（last_context 正常流转），combinations 由前端丢弃 |

## 6. Testing Strategy

| 文件 | 用例 |
|------|------|
| `test_llm_intent.py` | D1: `_messages` 含 last_context 块；指代解析（Turn2 "这个物料" + last_context -> SELECT 继承 material）。D2: LLM 有效直接用（mock rule 不调用）；空返回 -> CLARIFY；`LlmUnavailable` -> rule 兜底。多值: `_payload_to_parse_result` 解析 `multiParameters`。 |
| `test_intent.py` | D3: rule 兜底+主关键词+无 material+last_context 有 -> 继承；有新 material -> 不继承。 |
| `test_orchestrator.py` | `expand_combinations` 单 key/多 key 笛卡尔积；`run_query` 多值 -> `awaiting_batch_confirm`（不 execute）；软上限 -> CLARIFY；`continue_batch` 全成功/部分失败/全失败；单值回归。 |
| `test_narrator.py`（或现有） | `narrate_inventory_facts` 多 fact/多物料/部分失败/模板兜底。 |
| `test_conversation_context.py` | LastContext round-trip 回归。 |
| e2e（task 5.3，3 轮） | Turn1 "DEMOA2 在 5100..." -> SELECT；Turn2 "这个物料在5200、1000的库存" -> `awaiting_batch_confirm`；Turn3 确认 -> 批量结果 "5200: 176 EA; 1000: 0 EA"。 |

## 7. Spec Patch 摘要

回写 `specs/agent-callplan-evidence/spec.md`：

- **Closed-set capability selection（MODIFIED）**：补 Q3 空返回 CLARIFY；补 `multi_parameters` 契约（任意参数多值 -> `multiParameters` 数组；selector 视 multi_parameters 满足 required；SELECT 继续）。新增场景：`LLM empty return emits CLARIFY`、`Multi-value parameter emits SELECT with multi_parameters`。
- **Multi-plant query split -> Multi-value query split（ADDED，泛化）**：静默拆分改写为 "expand combinations -> awaiting_batch_confirm -> 用户确认后 continue_batch 执行 + 聚合"；含软上限。场景：`Multi-value query emits awaiting_batch_confirm`、`Confirmed multi-value batch executes and aggregates`（material×plant）、`Multi-value partial failure`、`Multi-value combination cap`。

## 8. Risks & Trade-offs

- **LLM 为主不再 rule 纠正**：LLM 错误时无 rule 兜底纠正；Q3 CLARIFY 缓解 UX。可接受（DeerFlow 理念：LLM 有完整上下文）。
- **方案 B SELECT 不总执行**：orchestrator 拦截多值 -> awaiting_batch_confirm。语义清晰（与 Action 审批同构）。
- **组合爆炸**：material×plant 笛卡尔积可能大。三层保护：确认步骤 + 软上限（20）+ 不硬编码组合数。超上限 CLARIFY。
- **跨轮状态在前端**：combinations 由前端持有（类比 approval_record）。无服务端状态（读无状态）。
- **last_context 注入安全**：复用 `_AUTHORITY_CONTRACT`，data 不可注入指令。

## 9. Future Extension Points

- **新能力多值**：`multi_parameters` 通用，LLM prompt 通用指引，`expand_combinations` 与能力无关。新能力注册即支持多值，无需改核心。
- **narrator 新能力**：按 `businessObject` 派生指引（类比 `narration_guidance`），新能力补模板。
- **组合分页/流式**：`expand_combinations` / `narrate_inventory_facts` 不硬编码组合数，预留分页扩展。
- **WRITE 批量**：`continue_batch` 仅 READ；WRITE 批量须单独设计审批语义（每组合审批 or 批量审批）。
- **软上限可配置**：`BATCH_COMBINATION_CAP` 常量，后续可改配置项。


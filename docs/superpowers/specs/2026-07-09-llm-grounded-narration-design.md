---
comet_change: llm-grounded-narration
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-09-llm-grounded-narration
status: final
---

# LLM-Grounded Flexible Narration - Technical Design

## 1. 背景与目标

### 1.1 问题

当前 narrator（`narrator.py`）是纯模板拼接：inventory 用 `f"物料 {material} 在工厂 {plant} 的可用库存为 {value} {unit}。"`，PO 逐条 `f"采购订单 {po}：供应商 {supplier}，..."`。不调 LLM，格式固定，每新增场景需硬编码模板分支。LLM 已就绪（DeepSeek 网关），未用于叙事。

### 1.2 目标

事实化与叙事结合 LLM：基于 ReasoningFact 字段 + capability 元数据用 LLM 生成结构化中文叙事；柔性架构--新增能力场景叙事由 capability 元数据派生指引，无需硬编码模板；防幻觉（spec「只能用 fact 字段、不得编造」）。

### 1.3 非目标

不改 fact builder / registry schema / OData service / 前端 / 意图识别 / LLM 认证机制。不做多轮叙事上下文、非 SAP 业务叙事。

## 2. 架构与数据流

```
orchestrator._finalize_inventory / _finalize_purchase_order
  │  传 capability_id（inventory）/ 默认 PO capability_id
  ▼
narrate_fact / narrate_purchase_order_facts
  ├─ 空列表 -> 模板「无匹配记录。」（不调 LLM）
  ├─ LLM 主路径:
  │    ├─ load_intent_catalog() 查 descriptor
  │    ├─ narration_guidance(capability_id) 按 businessObject 派生指引
  │    ├─ grounding prompt = system(严格约束不编造) + guidance + fact 字段
  │    ├─ client.chat_text(prompt) -> text
  │    └─ redact_sensitive(text) -> narrative
  └─ fallback (LLM 不可用/异常): 既有模板拼接
```

## 3. 组件设计

### 3.1 `llm_client.py` - 加 chat_text

```python
class OpenAiCompatibleLlmClient:
    def chat_text(self, messages, *, temperature=0.0, max_tokens=400) -> str:
        # 复用 chat_json 的请求/重试/超时逻辑，返回 choices[0].message.content (str)
        # LlmUnavailable 同 chat_json
```

`JsonLlmClient` Protocol 不含 chat_text（narrator 用具体类型或单独 Protocol）。测试用 fake client 实现 chat_text。

### 3.2 `narrator.py` - 柔性指引派生

```python
def narration_guidance(capability_id: str) -> str:
    """按 businessObject 派生叙事指引；未知能力用通用 fact-based 指引。"""
    catalog = load_intent_catalog()
    descriptor = catalog.find(capability_id)
    business_object = descriptor.business_object if descriptor else ""
    if business_object == "InventoryStock":
        return _INVENTORY_GUIDANCE  # 库存单值结论指引
    if business_object == "PurchaseOrder":
        return _PO_GUIDANCE  # 订单列表归纳指引
    return _GENERIC_GUIDANCE  # 通用：基于 fact 字段自然语言陈述
```

指引常量示例：
- `_INVENTORY_GUIDANCE`：「用给定物料的可用库存事实生成一句中文结论，说明物料在工厂的可用库存量与单位。」
- `_PO_GUIDANCE`：「用给定的采购订单条目事实生成中文归纳，列出关键订单（采购订单号、供应商、物料、工厂、数量、单位），多条时归纳总结。」
- `_GENERIC_GUIDANCE`：「用给定事实字段的值生成自然语言中文陈述，只陈述字段中存在的数据。」

### 3.3 `narrator.py` - LLM 主路径 + fallback

```python
_SYSTEM_CONSTRAINT = (
    "你是一个 SAP 业务结论叙事器。只能使用下方提供的事实字段及其值生成中文叙事，"
    "不得编造任何记录、数值或字段，不得猜测，不得添加未提供的信息，"
    "不得输出 SAP 表名、BAPI/RFC 名或凭据。"
)

def narrate_fact(fact, *, capability_id="MM.Inventory.GetAvailability", client=None) -> str:
    # fact 字段不足 -> 模板 fallback（既有 guard）
    missing = [...]  # 既有检查
    if missing:
        # 模板路径会因缺字段失败，直接走 LLM 也无法 grounding；抛 guard 或模板
        raise NarrativeGuardError(...)  # 保持既有行为
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(_build_messages(fact, capability_id), temperature=0.0, max_tokens=200)
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_inventory(fact)  # 既有模板拼接

def narrate_purchase_order_facts(facts, *, total_count=None, client=None) -> str:
    if not facts:
        return "无匹配记录。"  # 空列表不调 LLM
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        text = llm_client.chat_text(_build_po_messages(facts, total_count), temperature=0.0, max_tokens=400)
        return redact_sensitive(text.strip())
    except LlmUnavailable:
        return _template_po(facts, total_count)  # 既有逐条模板拼接
```

`_build_messages` / `_build_po_messages`：system（`_SYSTEM_CONSTRAINT`）+ guidance + user（fact 字段 JSON/结构化文本）。

模板 fallback 函数 `_template_inventory` / `_template_po` 即既有拼接逻辑，提取保留。

### 3.4 `orchestrator.py` - 传 capability_id

`_finalize_inventory` 调 `narrate_fact(fact, capability_id="MM.Inventory.GetAvailability")`（默认值已是该值，显式传清晰）。`_finalize_purchase_order` 调 `narrate_purchase_order_facts(facts, total_count=...)`（capability_id 默认 PO）。orchestrator 改动最小。

## 4. 防幻觉与边界

| 场景 | 行为 |
|---|---|
| LLM 不可用 | fallback 模板拼接（deterministic） |
| LLM 编造 | prompt 严格约束 + redact；fallback 兜底 |
| fact 字段不足（inventory） | 抛 NarrativeGuardError（既有行为，不调 LLM） |
| PO fact 字段不足 | fallback 模板的既有 guard 抛错（保持） |
| 空列表 | 模板「无匹配记录。」不调 LLM |
| 未知 capability | 通用 fact-based 指引 |
| LLM 输出含敏感信息 | redact_sensitive 过滤 |
| LLM 输出异常/空 | 视为不可用 -> fallback 模板 |

**安全失败**：任何 LLM 异常降级模板，不让 agent 崩溃。

## 5. 测试策略

| 类型 | 覆盖 |
|---|---|
| LLM 叙事（fake chat_text client） | inventory 生成自然语言、PO 归纳、未知能力通用指引 |
| fallback | LLM 不可用 -> 模板拼接（inventory + PO） |
| 防幻觉 | prompt 含「不得编造」约束断言；fact 字段不足抛 guard |
| 空列表 | 直接返回「无匹配记录。」不调 LLM（断言 client 未调用） |
| redact | LLM 输出含敏感信息 -> redact_sensitive 过滤 |
| orchestrator 集成 | 注入 fake client，narrator LLM 路径全链路；现有 fallback 不破坏 |

fake client 复用 `FakeLlmClient` 模式，加 `chat_text` 返回固定文本。

## 6. 风险与取舍

- **LLM 幻觉** -> prompt 约束 + redact + fallback 模板；spec「不编造」由 fallback 兜底。
- **LLM 不可用** -> fallback 模板，降级固定格式不失败。
- **LLM 延迟** -> temperature=0 + max_tokens 限；单次调用。
- **柔性指引泛化** -> 通用 fact-based 指引兜底未知能力。
- **测试依赖 LLM** -> fake client 注入；fallback 模板用真实 fact。
- **spec 约束变化** -> delta spec 已同步（LLM grounded + fallback）。

## 7. 迁移与回滚

纯 agent 侧，无迁移：
1. 实现 chat_text + narrator LLM 路径 + 指引 + fallback。
2. 更新测试。
3. 验证全量 + 端到端。
4. 归档。

**回滚**：`git revert`。

## 8. 改动文件清单

| 文件 | 改动 |
|---|---|
| `agent/sap_nexus_agent/llm_client.py` | 加 `chat_text` |
| `agent/sap_nexus_agent/narrator.py` | LLM 主路径 + 指引派生 + 模板 fallback 提取 |
| `agent/sap_nexus_agent/orchestrator.py` | 显式传 capability_id（最小） |
| `agent/tests/test_reasoning_narrator.py` | LLM/fallback/防幻觉/空/redact 用例 |
| `agent/tests/test_orchestrator.py` | narrator LLM 集成 |


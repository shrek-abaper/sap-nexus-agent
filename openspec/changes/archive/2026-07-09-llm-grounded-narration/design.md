## Context

当前 narrator（`narrator.py`）是纯模板拼接：inventory 用 `f"物料 {material} 在工厂 {plant} 的可用库存为 {value} {unit}。"`，PO 逐条 `f"采购订单 {po}：供应商 {supplier}，物料 {material}，工厂 {plant}，数量 {qty} {unit}。"`。不调 LLM，格式固定，每新增场景需硬编码模板分支。

LLM 已就绪（DeepSeek 网关，`flexible-intent-recognition` 验证可用）。`registry_loader` 的 `IntentCatalog`/`CapabilityDescriptor` 可派生叙事指引。spec 强约束：narrative SHALL render only from fields present in ReasoningFact，does not invent records/values。

下游（orchestrator `_finalize_inventory`/`_finalize_purchase_order`）调 `narrate_fact`/`narrate_purchase_order_facts`，LLM 不可用时需 fallback 模板。

## Goals / Non-Goals

**Goals:**
- inventory + PO 叙事改用 LLM grounded 生成（基于 ReasoningFact 字段 + capability 元数据）。
- 柔性叙事架构：叙事指引按 capability 的 businessObject/capabilityId 派生，新增能力场景无需硬编码模板即有 LLM 叙事。
- 防幻觉：prompt 严格约束「只能用给定 fact 字段、不得编造记录/数值/字段」+ redact_sensitive 过滤 + LLM 不可用/fact 全无 fallback 模板。
- 保留模板路径作为 fallback（LLM 不可用、fact 字段缺失、测试注入）。

**Non-Goals:**
- 不改 fact builder（`reasoning_fact.py`，刚修过嵌套 items）。
- 不改 registry schema / OData service / 前端 / 意图识别。
- 不做多轮叙事上下文、不做非 SAP 业务叙事。
- 不改 LLM client 的认证/重试机制（仅可能加 chat_text 方法）。

## Decisions

### D1: LLM 叙事主路径 + 模板 fallback

`narrate_fact`/`narrate_purchase_order_facts` 改为：先尝试 LLM 叙事，LLM 不可用（LlmUnavailable）或 fact 字段不足以 grounding 时 fallback 既有模板拼接。模板路径保留，作为 deterministic fallback 与测试注入点。

### D2: 柔性叙事指引派生（按 capability 元数据）

新增 `narration_guidance(descriptor)` 派生叙事指引：
- 按 `descriptor.business_object` 或 `capability_id` 派生（InventoryStock -> 库存单值结论指引，PurchaseOrder -> 订单列表归纳指引）。
- 未知 business_object -> 通用 fact-based 叙事指引（列出 fact 字段 + 要求自然语言陈述）。
- 指引 + fact 字段注入 LLM prompt，LLM 生成结构化中文叙事。

柔性体现：新增 capability 只需注册（businessObject/description/outputs），叙事指引自动派生，无需模板代码。

### D3: 防幻觉三重保障

1. **prompt 约束**：system prompt 严格指令「只能用给定 fact 字段、不得编造记录或数值、不得添加未提供的字段、不得猜测」。
2. **redact_sensitive 过滤**：LLM 输出经 `redact_sensitive` 过滤敏感信息（既有函数）。
3. **fallback**：LLM 不可用 / fact 全无关键字段 / 输出异常 -> fallback 模板拼接（deterministic，不编造）。

### D4: LLM client 加 chat_text

现有 `OpenAiCompatibleLlmClient` 只有 `chat_json`。叙事是自然语言输出，加 `chat_text(messages, *, temperature, max_tokens) -> str`（复用 chat_json 的请求逻辑但返回 text）。备选：让 LLM 返回 `{"narrative": "..."}` JSON 复用 chat_json--但自然语言用 text 更直接。design 阶段定。

### D5: orchestrator 传 catalog/descriptor

orchestrator 的 `_finalize_inventory`/`_finalize_purchase_order` 调 narrator 时传 `CapabilityDescriptor`（或 narrator 内部用 capability_id 从 catalog 查）。design 阶段定接口。

## Risks / Trade-offs

- **[LLM 幻觉编造]** -> prompt 严格约束 + redact + fallback 模板；spec guard「不编造」仍由 fallback 兜底。
- **[LLM 不可用]** -> fallback 模板拼接，叙事降级为固定格式但不失败。
- **[LLM 延迟]** -> 叙事增加一次 LLM 调用；temperature=0 + 限 max_tokens 控制延迟。
- **[柔性指引对未知能力泛化差]** -> 通用 fact-based 指引兜底；特定能力（inventory/PO）有专属指引。
- **[测试依赖 LLM]** -> 测试用 fake client 注入；fallback 模板路径用真实 fact 测试。
- **[spec 约束变化]** -> 现有「模板 guard」改为「LLM grounded + fallback」；spec scenario 同步更新。

## Migration Plan

纯 agent 侧重构，无迁移：
1. 实现 narrator LLM 路径 + 指引派生 + fallback + chat_text。
2. 更新测试（fake client + fallback + 防幻觉）。
3. 验证全量 + 端到端（库存 + PO）。
4. 归档。

**回滚**：`git revert` 即可。

## Open Questions

design 阶段 brainstorming 细化：
- LLM 输出用 text 还是 JSON（`{"narrative": ...}`）？
- 叙事指引派生按 businessObject 还是 capabilityId，还是 registry 加 narrationHint 字段？
- orchestrator 传 descriptor 还是 narrator 内部加载 catalog？
- 空结果（无匹配）走 LLM 还是直接模板「无匹配记录。」？

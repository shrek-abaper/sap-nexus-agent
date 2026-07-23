# Brainstorm Summary

- Change: llm-grounded-narration
- Date: 2026-07-09

## 确认的技术方案

LLM grounded 柔性叙事：narrator 用 LLM 基于 ReasoningFact 字段 + capability 元数据生成结构化中文叙事，模板作 fallback。

### 核心架构
- `OpenAiCompatibleLlmClient` 加 `chat_text(messages, *, temperature, max_tokens) -> str`（复用 chat_json 请求逻辑返回 text）。
- `narrator.py` 新增 `narration_guidance(capability_id) -> str`：narrator 内部 `load_intent_catalog()` 查 descriptor，按 `businessObject` 派生指引（InventoryStock -> 库存单值结论指引，PurchaseOrder -> 订单列表归纳指引，未知 -> 通用 fact-based 指引）。
- LLM 叙事主路径：grounding prompt = system（严格约束「只能用给定 fact 字段、不得编造记录/数值/字段、不得猜测」）+ guidance + fact 字段；LLM 输出经 `redact_sensitive` 过滤。
- 模板 fallback：LLM 不可用（LlmUnavailable）或异常 -> 既有模板拼接（deterministic）。
- 空结果：fact 列表为空直接返回「无匹配记录。」模板，不调 LLM。

### narrator 接口
- `narrate_fact(fact, *, capability_id="MM.Inventory.GetAvailability", client=None) -> str`：LLM 主路径 + 模板 fallback。
- `narrate_purchase_order_facts(facts, *, total_count=None, client=None) -> str`：空列表模板直接返回；非空 LLM 主路径 + 模板 fallback。
- narrator 内部加载 catalog 派生 guidance，orchestrator 只传 capability_id（inventory）或用默认 PO capability_id。

### 防幻觉三重保障
1. prompt 严格约束（只能用 fact 字段、不得编造记录/数值/字段、不得猜测）。
2. 输出 `redact_sensitive` 过滤。
3. LLM 不可用/异常 fallback 模板（deterministic 不编造）。

## 关键取舍与风险

- **[LLM 幻觉编造]** -> prompt 严格约束 + redact + fallback 模板；spec guard「不编造」由 fallback 兜底。
- **[LLM 不可用]** -> fallback 模板拼接，叙事降级固定格式但不失败。
- **[LLM 延迟]** -> temperature=0 + 限 max_tokens；单次调用。
- **[柔性指引对未知能力泛化差]** -> 通用 fact-based 指引兜底；inventory/PO 有专属指引。
- **[测试依赖 LLM]** -> fake chat_text client 注入；fallback 模板路径用真实 fact 测试。
- **[spec 约束变化]** -> 「模板 guard」改为「LLM grounded + fallback」；spec scenario 同步（已写 delta）。

## 测试策略

- `test_reasoning_narrator.py` 更新：LLM 叙事用例（fake chat_text client：inventory + PO + 未知能力）、fallback 用例（LLM 不可用 -> 模板）、防幻觉约束用例（prompt 含「不得编造」）、空列表用例、redact 过滤用例。
- `test_orchestrator.py` 更新：narrator LLM 路径集成（注入 fake client），现有 fallback 用例不破坏。
- 验证：pytest + evals（inventory + PO）+ openspec + verify 脚本 + 端到端 CLI（库存 + PO 返回 LLM 自然语言结论）。

## Spec Patch

无额外 patch。delta spec 已覆盖：ADDED「LLM-grounded flexible narration」（5 scenarios：inventory/PO/新能力/fallback/空结果）+ MODIFIED「Chinese narration from facts only」「List execution result to reasoning facts」（叙事方式改 LLM grounded + fallback）。

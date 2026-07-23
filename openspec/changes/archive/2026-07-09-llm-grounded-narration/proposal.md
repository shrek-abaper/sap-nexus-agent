## Why

当前 narrator 是纯模板拼接（`f"物料 {material} 在工厂 {plant} 的可用库存为 {value} {unit}。"` / PO 逐条拼接），不调用 LLM。问题：

- 叙事生硬、固定格式，无法根据数据特征（如多记录归纳、单值结论、空结果、异常）生成自然流畅的中文结论。
- 每新增一个能力场景都要在 narrator 硬编码模板分支，扩展性差。
- 未利用已就绪的 LLM 能力（DeepSeek 网关，`flexible-intent-recognition` 已验证可用）做结构化叙事。

需求：事实化与叙事结合 LLM，基于能力拿到的数据（ReasoningFact）用 LLM 进行结构化叙事，且要考虑扩展性--后续新增场景叙事都走 LLM 结构化输出，不再硬编码模板。

## What Changes

- 重构 `agent/sap_nexus_agent/narrator.py`：叙事改用 LLM grounded 生成，prompt 从 ReasoningFact 字段 + capability 元数据动态构造，LLM 输出结构化中文叙事。
- 柔性叙事架构：叙事 prompt 按 capability 的 `businessObject`/`capabilityId` 派生叙事指引（inventory -> 库存单值结论指引，PO -> 订单列表归纳指引，未来新能力 -> 通用 fact-based 叙事指引），新增能力只需注册即有 LLM 叙事（零模板代码）。
- 防幻觉（spec 约束「只能用 fact 字段、不得编造记录/数值」）：prompt 严格约束「只能用给定 fact 字段、不得编造记录或数值、不得添加未提供字段」+ 输出经 `redact_sensitive` 过滤 + fact 全无时模板 fallback + LLM 不可用时 fallback 既有模板拼接。
- inventory 与 PO 两种既有叙事都改走 LLM；保留模板路径作为 fallback。
- 复用 `registry_loader` 的 `IntentCatalog`/`CapabilityDescriptor` 派生叙事指引（避免重复读 registry）。
- 同步 spec：现有「模板拼接 guard」requirement 改为「LLM 叙事 grounded on fact 字段 + fallback」。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `agent-callplan-evidence`: 叙事从纯模板拼接改为 LLM grounded 生成--LLM 基于 ReasoningFact 字段 + capability 元数据生成结构化中文叙事，prompt 严格约束不得编造记录/数值/字段，LLM 不可用或 fact 全无时 fallback 模板拼接；新增能力场景的叙事由 capability 元数据派生指引，无需硬编码模板。

## Impact

- Agent 代码（Python）：
  - 重构 `agent/sap_nexus_agent/narrator.py`（LLM 叙事主路径 + 模板 fallback + 柔性指引派生）
  - 可能新增 `agent/sap_nexus_agent/narrator_prompt.py` 或在 narrator 内组织指引派生（视 design）
  - `agent/sap_nexus_agent/orchestrator.py` 微调（传 catalog/descriptor 给 narrator，或 narrator 内部加载）
  - `agent/sap_nexus_agent/llm_client.py` 可能加 `chat_text`（现有只有 `chat_json`）--视 design 决定
- 测试：
  - 更新 `agent/tests/test_reasoning_narrator.py`（LLM 叙事用例 + fallback 用例 + 防幻觉约束用例）
  - 更新 `agent/tests/test_orchestrator.py`（narrator LLM 路径集成）
- 不改 registry schema / OData service / 前端事件流 / 意图识别 / fact builder。
- 依赖：无新增（复用现有 LLM client + registry_loader）。
- 验证：`pytest agent/tests` + evals + `openspec validate --all --strict` + `verify-agent-callplan-evidence.sh` 通过；端到端 CLI 库存 + PO 查询返回 LLM 生成的自然语言结论。

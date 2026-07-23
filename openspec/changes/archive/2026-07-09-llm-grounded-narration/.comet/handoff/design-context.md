# Comet Design Handoff

- Change: llm-grounded-narration
- Phase: design
- Mode: compact
- Context hash: 0668ebf25cae8664c5067781a722fd2a4184c570293f0eb207e27113af27532e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/llm-grounded-narration/proposal.md

- Source: openspec/changes/llm-grounded-narration/proposal.md
- Lines: 1-42
- SHA256: db67b4671554064ff6a5dd035f1fab34eb4eb2874693e9f48b8bd05da1c0bfaf

```md
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

```

## openspec/changes/llm-grounded-narration/design.md

- Source: openspec/changes/llm-grounded-narration/design.md
- Lines: 1-77
- SHA256: 9e7d416c374d3704fb7929a8f343751f48d41e9fdc0ce840322520efb5d71639

```md
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

```

## openspec/changes/llm-grounded-narration/tasks.md

- Source: openspec/changes/llm-grounded-narration/tasks.md
- Lines: 1-32
- SHA256: fe222e22079aafa3019654acb2ebc5afbac7c16f7e9f13b641ac02a18e24a4d2

```md
## 1. LLM client 加 chat_text

- [ ] 1.1 `agent/sap_nexus_agent/llm_client.py`：`OpenAiCompatibleLlmClient` 加 `chat_text(messages, *, temperature=0.0, max_tokens=400) -> str`，复用 chat_json 请求逻辑但返回 text content。
- [ ] 1.2 更新 `agent/tests/test_llm_intent.py` 或新增 client 测试：fake client 支持 chat_text；确认 chat_json 不破坏。

## 2. 柔性叙事指引派生

- [ ] 2.1 `agent/sap_nexus_agent/narrator.py`（或新增 `narrator_prompt.py`）：`narration_guidance(capability_id, descriptor) -> str` 按 businessObject/capabilityId 派生叙事指引（InventoryStock -> 库存单值结论指引，PurchaseOrder -> 订单列表归纳指引，未知 -> 通用 fact-based 指引）。
- [ ] 2.2 指引 + fact 字段注入 LLM prompt；system prompt 严格约束「只能用给定 fact 字段、不得编造记录/数值/字段、不得猜测」。

## 3. narrator LLM 主路径 + 模板 fallback

- [ ] 3.1 `narrate_fact`（inventory）：先尝试 LLM 叙事（chat_text + grounding prompt + redact_sensitive），LLM 不可用或 fact 字段不足时 fallback 既有模板拼接。
- [ ] 3.2 `narrate_purchase_order_facts`（PO）：LLM 叙事主路径 + fallback 模板逐条拼接；空列表直接返回「无匹配记录。」（不调 LLM）。
- [ ] 3.3 LLM 输出经 `redact_sensitive` 过滤敏感信息。

## 4. orchestrator 接入

- [ ] 4.1 `agent/sap_nexus_agent/orchestrator.py`：`_finalize_inventory`/`_finalize_purchase_order` 调 narrator 时传入 capability_id（narrator 内部用 catalog 派生指引），或传 descriptor。确认 LLM 不可用时 fallback 路径不破坏现有集成。

## 5. 测试

- [ ] 5.1 更新 `agent/tests/test_reasoning_narrator.py`：LLM 叙事用例（fake chat_text client，inventory + PO + 未知能力）、fallback 用例（LLM 不可用 -> 模板）、防幻觉约束用例（prompt 含「不得编造」约束）、空列表用例、redact 过滤用例。
- [ ] 5.2 更新 `agent/tests/test_orchestrator.py`：narrator LLM 路径集成（注入 fake client），现有 fallback 用例不破坏。

## 6. 验证与端到端

- [ ] 6.1 运行 `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q` 通过。
- [ ] 6.2 运行 `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml` 和 `evals/purchase_order_cases.json` 通过。
- [ ] 6.3 运行 `openspec validate --all --strict` 通过。
- [ ] 6.4 运行 `scripts/verify-agent-callplan-evidence.sh` 通过。
- [ ] 6.5 端到端：CLI 直测库存查询 + PO 查询，确认返回 LLM 生成的自然语言结论（非固定模板格式）。

```

## openspec/changes/llm-grounded-narration/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/llm-grounded-narration/specs/agent-callplan-evidence/spec.md
- Lines: 1-74
- SHA256: 30ab4558e0e9c69b568bb3e9d08c8f9a3cb7afbeb552db4b8cf8bc1ef663f898

```md
## ADDED Requirements

### Requirement: LLM-grounded flexible narration

The system SHALL render Chinese narrative by grounding a Large Language Model on `ReasoningFact` fields and capability metadata, rather than only fixed string templates. The LLM narration prompt SHALL be derived from the capability's `businessObject`/`capabilityId` metadata so that a newly registered capability gets LLM narration without hardcoding a narration template. The system SHALL constrain the LLM to use only the provided fact fields and MUST NOT allow it to invent records, values, or fields not present in the facts.

#### Scenario: Inventory narration generated by LLM

- **WHEN** a `ReasoningFact` for `MM.Inventory.GetAvailability` carries material, plant, available quantity, and unit
- **THEN** the LLM generates a natural-language Chinese conclusion grounded on those fact fields
- **AND** the conclusion does not invent additional stock, demand, recommendation, or write-action details
- **AND** the conclusion does not expose raw SAP table contents or credentials

#### Scenario: Purchase order list narration generated by LLM

- **WHEN** one or more `ReasoningFact` entries for `MM.PurchaseOrder.GetList` carry per-item evidence
- **THEN** the LLM generates a natural-language Chinese summary grounded on those fact fields
- **AND** the summary cites only item fields present in the facts and does not invent additional records or quantities

#### Scenario: Newly registered capability gets LLM narration without template code

- **WHEN** a new capability is registered as `status: active` with a `businessObject` and outputs
- **AND** no narration-recognition code is changed
- **THEN** the LLM narration path can narrate that capability's facts using the derived guidance
- **AND** does not require a hardcoded narration template for the new capability

#### Scenario: LLM narration falls back to template when LLM unavailable

- **WHEN** the LLM is unavailable (missing configuration or connection failure) during narration
- **THEN** the Agent falls back to deterministic template narration grounded on the fact fields
- **AND** does not fail the run solely because the LLM is unavailable

#### Scenario: Empty result narration

- **WHEN** narration is requested for an empty fact list (no matching records)
- **THEN** the narrative states that no matching records were found
- **AND** does not invoke the LLM to invent records

## MODIFIED Requirements

### Requirement: Chinese narration from facts only

The system SHALL render Chinese narrative only from fields present in `ReasoningFact` or structured failure outcomes. When the LLM narration path is used, the LLM SHALL be constrained (via prompt and output redaction) to use only the provided fact fields and MUST NOT invent records, values, or fields; when the LLM is unavailable the system SHALL fall back to deterministic template narration grounded on the same fact fields.

#### Scenario: Narrate available quantity from fact

- **WHEN** a `ReasoningFact` contains material, plant, available quantity, and unit
- **THEN** the Chinese answer includes only those fact values and does not invent additional stock, demand, recommendation, or write-action details

#### Scenario: Narrator rejects missing fact values

- **WHEN** the narrator is asked to output a quantity that is not present in `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure (or falls back to template) instead of inventing the value

### Requirement: List execution result to reasoning facts

The system SHALL convert a successful list-shaped `ExecutionResult` into one or more deterministic `ReasoningFact` entries before narration, with one fact per returned item, and MUST narrate list results only from fields present in those facts. When the LLM narration path is used, the LLM SHALL be constrained to cite only item fields present in the facts and MUST NOT invent additional records or quantities; when the LLM is unavailable the system SHALL fall back to deterministic template narration.

#### Scenario: Successful list execution creates per-item facts

- **WHEN** Gateway execute returns success with a non-empty `purchaseOrders` array for `MM.PurchaseOrder.GetList`
- **THEN** the Agent creates one `ReasoningFact` per purchase order item with `predicate=purchaseOrderItem`, `deterministic=true`, `confidence=1.0`, source capability metadata, and per-item evidence fields
- **AND** the Chinese narrative cites only those item fields present in the facts and does not invent additional records

#### Scenario: Empty list execution creates no item facts

- **WHEN** Gateway execute returns success with an empty `purchaseOrders` array for a valid filter
- **THEN** the Agent does not create per-item facts that claim records exist
- **AND** the Chinese narrative states that no matching purchase orders were found

#### Scenario: Narrator rejects list item values not present in facts

- **WHEN** the narrator is asked to output a PO number, vendor, or quantity that is not present in any `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure (or falls back to template) instead of inventing the value

```

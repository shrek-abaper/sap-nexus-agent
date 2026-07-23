# Comet Design Handoff

- Change: flexible-intent-recognition
- Phase: design
- Mode: compact
- Context hash: 78ff8149e0401a92c73d1c2cbfc0e5edeabde89dc6007216a5b9ea3786df38d3

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/flexible-intent-recognition/proposal.md

- Source: openspec/changes/flexible-intent-recognition/proposal.md
- Lines: 1-47
- SHA256: c9adbebfe315d24dbb9eb84163ec24fd34c2377c9186b80fe919720adfdbcdba

```md
## Why

当前 Agent 意图识别入口层（`llm_intent.py` / `cli.py`）是为「库存-only 时代」写的，OData 采购订单能力落地后未同步更新，导致已注册的 `MM.PurchaseOrder.GetList` 无法通过自然语言触发：

- 查询「查询采购订单DEMOPO1」返回 `当前仅支持已注册的只读能力（库存可用量查询、采购订单列表）。`
- 根因有三：(1) hybrid 模式 LLM 失败 fallback 调用库存-only 解析器 `parse_inventory_intent` 而非统一解析器 `parse_intent`；(2) LLM prompt 写死「只支持库存（capabilityId=MM.Inventory.GetAvailability），allowed intents 只有 inventory_availability/unsupported」；(3) CLI 入口用 `run_inventory_query` 且 `_payload_to_parse_result` 只认库存意图。
- 下游（`run_query` / `select_capability` / PO fact / PO narrator）已完整支持 PO，问题完全集中在意图识别入口层。

需要将意图识别重构为**柔性识别**：意图闭集从 `registry/capabilities.yaml` 的 active capability 动态派生，LLM prompt 动态注入能力元数据，新增能力只需注册即自动支持（LLM 可用时零代码），并修复规则 fallback 使 PO 等已注册能力在 LLM 不可用时也可查。

## What Changes

- 新增 `agent/sap_nexus_agent/registry_loader.py`：从 `registry/capabilities.yaml` 读取 active capability，派生 `IntentCatalog`（capability 闭集 + 描述符，含 capabilityId/name/description/domain/businessObject/inputs），供 LLM prompt 与闭集校验使用。
- 重构 `agent/sap_nexus_agent/llm_intent.py`：
  - LLM prompt 从「写死库存」改为**动态注入 registry 所有 active capability 的 capabilityId + description + inputs**，LLM 直接选 capabilityId 并提取参数（不再经 intent 名中转）。
  - `_payload_to_parse_result` 增加 **capabilityId 闭集校验**（必须在 registry active 集合内）+ 按 capability inputs 校验 required 参数；不再只认 `inventory_availability`。
  - hybrid/llm 模式 fallback 从 `parse_inventory_intent` 改为 **`parse_intent`**（统一规则解析器，已支持 PO）。
  - `build_intent_adapter(mode, catalog)` 注入 catalog。
- `agent/sap_nexus_agent/intent.py`：`IntentParseResult` 增加 `capability_id: str | None` 字段（LLM 路径填 capabilityId，规则路径填 intent 名）。规则解析器本身行为不变。
- `agent/sap_nexus_agent/capability_selector.py`：`select_capability` 优先用 `parse_result.capability_id`，回退 `INTENT_TO_CAPABILITY.get(intent)`。RFC/OData 拦截、missing_parameters 逻辑不变。
- `agent/sap_nexus_agent/cli.py`：入口从 `run_inventory_query` 改为 `run_query`（统一入口，能路由 PO）；加载 catalog 注入 adapter；help 文案去掉 inventory-only 措辞。
- 不改 `registry/capabilities.yaml` schema（复用现有 description/inputs/businessObject 字段）；不改下游 fact/narrator/gateway/前端事件流。

## Capabilities

### New Capabilities

（无独立新 spec 文件）

### Modified Capabilities

- `capability-registry-gateway`: 新增「柔性意图识别」行为--Agent 意图识别的 capability 闭集从 registry active capability 动态派生，LLM 直接从闭集选 capabilityId，规则 fallback 覆盖已注册的显式意图；新增已注册能力时 LLM 路径自动支持，无需改意图识别代码。

## Impact

- Agent 代码（Python）：
  - 新增 `agent/sap_nexus_agent/registry_loader.py`
  - 修改 `agent/sap_nexus_agent/llm_intent.py`、`intent.py`、`capability_selector.py`、`cli.py`
- 测试：
  - 更新 `agent/tests/test_llm_intent.py`（prompt 不再写死库存、PO LLM 用例、闭集校验、fallback 改 parse_intent）
  - 更新 `agent/tests/test_orchestrator.py`（run_query 经 LLM adapter 选 PO）
  - 新增 `agent/tests/test_registry_loader.py`
  - `agent/tests/test_intent.py` 基本不变（规则解析器不动）
- Registry：不改 schema，不改 `capabilities.yaml` 内容；`validate_registry_contract.py` 不受影响。
- 前端：不改（事件流、intentMode 默认 hybrid 保留）。
- 依赖：无新增（继续用现有 openai-compatible LLM client + PyYAML，后者已是依赖）。
- 验证：`pytest agent/tests`、PO eval、`validate_registry_contract.py`、`openspec validate --all --strict`、`scripts/verify-agent-callplan-evidence.sh` 仍需通过；端到端「查询采购订单DEMOPO1」应返回 PO 列表。

```

## openspec/changes/flexible-intent-recognition/design.md

- Source: openspec/changes/flexible-intent-recognition/design.md
- Lines: 1-82
- SHA256: c749483cc88548a16d92cb8c9c44e108b18fe01599062f0d16e9f9e7c398316b

[TRUNCATED]

```md
## Context

Agent 意图识别入口层（`llm_intent.py` / `cli.py`）为库存-only 时代编写。OData PO 能力（`MM.PurchaseOrder.GetList`）已注册并已通过 `run_query` + PO fact/narrator 端到端验证（`test_run_query_po_list_success`），但意图识别入口层未同步：

- `llm_intent.py` LLM prompt 写死 `CAPABILITY_ID=MM.Inventory.GetAvailability`，allowed intents 仅 `inventory_availability/unsupported`。
- hybrid fallback 用 `parse_inventory_intent`（库存-only），而非 `parse_intent`（已支持 PO）。
- `cli.py` 入口 `run_inventory_query`，`_payload_to_parse_result` 只认库存意图。

`registry/capabilities.yaml` 每个 active capability 已有 `capabilityId/name/description/domain/businessObject/inputs[]`（含 name/semanticName/required/type），足以派生 LLM prompt 上下文与闭集校验，无需改 schema。LLM 配置已就绪（`.env` 配 DeepSeek-V4-Flash 网关，`available=True`）。

## Goals / Non-Goals

**Goals:**
- 意图闭集从 `registry/capabilities.yaml` active capability 动态派生，LLM prompt 动态注入能力元数据。
- LLM 直接选 capabilityId（不经 intent 名中转）+ 提取参数；闭集校验 + required 参数校验兜底。
- 规则 fallback 修复为 `parse_intent`（支持 PO），LLM 不可用时已注册显式意图可查。
- 新增 active capability 时 LLM 路径自动支持（零代码）。
- CLI 入口改 `run_query`，能路由 PO。
- 不改 registry schema、下游 fact/narrator/gateway、前端事件流。

**Non-Goals:**
- 不改 `registry/capabilities.yaml` schema（不加 intent/keywords 字段，`aliases` 留作未来可选扩展）。
- 不实现规则路径的完全柔性（规则路径仍需在 `intent.py` 显式映射；LLM 不可用时仅覆盖显式意图）。
- 不改前端（intentMode 默认 hybrid 保留，事件流不变）。
- 不改 LLM client（继续 openai-compatible + DeepSeek 网关）。
- 不做多轮上下文、不做 capability 之外的意图（如非 SAP 业务问题）。

## Decisions

### D1: A 方案为主--LLM 从 registry 闭集选 capabilityId，不改 schema

LLM prompt 动态注入所有 active capability 的 `capabilityId + description + inputs`，LLM 选 capabilityId + 提取参数。备选 B（registry 加 intent/keywords 字段）被否：关键词维护反柔性、schema 改动大、规则 fallback 价值有限（LLM 不可用时 A 的 businessObject 粗匹配 + 修复后的 `parse_intent` 已覆盖显式意图）。

### D2: LLM 路径直接输出 capabilityId，不经 intent 名中转

`IntentParseResult` 增加 `capability_id` 字段。LLM 路径填 capability_id（不填 intent），规则路径填 intent（不填 capability_id）。`select_capability` 优先用 `capability_id`，回退 `INTENT_TO_CAPABILITY[intent]`。两路径在 selector 汇合，下游无感。

**为何不统一为 intent 名**：LLM 选 capabilityId 更直接（registry 闭集即 capabilityId），intent 名是规则路径的内部概念。统一到 capabilityId 让 LLM 路径与 registry 闭集天然对齐。

### D3: registry_loader 派生 IntentCatalog

新增 `registry_loader.py`：`load_intent_catalog()` 读 `registry/capabilities.yaml`，过滤 `status==active`，构建 `IntentCatalog`（`capabilities: list[CapabilityDescriptor]` + `capability_ids: frozenset`）。repo_root 解析多级回退：`SAP_NEXUS_AGENT_ROOT` env > 向上查找 `registry/` > cwd。

### D4: 闭集校验 + required 参数校验

`_payload_to_parse_result(payload, catalog)`：
1. capabilityId 必须在 `catalog.capability_ids` 内，否则 intent=None（unsupported）。
2. 按 capabilityId 对应 inputs 校验 required 参数，生成 `missing_parameters` + `clarification`。
3. OData/RFC 注入检测保留（双层防御）。

### D5: fallback 修复为 parse_intent

hybrid/llm 模式 LLM 不可用时回退 `parse_intent`（非 `parse_inventory_intent`）。`parse_intent` 已支持 inventory + purchase_order_list，是规则路径的正确统一入口。

### D6: CLI 入口改 run_query

`cli.py` 从 `run_inventory_query` 改 `run_query`，加载 catalog 注入 adapter。`run_inventory_query` 保留（向后兼容，测试用）。

## Risks / Trade-offs

- **[LLM 选错 capabilityId]** -> 闭集校验 + required 参数校验兜底；错则 unsupported，不执行。
- **[LLM 不可用时规则 fallback 仅覆盖显式意图]** -> 已修复为 `parse_intent`（PO 可查）；口语变体需 LLM。属 Non-Goal。
- **[IntentParseResult 加字段影响既有测试]** -> 字段默认 None，既有断言不破坏；测试同步更新。
- **[registry 读取路径解析（agent cwd 不定）]** -> `load_intent_catalog` 多级回退 env > 向上找 registry/ > cwd；测试注入固定路径。
- **[LLM prompt 随能力增长变长]** -> 当前仅 2 能力，可控；后续可按 domain 分组或摘要。
- **[规则路径仍需手动加映射]** -> 规则路径固有局限；LLM 可用时完全柔性。`aliases` 字段留未来扩展口。

## Migration Plan

纯 agent 侧重构，无数据迁移、无后端部署：

1. 实现 registry_loader + llm_intent 重构 + intent/capability_selector/cli 小改。
2. 更新/新增测试。
3. `pytest agent/tests` + PO eval + `validate_registry_contract.py` + `openspec validate --all --strict` + `verify-agent-callplan-evidence.sh` 通过。
4. 端到端：启动后前端查「查询采购订单DEMOPO1」返回 PO 列表。
5. 归档 change。

**回滚**：`git revert` agent 改动即可，无副作用。

## Open Questions

```

Full source: openspec/changes/flexible-intent-recognition/design.md

## openspec/changes/flexible-intent-recognition/tasks.md

- Source: openspec/changes/flexible-intent-recognition/tasks.md
- Lines: 1-37
- SHA256: d876cde55ccd734176c8e0ab7fa6facfd88df29a49c7011e5aaf886f2b80294b

```md
## 1. Registry 派生意图闭集

- [ ] 1.1 新增 `agent/sap_nexus_agent/registry_loader.py`：定义 `CapabilityDescriptor` / `InputDescriptor` / `IntentCatalog` dataclass；`load_intent_catalog(repo_root=None)` 读 `registry/capabilities.yaml`，过滤 `status==active`，构建 capabilities 列表 + `capability_ids` frozenset。
- [ ] 1.2 repo_root 多级回退解析：`SAP_NEXUS_AGENT_ROOT` env > 向上查找 `registry/` 目录 > cwd；找不到时返回空 catalog 并记录（不抛异常，让 LLM 路径自然降级为 unsupported）。
- [ ] 1.3 新增 `agent/tests/test_registry_loader.py`：读真实 capabilities.yaml 派生 catalog、active 过滤、闭集含 inventory + PO、inputs 解析正确。

## 2. IntentParseResult 扩展 capability_id

- [ ] 2.1 `agent/sap_nexus_agent/intent.py`：`IntentParseResult` 增加 `capability_id: str | None = None` 字段；规则解析器（`parse_intent`/`parse_inventory_intent`）行为不变，不填 capability_id。
- [ ] 2.2 `agent/sap_nexus_agent/capability_selector.py`：`select_capability` 优先用 `parse_result.capability_id`，回退 `INTENT_TO_CAPABILITY.get(parse_result.intent)`；RFC/OData 拦截与 missing_parameters 逻辑不变。

## 3. LLM 意图层柔性重构

- [ ] 3.1 `agent/sap_nexus_agent/llm_intent.py`：`_messages(text, catalog)` 动态注入所有 active capability 的 `capabilityId + description + inputs`，prompt 改为「从闭集选 capabilityId 并提取参数，都不匹配则 capabilityId=null」。
- [ ] 3.2 `_payload_to_parse_result(payload, catalog)`：capabilityId 闭集校验（不在 active 集合则 intent=None/unsupported）；按选中 capability 的 required inputs 校验参数，生成 missing_parameters + clarification；OData/RFC 注入检测保留；LLM 路径填 `capability_id` 不填 intent。
- [ ] 3.3 `parse_with_llm` / `parse_with_hybrid` 接收 catalog 参数；`parse_with_hybrid` fallback 从 `parse_inventory_intent` 改为 **`parse_intent`**。
- [ ] 3.4 `build_intent_adapter(mode, catalog)` 注入 catalog；rule 模式仍返回 `parse_inventory_intent`（纯库存向后兼容）或改 `parse_intent`（确认）。

## 4. CLI 入口统一

- [ ] 4.1 `agent/sap_nexus_agent/cli.py`：入口从 `run_inventory_query` 改 `run_query`；加载 `load_intent_catalog()` 注入 `build_intent_adapter(mode, catalog)`；help 文案去掉 inventory-only 措辞。
- [ ] 4.2 确认 `run_inventory_query` 保留（向后兼容 + 测试用），不删除。

## 5. 测试更新

- [ ] 5.1 更新 `agent/tests/test_llm_intent.py`：移除「prompt 写死库存」断言；新增 PO LLM 用例（fake client 返回 PO capabilityId + poNumber -> 正确解析）；新增闭集校验用例（非法 capabilityId -> unsupported）；fallback 改 `parse_intent` 的断言。
- [ ] 5.2 更新 `agent/tests/test_orchestrator.py`：补 `run_query` 经 LLM adapter（注入 catalog + fake client）选 PO 的集成用例；确认现有 inventory 用例不破坏。
- [ ] 5.3 确认 `agent/tests/test_intent.py` 不破坏（规则解析器未改行为，仅加字段）。

## 6. 验证与端到端

- [ ] 6.1 运行 `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q` 通过。
- [ ] 6.2 运行 `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/purchase_order_cases.json` 通过（PO eval）。
- [ ] 6.3 运行 `.venv/bin/python scripts/validate_registry_contract.py registry/capabilities.yaml` 通过。
- [ ] 6.4 运行 `openspec validate --all --strict` 通过。
- [ ] 6.5 运行 `scripts/verify-agent-callplan-evidence.sh` 通过。
- [ ] 6.6 端到端：CLI 直测 `查询采购订单DEMOPO1` 返回 PO 列表（非 unsupported）。

```

## openspec/changes/flexible-intent-recognition/specs/capability-registry-gateway/spec.md

- Source: openspec/changes/flexible-intent-recognition/specs/capability-registry-gateway/spec.md
- Lines: 1-48
- SHA256: 53f62b915ebd97ab80d75f2f487de278d95decd259ca7c5b9a1a7257063d1134

```md
## ADDED Requirements

### Requirement: Flexible intent recognition from registry capability set

The Agent SHALL derive the intent recognition capability closed set from active capabilities in the capability registry (`registry/capabilities.yaml`), rather than hardcoding a single capability. The LLM intent path SHALL dynamically inject all active capabilities' `capabilityId`, `description`, and `inputs` into the LLM prompt, and the LLM SHALL select a `capabilityId` directly from that closed set. A capability registered as `status: active` SHALL become selectable by the LLM path without any intent-recognition code change.

#### Scenario: Registered purchase order capability is selectable via natural language

- **WHEN** a user submits `查询采购订单DEMOPO1` and `MM.PurchaseOrder.GetList` is an active registered capability
- **THEN** the Agent intent recognition selects `MM.PurchaseOrder.GetList` (via LLM or rule fallback)
- **AND** extracts `poNumber=DEMOPO1` as a parameter
- **AND** the run proceeds to capability selection, CallPlan, Gateway validate, and Gateway execute for that capability
- **AND** does not return the "仅支持已注册的只读能力" unsupported message

#### Scenario: LLM selects capabilityId from dynamic registry closed set

- **WHEN** the LLM intent path runs with a registry containing both `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList` as active capabilities
- **THEN** the LLM prompt lists both capabilityIds with their descriptions and inputs
- **AND** the LLM returns a `capabilityId` that is a member of the active registry closed set
- **AND** a `capabilityId` not in the active registry closed set is rejected as unsupported

#### Scenario: Required parameters validated against selected capability inputs

- **WHEN** the LLM selects a capabilityId and the registry defines required inputs for that capability
- **THEN** the Agent validates that all required inputs are present
- **AND** if a required input is missing, returns a clarification identifying the missing parameter
- **AND** does not proceed to Gateway execution until required inputs are satisfied

#### Scenario: Rule fallback covers registered explicit intents when LLM unavailable

- **WHEN** the LLM is unavailable (missing configuration or connection failure) in hybrid mode
- **THEN** the Agent falls back to the unified rule parser (`parse_intent`) that recognizes both inventory and purchase order list intents
- **AND** does not fall back to an inventory-only parser
- **AND** a registered explicit-intent query (e.g. `查询采购订单DEMOPO1`) still resolves to the correct capability

#### Scenario: Newly registered active capability is auto-supported by LLM path

- **WHEN** a new capability is added to `registry/capabilities.yaml` with `status: active` and a description and inputs
- **AND** no intent-recognition code is changed
- **THEN** the LLM path can select the new capabilityId from the dynamically injected prompt
- **AND** the rule fallback does not need to know about the new capability for the LLM path to work

#### Scenario: CLI unified entry routes to any registered capability

- **WHEN** the Agent CLI entry processes a query
- **THEN** it uses the unified `run_query` entry that routes by selected capabilityId
- **AND** can route to both inventory and purchase order capabilities
- **AND** does not use an inventory-only entry that prevents purchase order routing

```

# Semantic Tool HTTP Facade Specification

## Purpose

在现有 Next app 内为外部 harness 提供窄的、harness 无关的语义级 HTTP 契约，把
harness（DeepSeek Harness、Python CLI、未来其他宿主）与服务端编排权威隔开。
本期只暴露一个只读语义工具 `diagnose_material_supply`，其域侧行为复用已有的
Python intent/plan authoring 与 TS composition coordinator（见 canonical
`production-agent-composition-orchestration`），不新建编排引擎。facade 是方案
R-2/R-3 的过渡形态：先建立进程边界与契约，内部实现（spawn Python / TS
coordinator）由后续 change 替换为 Resolve Service / Plan Service。

## Requirements

### Requirement: Facade exposes business-semantic tools, never atomic capabilities

facade SHALL 只暴露业务语义级工具（本期仅 `diagnose_material_supply`），MUST NOT
暴露原子 `capabilityId`、`bindingId`、`rfcName`、服务 URL、HTTP 方法或凭证引用入参。
请求方只能提交自然语言目标、已知槽位（按 semanticType 命名）与上下文提示
（plant_scope/module/period_hint）；任何技术绑定字段 MUST 被 fail-closed 拒绝。

#### Scenario: Semantic request returns a material supply diagnosis

- **WHEN** 客户端以 `{ tool: "diagnose_material_supply", utterance, slots: { material, plant }, context }` 调用 facade
- **THEN** 服务端经既有治理链路（governed principal → snapshot → intent/plan → READ composition）返回结构化结果：resolved semantic values（含 provenance）、执行的 capability 链、MaterialSupplySnapshot facts（含 lineage refs）、narrative envelope 与 limitations
- **AND** 响应中不出现 RFC 名、binding 名、目标 URL 或凭证引用

#### Scenario: Technical binding fields are rejected

- **WHEN** 请求含 `rfcName`、`bindingId`、`endpoint`、`credentialRef` 或任意技术覆盖字段
- **THEN** facade 返回 400 结构化错误（errorType `TECHNICAL_OVERRIDE_REJECTED`）
- **AND** 不产生 Gateway validate/execute 调用

### Requirement: Facade signatures contain no harness-specific objects

facade 的请求/响应 schema MUST NOT 出现任何 DeepSeek Harness / Cordis / 其他
harness 专属类型（`ctx.*`、plugin context、session seam）。契约以开放的 JSON
Schema 定义并纳入 `schemas/`，携带契约版本号；破坏性变更 MUST 提升版本。

#### Scenario: Two harnesses use one identical contract

- **WHEN** dsh 应用与任一其他 HTTP 客户端以相同版本契约提交等价请求
- **THEN** 服务端处理路径与结果结构一致，不依据客户端 harness 类型分叉

### Requirement: Read-only chain never invokes WRITE or transaction control

`diagnose_material_supply` 的执行图 MUST 只包含 READ partition（本期固定为
MM.Inventory.GetAvailability、MM.PurchaseOrder.GetList、MM.Material.GetInfo
的可达闭包子集）。facade MUST NOT 接受、生成或执行任何 WRITE/Action capability；
READ 路径 MUST NOT 调用 `BAPI_TRANSACTION_COMMIT/ROLLBACK`。

#### Scenario: Goal requiring write is out of scope

- **WHEN** 解析后的目标需要 WRITE（如创建 PR）
- **THEN** facade 返回 `OUT_OF_SCOPE_FOR_TOOL` 结构化结果（可选返回工具名候选）
- **AND** 不创建审批记录、不调用 Action executor

### Requirement: Server-owned identity and audit on every call

facade SHALL 复用现有 `injectPrincipal` 服务端身份注入与 Gateway 审计链；请求方
提供的 principal 声明 MUST NOT 被信任为身份来源。每次调用 MUST 落可追溯的
run/trace 记录（沿用现有 durable run store / redaction 规则）。

#### Scenario: Call without server principal is rejected

- **WHEN** 请求上下文无法解析 server-owned principal
- **THEN** facade 返回 401/403 结构化错误
- **AND** 不触达 Gateway

### Requirement: Fail-closed semantics and freshness are explicit

facade SHALL 透传组合执行的 completeness/freshness/limitations；SAP 超时或数据
不可用时 MUST 返回显式不可用状态，MUST NOT 用陈旧值冒充实时结果。闭包外目标
MUST 返回 gap 结构，不降级为任意能力尝试。

#### Scenario: Upstream timeout is reported as unavailable

- **WHEN** 链上任一 READ 超时或失败导致快照不完整
- **THEN** 响应标 `partial`/`unavailable` 并带 failed nodes 与 limitations
- **AND** narrative 不产生无 evidence 支撑的结论

# Comet Design Handoff

- Change: multi-value-batch-service-integration
- Phase: design
- Mode: compact
- Context hash: 2331e0f45888ab2cc703c3f5d320a31156a411031b99d47054f7b0954bd93d06

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/multi-value-batch-service-integration/proposal.md

- Source: openspec/changes/multi-value-batch-service-integration/proposal.md
- Lines: 1-30
- SHA256: 85e7dbc8745d21c91222d8990059ac5e89763b9badc29502674c3370ff87410c

```md
## Why

`awaiting_batch_confirm` 端到端不可用：`continue_batch` 在生产代码零调用方（无 CLI/workbench/SSE 入口），`combinations` 不跨轮携带。上一个 change 实现了 orchestrator 层（run_query 多值检测 + continue_batch + narrate_inventory_facts），hotfix 止住了"确认"死循环（`_last_context_from_outcome` 对 awaiting_batch_confirm 返回 None），但功能仍不可用：用户"确认"后得到 CLARIFY/REJECT 而非批量结果。

根因：服务层集成缺失。`continue_batch` 类比 `continue_action`（Action 审批流），但后者有完整的服务层接续（workbench 序列化 approvalRecord + 前端 pendingOutcome 持有 + ApprovalContinuation 回传 + CLI `--continue-action` + runner 调用 continue_action），batch 路径缺这套接续。

## What Changes

全类比 `continue_action` 审批流（A+A 设计：前端持有 combinations 回传 + 显式 continuation）：

- **`workbench_output.py`**：`outcome_to_workbench_dict` 序列化 `combinations`（类比 `approvalRecord`）。
- **`agent-runtime-adapter.ts`**：`WorkbenchOutcome` 增加 `combinations` 字段；新增 `BatchContinuation` 类型（callPlan + combinations）；`awaiting_batch_confirm` -> pendingOutcome 持有；用户确认 -> BatchContinuation 回传 -> 调用 `continue_batch`。
- **`cli.py`**：新增 `--continue-batch` 标志（类比 `--continue-action`），解析 callPlan + combinations 调 `continue_batch`。
- **API route / SSE**：batch continuation 端点（类比 approval continuation），SSE `awaiting_batch_confirm` 状态。
- **`continue_batch`**：已有实现，接上调用方。

## Capabilities

### New Capabilities
（无新 capability，集成现有 continue_batch 到服务层）

### Modified Capabilities
- `agent-callplan-evidence`：`awaiting_batch_confirm` outcome 序列化 combinations + continue_batch 服务入口 + batch continuation 流。

## Impact

- **Python Agent**：`agent/sap_nexus_agent/workbench_output.py`（序列化 combinations）、`agent/sap_nexus_agent/cli.py`（--continue-batch）。
- **Frontend**：`frontend/src/runtime/agent-runtime-adapter.ts`（WorkbenchOutcome.combinations + BatchContinuation + 路由）、API route（batch continuation 端点）、SSE 事件（awaiting_batch_confirm）。
- **测试**：`agent/tests/test_{workbench_output,orchestrator,conversation_context}.py` + frontend tests + e2e（awaiting_batch_confirm -> 确认 -> 批量结果）。
- **非影响**：orchestrator/selector/narrator 核心逻辑不变（已实现）；capability 契约不变；Action 审批流不变；WRITE 批量不做（continue_batch 仅 READ）。

```

## openspec/changes/multi-value-batch-service-integration/design.md

- Source: openspec/changes/multi-value-batch-service-integration/design.md
- Lines: 1-53
- SHA256: c793a4315b8c2c48d13591700f0b9812e12cf79cfe2089fa474d8d22d3fcac33

```md
## Context

`continue_action` 审批流有完整服务层接续：`run_query` -> `awaiting_approval`（approval_record）-> `outcome_to_workbench_dict` 序列化 approvalRecord -> 前端 `pendingOutcome` 持有 -> 用户 approve -> `ApprovalContinuation` 回传（callPlan+validationResult+approvalRecord）-> runner 调 `continue_action`。`continue_batch` 缺这套接续：`combinations` 未序列化、无 continuation 类型、无 CLI 入口、零调用方。

## Goals / Non-Goals

**Goals**:
- `awaiting_batch_confirm` outcome 序列化 `combinations` + `callPlan` 到 workbench dict。
- 前端 `pendingOutcome` 持有 combinations；用户确认 -> `BatchContinuation` 回传 -> 调 `continue_batch`。
- CLI `--continue-batch` 入口。
- API route / SSE 支持 batch continuation。
- 端到端：Turn N 多值 -> awaiting_batch_confirm；Turn N+1 确认 -> continue_batch -> 批量聚合结果。

**Non-Goals**:
- 不改 orchestrator/selector/narrator 核心逻辑（已实现）。
- 不实现 WRITE 批量（continue_batch 仅 READ，Action 落到 awaiting_approval）。
- 不改 capability 契约。
- 不改 Action 审批流。
- 不做服务端 BatchRecord（reads 无状态，前端持有回传，类比 approval）。

## Decisions

### D1: combinations 前端持有回传（类比 approvalRecord）
`outcome_to_workbench_dict` 序列化 `combinations` + `callPlan`。前端 `AgentRunRecord.pendingOutcome` 持有（与 approval 相同机制）。用户确认 -> `BatchContinuation`（callPlan + combinations）回传。无服务端状态（reads 无状态，与 approval 审批流的 pendingOutcome 持有一致）。

### D2: 显式 continuation（类比 approve）
不自动检测"确认"文本。前端检测 `status="awaiting_batch_confirm"` + 用户点确认按钮 -> 发 `BatchContinuation`。CLI `--continue-batch` 标志（类比 `--continue-action`）。可靠且与 approval 一致。

### D3: continue_batch READ-only 不变
`continue_batch` 已有 READ-only 守卫（ValueError on Action）。batch continuation 仅对 READ capability（inventory）。Action + multi_parameters 仍走 awaiting_approval（run_query 守卫已保证）。

### D4: API route / SSE
batch continuation 复用 approval continuation 的端点模式（或并行新端点，design 阶段细化）。SSE 增加 `awaiting_batch_confirm` 状态事件（类比 `awaiting_approval`）。

## Risks / Trade-offs

- 前端持有 combinations：与 approval 一致，但 combinations 可能较大（≤20 组合，每组合小 dict）。可接受。
- API route 设计（复用 vs 新端点）需 design 阶段细化。
- SSE 状态扩展：`AgentRunState` 增加 `awaiting_batch_confirm`（类比 `awaiting_approval`）。
- 跨轮 combinations 完整性：前端持有，无服务端校验（类比 approval 的 approvalRecord 前端持有）。READ 操作无安全风险。

## Migration Plan

1. `workbench_output.py`：序列化 combinations。
2. `agent-runtime-adapter.ts`：WorkbenchOutcome.combinations + BatchContinuation + 路由。
3. `cli.py`：--continue-batch。
4. API route / SSE：batch continuation 端点 + awaiting_batch_confirm 状态。
5. 测试 + e2e。

## Open Questions

1. API route：复用 approval continuation 端点 vs 新增 batch continuation 端点？（design 阶段细化）
2. SSE `awaiting_batch_confirm` 状态事件设计？（design 阶段细化）

```

## openspec/changes/multi-value-batch-service-integration/tasks.md

- Source: openspec/changes/multi-value-batch-service-integration/tasks.md
- Lines: 1-33
- SHA256: e5fd630c5121cd99097488f9c156dde6cf4dbbb61db36c390fb9d28961270f24

```md
## 1. workbench 序列化 combinations

- [ ] 1.1 `outcome_to_workbench_dict` 序列化 `combinations`（类比 approvalRecord，line 44）
- [ ] 1.2 测试：awaiting_batch_confirm outcome -> workbench dict 含 combinations + callPlan
- [ ] 1.3 测试：非 awaiting_batch_confirm outcome -> combinations=None

## 2. 前端 agent-runtime-adapter BatchContinuation

- [ ] 2.1 `WorkbenchOutcome` 增加 `combinations` 字段
- [ ] 2.2 新增 `BatchContinuation` 类型（callPlan + combinations）
- [ ] 2.3 `awaiting_batch_confirm` -> pendingOutcome 持有 combinations
- [ ] 2.4 用户确认 -> BatchContinuation 回传 -> 调用 continue_batch（类比 ApprovalContinuation -> continue_action）
- [ ] 2.5 测试：awaiting_batch_confirm pendingOutcome 持有；确认 -> continue_batch 调用

## 3. CLI --continue-batch

- [ ] 3.1 `cli.py` 新增 `--continue-batch` 标志（类比 `--continue-action`）
- [ ] 3.2 解析 callPlan + combinations JSON -> 调 `continue_batch(call_plan, combinations, gateway)`
- [ ] 3.3 测试：--continue-batch 调 continue_batch 返回批量结果

## 4. API route / SSE batch continuation

- [ ] 4.1 API route：batch continuation 端点（类比 approval continuation，design 阶段定复用 vs 新端点）
- [ ] 4.2 SSE：`awaiting_batch_confirm` 状态事件（AgentRunState + 事件类型，类比 awaiting_approval）
- [ ] 4.3 测试：API batch continuation 端到端

## 5. 验证

- [ ] 5.1 `openspec validate --all --strict` 通过
- [ ] 5.2 pytest 回归（workbench_output + cli + orchestrator）
- [ ] 5.3 `npm --prefix frontend run verify`（frontend 改动）
- [ ] 5.4 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 5.5 e2e：Turn N 多值 -> awaiting_batch_confirm + combinations 序列化；Turn N+1 确认 -> continue_batch -> 批量聚合结果

```

## openspec/changes/multi-value-batch-service-integration/specs/agent-callplan-evidence/spec.md

- Source: openspec/changes/multi-value-batch-service-integration/specs/agent-callplan-evidence/spec.md
- Lines: 1-46
- SHA256: 4222bbbb4e8d7fdce5fffaf974170767ddaeaaf1730469d708b596363d3be6c1

```md
## MODIFIED Requirements

### Requirement: Multi-value query split
The orchestrator SHALL support multi-value inventory queries where any parameter (e.g. `plant`, `material`) has multiple values. When the LLM identifies multiple values for one or more parameters in a single utterance (e.g. "DEMOA2 和 DEMOA4 在 5200、1000 的库存"), the orchestrator SHALL expand the Cartesian product of the multi-valued parameters (via `multi_parameters`) into a combination list and return `AgentOutcome.status="awaiting_batch_confirm"` with the combinations. The orchestrator SHALL NOT execute Gateway calls until the user confirms. Upon confirmation, `continue_batch` SHALL execute single-value execute calls per combination (the single-plant/single-material capability contract SHALL NOT change) and aggregate the results. Partial failures (one combination fails) SHALL be surfaced as partial results with the failed combination annotated. A soft combination cap (default 20) SHALL emit CLARIFY when exceeded, instead of `awaiting_batch_confirm`.

The workbench SHALL clear the session `last_context` (emit `None`) for an `awaiting_batch_confirm` outcome, so the LLM does not re-emit `multi_parameters` from the prior SELECT's material on the user's confirmation reply (which would loop back to `awaiting_batch_confirm`).

The workbench SHALL serialize the `combinations` and `callPlan` for an `awaiting_batch_confirm` outcome so the frontend can hold them pending user confirmation. Upon user confirmation, the service layer SHALL route a `BatchContinuation` (carrying `callPlan` + `combinations`) to `continue_batch`; this is analogous to the `continue_action` approval flow where the frontend holds `approvalRecord` and returns an `ApprovalContinuation`. `continue_batch` is READ-only (Action capabilities MUST NOT enter this path).

#### Scenario: Multi-value query emits awaiting_batch_confirm
- **WHEN** the user asks "DEMOA2 和 DEMOA4 在 5200、1000的库存分别是多少" (same conversation)
- **THEN** the LLM returns `multi_parameters={plant:[5200,1000], material:[DEMOA2,DEMOA4]}`
- **AND** the orchestrator expands 4 combinations (2×2 Cartesian product)
- **AND** returns `awaiting_batch_confirm` with the 4 combinations and does NOT call Gateway validate or execute

#### Scenario: Confirmed multi-value batch executes and aggregates
- **WHEN** the user confirms the batch from a prior `awaiting_batch_confirm` outcome
- **THEN** `continue_batch` executes MM.Inventory.GetAvailability once per combination
- **AND** aggregates results into a single narrative: "5200: 176 EA; 1000: 0 EA" (single material) or a per-material narrative (multi material)

#### Scenario: Multi-value partial failure
- **WHEN** one combination execute fails (SAP error) in a confirmed batch
- **THEN** `continue_batch` returns partial results with the failed combination annotated
- **AND** does not fail the entire batch

#### Scenario: Multi-value combination cap
- **WHEN** the expanded combinations exceed the soft cap (default 20)
- **THEN** the orchestrator emits CLARIFY "组合数过多，请缩小范围" instead of `awaiting_batch_confirm`
- **AND** does NOT execute any Gateway call

#### Scenario: awaiting_batch_confirm clears session last_context
- **WHEN** the orchestrator returns an `awaiting_batch_confirm` outcome
- **THEN** the workbench emits `lastContext=None` for that turn
- **AND** the next turn's intent adapter receives no `last_context`
- **AND** the LLM does not re-emit `multi_parameters` from the prior material on the user's "确认" reply (no dead loop)

#### Scenario: awaiting_batch_confirm serializes combinations to workbench
- **WHEN** the orchestrator returns an `awaiting_batch_confirm` outcome with combinations
- **THEN** the workbench dict includes the `combinations` array and `callPlan`
- **AND** the frontend holds them in `pendingOutcome` pending user confirmation

#### Scenario: continue_batch service entry executes confirmed batch
- **WHEN** the user confirms the batch (frontend button or CLI `--continue-batch`)
- **THEN** the service layer routes a `BatchContinuation` (callPlan + combinations) to `continue_batch`
- **AND** `continue_batch` executes each combination and aggregates results
- **AND** returns the batch narrative to the user

```

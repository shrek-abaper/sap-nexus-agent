## Why

当前一次 Agent run 的意图识别、候选召回、matcher 与 planner 各自加载或忽略 `RegistrySnapshot`，无法证明它们使用同一快照：matcher（`select_capability`）完全不接 snapshot；`EscalationHandoff.registry_snapshot_id` 恒为空串（`getattr(parse_result, "registry_snapshot_id", "")`，`IntentParseResult` 不携带该字段）；planner 在 `_compile_dry_run_safely` 中另行加载 snapshot，失败时 `except Exception: return None` 静默退化为 `dry_run=None`。同时 `filter_visible` 无任何运行时调用方，principal 止步于 Node durable 鉴权层（`executeRunnerInBackground` 收 `principalId` 仅用于 `run.principalId` 校验，`runner()` 不传 Python），从未到达 intent/matcher/planner。结果是不可见能力可能在 visibility 过滤前进入 LLM prompt，snapshot 漂移或 source load 失败被静默吞掉，cross-principal fail-closed 在决策层无法验收。Runbook 13 关闭这些缺口，为 Runbook 14-22 的召回、规划、执行、投影、建议、叙事和审批提供同快照治理基础。

## What Changes

- 新增 `GovernedContext`（principal + scopes + snapshotId + registryVersion）作为一次 run 的受治理上下文，贯穿 intent、recall、matcher、planner、approval。
- 新增 `SnapshotLease`：持有并校验同一非空 `RegistrySnapshot`；snapshot 缺失、漂移或 principal 不匹配时结构化 fail-closed。
- 新增 `VisibleCapabilitySet`：principal/visibility pre-filter 后的安全 `CapabilityCard[]`，在进入 LLM prompt 前移除不可见能力。
- 新增 `PlannerFailure`：source load 失败、snapshot 漂移、visibility denial 返回稳定 error type + audit evidence，替代 `except: return None` 静默降级。
- `EscalationHandoff.registry_snapshot_id` 绑定为非空（从 `GovernedContext` 填入），证明 matcher 与 planner 使用同一快照。
- `CapabilityCard` 新增 `registry_snapshot_id` 字段；`discover_cards` 绑定 snapshot，不再 `del snapshot` 弃用。
- capability kind / sideEffect / approvalPolicy 从 Registry snapshot 投影，不再以 `capability_id in ACTION_CAPABILITY_IDS` 兜底。
- principal 透传从 Node durable 鉴权层延伸到 Python agent 决策层（CLI `--principal` -> `run_query` -> visibility pre-filter）。
- `ApprovalRecord` 新增 `registry_snapshot_id` 字段（pending 生成时填入），使 approval 记录携带同快照标识；跨语言 approval store 的「漂移使审批失效」执行校验留 Runbook 21。
- `CapabilityCard` 安全投影保持不暴露 RFC、URL、credential、raw SQL 或 technical mapping（现状已不读 `executorBinding`，本轮固化）。

## Capabilities

### New Capabilities

- `governed-context-registry-snapshot`: 一次 Agent run 的受治理上下文与统一 RegistrySnapshot 绑定契约——`GovernedContext`、`SnapshotLease`、`VisibleCapabilitySet`、`PlannerFailure`，principal/visibility pre-filter 与结构化 fail-closed 错误模型。

### Modified Capabilities

- `semantic-match-decision`: matcher 决策路径接入 visibility pre-filter 并消费同一非空 snapshotId；`EscalationHandoff.registry_snapshot_id` 由 `GovernedContext` 填入，不再恒空。
- `planner-dry-run`: planner 绑定同一非空 snapshotId；`CapabilityCard` 携带 `registry_snapshot_id` 且 `discover_cards` 绑定 snapshot；capability kind / sideEffect / approvalPolicy 从 snapshot 投影。
- `trusted-principal-scope`: principal 透传从 durable store 鉴权层延伸到 Python agent 决策层（CLI -> `run_query` -> visibility pre-filter）。
- `pr-create-action`: `ApprovalRecord` 契约新增 `registry_snapshot_id` 字段（pending 生成时从 `GovernedContext` 填入），使 approval 记录携带同快照标识；Node/Java approval store 的漂移使审批失效的执行校验留 Runbook 21。

## Impact

- **代码**：`agent/sap_nexus_agent/` 新增 governed_context 模块；修改 `orchestrator`、`capability_selector`、`match_decision`、`visibility`、`planner/capability_card`、`planner/handoff`、`intent`、`llm_intent`、`cli`、`approval`；`frontend/src/runtime/agent-runtime-adapter.ts` 透传 principal 到 Python CLI。
- **契约**：1 个新 spec（`governed-context-registry-snapshot`）+ 4 个现有 spec 的 requirements delta。
- **测试**：visibility leakage = 0、cross-principal fail-closed（决策层，非仅 durable 层）、snapshot 漂移 / source load 失败结构化错误、`CapabilityCard` 安全投影回归。
- **边界**：不执行 SAP WRITE；不改 matcher 五态决策算法（只绑 snapshot/visibility）；不重建身份/状态/审批/事件机制（复用 P0B）；不夹带 Runbook 14 recall / 15 PlanGraph v2 / 16 PlanExecutor / 20 UI。

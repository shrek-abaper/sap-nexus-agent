# Governed Context and Registry Snapshot Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `13-governed-context-registry-snapshot` |
| Version | `v0.1.1` |
| Status | `Completed / Archived` |
| Created | `2026-08-03` |
| Updated | `2026-08-03` |
| Last Change | Comet archive of `sap-nexus-governed-context-registry-snapshot` (26/26 tasks, pytest 836 passed/1 skipped, openspec 16 passed, verify PASS). Main specs merged: `governed-context-registry-snapshot` (ADDED 6), `planner-dry-run` (MODIFIED 3), `pr-create-action` (MODIFIED 1), `semantic-match-decision` (ADDED 1 + MODIFIED 1), `trusted-principal-scope` (ADDED 1). |
| Depends On | P0B trusted principal and durable runtime foundation (archived) |
| Unblocks | Runbooks 14-22 |
| Related Changes | `sap-nexus-governed-context-registry-snapshot` (archived 2026-08-03 at `openspec/changes/archive/2026-08-03-sap-nexus-governed-context-registry-snapshot/`) |
| Current Phase | Closed; do not resume implementation from this runbook |
| Successor | Runbook 14 (`14-governed-intent-capability-recall.md`) starts LLM-first IntentEnvelope and governed closed-set capability recall |
| Reopen Policy | Do not reopen; visibility scope expansion, snapshot lease lifecycle changes or new PlannerFailure error types require a separate future change |

## 1. Goal

让一次 Agent run 的意图识别、候选召回、规划、执行和审批共享同一个受治理上下文与 `RegistrySnapshot`，关闭 visibility、snapshot handoff 和 Registry-derived capability kind 缺口。

## 2. Current Baseline

- `TrustedPrincipal`、durable Run/Session、ownership/lease、durable approval 和 cursor SSE 已实现。
- S1 可生成四源 `RegistrySnapshot`，S2-B PlanGraph 可绑定 `snapshotId`。
- 当前 LLM intent catalog 在组装提示词时尚未统一经过 principal/visibility pre-filter。
- `EscalationHandoff.registry_snapshot_id` 可能为空；orchestrator 可在 handoff 后重新加载 snapshot，不能证明 matcher 与 planner 使用同一快照。
- 部分调用仍以默认 `Function` 兜底 capability kind；目标是全部从 Registry projection 获得。

## 3. Contracts and Data Flow

```text
TrustedPrincipal + RunId
-> GovernedContext { principal, scopes, snapshotId, registryVersion }
-> visibility pre-filter
-> safe CapabilityCard[]
-> Intent / MatchDecision / Planner / Executor / Approval
```

新增或固化：`GovernedContext`、`SnapshotLease`、`VisibleCapabilitySet`、`PlannerFailure`。所有下游对象必须携带 `runId`、`traceId` 和同一 `snapshotId`；snapshot 不可加载、漂移或 principal 不匹配时返回结构化失败，不以空 dry-run 静默降级。

## 4. Scope and Non-goals

- Scope：服务端身份注入、snapshot 创建/持有/校验、visibility 双重校验、安全投影、结构化错误。
- Non-goal：不改能力召回算法、不执行 PlanGraph、不接 Knowledge/RAG、不引入新身份供应商。

## 5. Safety Boundaries

- 不可见 capability 在进入 LLM prompt 前即移除；Gateway execute 再次授权。
- request、prompt、history 或 model output 不能提供 principal、scope 或 snapshot id。
- `CapabilityCard` 不包含 RFC、URL、header、credential、raw SQL 或 binding mapping。
- snapshot 漂移必须 fail-closed，不能自动换新快照继续既有计划或审批。

## 6. Acceptance Criteria

- 同一 run 的 matcher、planner、executor 和 approval 记录使用同一非空 `snapshotId`。
- visibility leakage Eval 为 0；cross-principal 访问保持 fail-closed。
- capability kind、side effect、approval policy 均从 Registry snapshot 投影。
- source load、snapshot drift、visibility denial 返回稳定 error type 和 audit evidence。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests -q
npm --prefix frontend run verify
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

本 runbook 已归档。下一实施入口为 Runbook 14 (`docs/runbooks/14-governed-intent-capability-recall.md`)：LLM-first IntentEnvelope、多目标拆分和已注册能力召回。不得跳过 14 直接进入 PlanExecutor 或 UI 工作。

---

## Session Closeout - 2026-08-03

### Completed

- Comet full workflow（open → design → build → verify → archive）全部走完，change `sap-nexus-governed-context-registry-snapshot` 归档至 `openspec/changes/archive/2026-08-03-sap-nexus-governed-context-registry-snapshot/`。
- 26/26 tasks 全部勾选；5 个 delta spec 按 ADDED/MODIFIED 语义合并到主 spec（`governed-context-registry-snapshot` +6 / `planner-dry-run` ~3 / `pr-create-action` ~1 / `semantic-match-decision` +1 ~1 / `trusted-principal-scope` +1）。
- Design Doc 和 Plan 已由归档脚本自动标注 `archived-with` / `status` 元数据。

### Verified

- Command: `.venv/bin/python -m pytest agent/tests -q`
- Result: 836 passed, 1 skipped
- Command: `openspec validate --all --strict`
- Result: 16 passed, 0 failed
- Command: `npm --prefix frontend run verify`
- Result: passed（Task 8，review 修复未触及 frontend）
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: exit 0（pytest + Eval 7/7 + 13/13 + 9/9 + 6/6 + 3/3 + openspec 16）
- Command: `grep -c '\- \[ \]' tasks.md`
- Result: 0（全部勾选）
- Code Review: 0 Critical / 3 Important 全部修复 / 4 Minor（2 已修，2 接受）
- 验证报告: `docs/superpowers/reports/2026-08-03-sap-nexus-governed-context-registry-snapshot-verify.md`

### Blockers

- 无

### Next Start Here

1. Runbook 14 (`14-governed-intent-capability-recall.md`) — LLM-first IntentEnvelope 和 governed closed-set capability recall。
2. 不得跳到 PlanExecutor、OutputProjection 或 WRITE。
3. 复用本 change 建立的 `GovernedContext` / `SnapshotLease` / `VisibleCapabilitySet` / `PlannerFailure` 数据结构；新增 visibility 维度或 snapshot lease 生命周期改动须另立 change。

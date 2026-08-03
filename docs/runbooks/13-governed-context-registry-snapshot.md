# Governed Context and Registry Snapshot Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `13-governed-context-registry-snapshot` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | P0B trusted principal and durable runtime foundation (archived) |
| Unblocks | Runbooks 14-22 |

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

以独立 Comet change 实施本 runbook；完成并归档后进入 Runbook 14。不得把 recall、PlanExecutor 或 UI 工作夹带进本 change。

# End-to-End Agent Eval and Release Gate Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `22-end-to-end-agent-eval-release-gate` |
| Version | `v0.2.0` |
| Status | `Completed / Archived` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbooks 13-21 |
| Change | `sap-nexus-end-to-end-agent-eval-release-gate` |
| Archive | `docs/comet/archive/2026-08-05-sap-nexus-end-to-end-agent-eval-release-gate/` |
| Unblocks | 完整 Agent MVP 的离线发布判断与后续独立量产评估 |

## 1. Goal

建立完整 Agent 的端到端 Eval、回归和发布门禁，分别证明单能力、多 READ 和 READ-to-WRITE 三个成熟度等级，不以 UI 标签、静态 fixture、平均分或单次 demo 代替执行证据。

## 2. Implemented Runtime

- Python Agent 继续负责 LLM-first intent、closed-set recall、五态 `MatchDecision` 与 PlanGraph v2 authoring。
- TypeScript `CompositionCoordinator` 只接收同 snapshot、无 gap、schema-valid 的 `ESCALATE_TO_PLANNER` handoff，并复用现有 PlanExecutor、FactBuilder、OutputProjection、Recommendation、Narrative 与 durable event projector。
- L2 完成两个 READ 节点到 `MaterialSupplySnapshot`、Recommendation、grounded Narrative、durable replay 与 Workbench state 的生产接线。
- L3 复用 Runbook 21 的 `PlanActionContinuation`；未审批时 WRITE execute 为 0，精确审批后的 fake/sandbox Action 最多执行一次，重复 continuation 只返回 durable result。
- `npm --prefix frontend run release-gate -- --profile L1|L2|L3|all` 输出机器可读 report 到 gitignored `runtime/evals/results/`。

## 3. Offline Maturity Result

| Level | Offline result | Execution evidence |
|---|---|---|
| L1 | `passed` | 现有 Python Agent Eval `13/13`，覆盖单 capability decision、CallPlan、fake Gateway、Fact/Narrative 与前置拦截 |
| L2 | `passed` | 真实 production coordinator boundary + Fake READ Gateway；projection `complete`，lineage `32/32`，9 个 narrative claims 均 grounded，durable replay 不重复 READ |
| L3 | `passed` | 同一 coordinator + `PlanActionContinuation` + fake/sandbox ActionGateway；未审批 WRITE `0`，审批与重复 continuation 后 WRITE 总计 `1` |

最高连续通过等级为 `L3_ACTION_GOVERNED`。该结论只表示 **offline fake/sandbox evidence** 已通过，不表示 live SAP multi-READ 或 live SAP WRITE 已执行。

## 4. Eval Matrix and Hard Gates

版本化 fixtures 覆盖 deterministic、recorded-LLM metadata 与真实 coordinator E2E 三类，并标注 matcher、planner、executor、projection、recommendation、narrative、approval、Workbench、security 和 operations 风险。

| Hard gate | Required | Observed |
|---|---:|---:|
| `visibilityLeakageRate` | `0` | `0` |
| `writeApprovalBypassRate` | `0` | `0` |
| unsupported narrative claim rate | `0` | `0` |
| fact lineage completeness | `100%` | `100%` |

任一 hard gate、missing/stale evidence 或较低等级失败都会阻止对应等级及更高等级；不能用其他 case 分数抵消。

## 5. Safety and Release Boundaries

- Gateway 仍只接收注册 `capabilityId`，不接收 request/model 提供的 RFC、binding、URL、SQL 或 credential。
- READ 不调用 commit/rollback；WRITE 未经 recorded exact-subject Human Approval 不执行。
- Offline runner 不访问 live LLM 或 SAP；recorded-LLM fixture 只验证版本化的脱敏模型响应元数据。
- live SAP READ/WRITE smoke 均为 `not_run`；本 change 没有 live WRITE 授权，也没有执行 live SAP WRITE。
- Knowledge/RAG、embedding/vector store、自由 Tool Calling、通用 Dynamic Planner、多 WRITE/Saga、自动补偿和 multi-worker/HA shared store 均不在本 change。

## 6. Acceptance Result

- 三个 level 均有 deterministic、recorded-LLM 和 coordinator E2E case，共 `9/9` passed。
- 两次真实 CLI report 删除 `startedAt/completedAt` 后 normalized JSON 完全一致。
- report 包含 schema/profile/code/snapshot/fixture versions、case totals、failures、metrics、hard gates、evidence refs、decision 和 `liveSmoke.status=not_run`。
- Workbench state 只由 durable events 投影；重复 load/reconnect 不增加 READ/WRITE execute count。
- report 与 committed fixtures 不含 credential、raw model response 或 raw SAP payload。

## 7. Verification

```bash
npm --prefix frontend run verify
.venv/bin/python -m pytest agent/tests -q
scripts/verify-agent-callplan-evidence.sh
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json
openspec list --json
openspec validate --all --strict
npm --prefix frontend run release-gate -- --profile all
git diff --check
git status --short
```

Final evidence accepted by Native Verify:

- frontend: `50` files / `428 passed`; Next.js production build passed。
- Agent: `959 passed, 1 skipped`。
- call-plan evidence: `7/7 + 13/13 + 9/9 + 10/10 + 3/3`; one documented pending dry-run fixture remains covered by unit test。
- OpenSpec: `20 passed, 0 failed`。
- release gate: `9/9`, `L3_ACTION_GOVERNED`, live smoke `not_run`; two normalized reports matched。
- Native acceptance: `42/42` fresh typed receipts; Verify passed and the change was archived。

## 8. Next Start Here

1. 常规离线发布判断运行 `npm --prefix frontend run release-gate -- --profile all`，并审查 gitignored report。
2. live SAP READ/WRITE smoke 不是本 runbook 的自动下一步；只有新的精确授权和独立证据计划才可运行，live WRITE 仍需 exact-subject Human Approval。
3. 后续量产工作应另立 change，重点是 shared durable store、multi-worker/HA、real identity provider、observability 与独立 live-smoke policy；不得把本次 offline L3 直接改写成 live SAP 成熟度。

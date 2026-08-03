# End-to-End Agent Eval and Release Gate Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `22-end-to-end-agent-eval-release-gate` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbooks 13-21 |
| Unblocks | 完整 Agent MVP 发布与后续扩展评估 |

## 1. Goal

建立完整 Agent 的端到端 Eval、回归和发布门禁，分别证明单能力、多 READ 和 READ-to-WRITE 三个成熟度等级，不以 UI 标签或单次 demo 代替执行证据。

## 2. Current Baseline

- 已有 inventory、seed、PO、matcher、dry-run、PR 与 narrative eval，以及 OpenSpec/verify script 门禁。
- 缺少覆盖 PlanExecutor、OutputProjection、Recommendation、NarrativeEnvelope、plan-aware approval、reconnect/replay 的统一 release suite。

## 3. Maturity Levels

| Level | 场景 | 必须证明 |
|---|---|---|
| L1 | 单 capability | LLM-first intent、五态决策、CallPlan、Gateway、Fact、Narrative 不回退 |
| L2 | 多 READ | 同 snapshot 召回/规划、DAG 执行、partial semantics、projection lineage、grounded narrative |
| L3 | READ-to-WRITE | RuleSet/Recommendation、单 Action proposal、Human Approval、exactly-once Action、完整 replay |

## 4. Eval Matrix

覆盖 matcher、planner、executor、projection、recommendation、narrative、approval、Workbench、security 和 operations。至少包含：未知/不可见 capability、prompt injection、缺参数、snapshot drift、节点超时/取消/恢复、partial fact、freshness mismatch、缺规则输入、unsupported claim、approval bypass、hash drift、重复 continuation、cross-principal、SSE reconnect 与 event replay。

## 5. Safety and Release Boundaries

- 任一 hard gate 失败即不发布；不能用平均分抵消安全失败。
- `visibilityLeakageRate=0`、`writeApprovalBypassRate=0`、unsupported narrative claim rate `0`、fact lineage completeness `100%`。
- L2 未通过时只能发布 L1；L3 未通过时只展示 Action proposal，不开放执行。
- Knowledge/RAG 未接入，不得在 release claim 中宣称知识召回能力。

## 6. Acceptance Criteria

- 三个 level 各有 deterministic fixtures、LLM recorded fixtures 和至少一个端到端 scenario。
- 每次回归输出版本、snapshot、case totals、failures、trace/evidence refs 和 release decision。
- Workbench 显示状态与 durable ledger/Gateway/approval 证据一致。
- 全量 suite 可离线运行；live SAP READ/WRITE smoke 与离线 gate 分开授权和记录。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests -q
npm --prefix frontend run verify
scripts/verify-agent-callplan-evidence.sh
openspec list --json
openspec validate --all --strict
git diff --check
```

## 8. Next Start Here

为 L1/L2/L3 分别建立 release profile 和证据报告模板。全部 hard gates 通过后，才可将 README/roadmap 的完整 Agent 状态从 `Planned` 更新为已实现；否则保留实际成熟度。

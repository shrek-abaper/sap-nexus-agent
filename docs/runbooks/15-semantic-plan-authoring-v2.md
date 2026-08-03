# Semantic Plan Authoring v2 Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `15-semantic-plan-authoring-v2` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbooks 13-14; S1/S2-B archived foundation |
| Unblocks | Runbook 16 |

## 1. Goal

把 advisory `GoalSpec` / `PlanDraft` 收敛为可执行前验证的 `PlanGraph` v2，完整表达参数来源、能力关系、projection/rule 引用以及 READ/WRITE 分区。

## 2. Current Baseline

- S1 已有 Fact Type、Capability Relation、GoalSpec、PlanGraph、snapshot 和 deterministic validator。
- S2-B 已有 progressive cards 与 dry-run compiler，但当前主要按 desired Fact producer 选节点，尚不执行。
- 当前 graph 未形成 projection/rule/action proposal 的完整下游引用；关系和参数来源覆盖仍需扩大。

## 3. Contracts and Data Flow

```text
IntentEnvelope + MatchDecision handoff + RegistrySnapshot
-> GoalSpec candidate
-> PlanDraft candidate
-> deterministic relation expansion and parameter binding
-> validation report
-> PlanGraph v2 { readPartition, actionPartition, projectionRef, ruleSetRefs }
```

参数来源只能是 `goalConstraint`、approved literal、validated `factField` 或 registered default。每条 edge、projection 和 RuleSet 都必须来自 snapshot。validation failure 必须保留明确 issues，不能只返回 `None`。

## 4. Scope and Non-goals

- Scope：PlanGraph v2 schema/compiler/validator、关系解析、参数 provenance、READ/WRITE partition、结构化 gaps/failures。
- Non-goal：不执行 Gateway、不调度节点、不计算建议、不批准或执行 Action、不做自由动态 replan。

## 5. Safety Boundaries

- LLM 不得创建 capability、relation、Fact Type、projection 或 RuleSet。
- 未注册节点、循环、类型不兼容、缺参数来源、snapshot 漂移一律 invalid。
- Action 节点必须单独分区并带 `requiresApproval=true`；不得混入 READ execution set。

## 6. Acceptance Criteria

- 首个双 READ 场景生成稳定、可重复的 PlanGraph v2。
- unknown capability/relation、cycle、type mismatch、missing source、snapshot drift 和 Action-in-READ bad case 全部 fail-closed。
- dry-run 可展示 plan、gaps、governance、projectionRef 和 ruleSetRefs，且不调用 Gateway。
- v1 fixtures 保持兼容或提供显式迁移器。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py -q
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

PlanGraph v2 contract 与 fixtures 归档后，Runbook 16 才可消费。不得在 compiler change 内偷渡执行代码。

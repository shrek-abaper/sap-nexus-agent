# Semantic Plan Authoring v2 Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `15-semantic-plan-authoring-v2` |
| Version | `v0.2.0` |
| Status | `Implemented / Archived` |
| Created / Updated | `2026-08-04` |
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

## Session Closeout - 2026-08-04

### Completed

- **Task 1 (v2 schema)**: `schemas/plan-graph-v2.schema.json` 新增，含 `planGraphVersion: 2`、`readPartition`、`actionPartition`、`projectionRef`、`ruleSetRefs` 及 `registeredDefault` 参数源种类；v1 schema 与 fixtures 零改动。
- **Task 2 (v2 契约类型)**: `semantic_planning` 新增 v2 PlanGraph 契约类型（分区结构 + `registeredDefault` 源种类 + `PlanCompileResult` / `PlanValidationReport`）。
- **Task 3 (v2 validator)**: `validate_plan_graph_v2` 复用 S1 `validate_plan_graph` 校验原语（provenance / edges / cycle / topological order / governance / snapshot / goalOutputs）并扩展分区隔离校验与 `projectionRef` / `ruleSetRefs` 引用校验。
- **Task 4 (partition 隔离)**: Action / 非 read-only 节点 MUST NOT 出现在 `readPartition`；`projectionRef` / `ruleSetRefs` 非空时引用实体 MUST 来自 snapshot。
- **Task 5 (ref 校验)**: `projectionRef` / `ruleSetRefs` 为空时通过（本期默认空）。
- **Task 6 (v2 compiler 入口)**: `compile_plan_v2` 消费 `EscalationHandoff` + `RegistrySnapshot` + `SemanticSourceDocuments`，绑定与 matcher 相同的 `snapshotId`；在 `goalConstraint` 之外 author `literal` / `factField` / `registeredDefault` 参数源。
- **Task 7 (data edge)**: 为 `factField` 绑定 author `data` edge。
- **Task 8 (dependency edge)**: 为 snapshot `dependsOn` 关系 author `dependency` edge（`fromNodeId` = prerequisite）。
- **Task 9 (edge authored from snapshot only)**: LLM 不得创建 capability / relation / Fact Type / projection / RuleSet；edge 由 S1 契约驱动。
- **Task 10 (partition by topologicalOrder)**: 节点按 topologicalOrder 排序后分区到 `readPartition`（READ-only）与 `actionPartition`（Action / write，`requiresApproval=true`）。
- **Task 11 (structured gaps + snapshot drift)**: 编译失败返回结构化 gaps / failures（error code、JSON Pointer path、message），不返回 `None`；snapshot 漂移返回 `PlannerFailure(SNAPSHOT_DRIFT)`。
- **Task 12 (dry-run)**: v2 dry-run 输出携带 plan / gaps / governance / `projectionRef` / `ruleSetRefs` / `snapshotId`，不调用 Gateway validate / execute，不调用 SAP。
- **Task 13 (fail-closed bad cases)**: unknown capability / relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ 全部 fail-closed 并带结构化 issues。
- **Task 14 (dual READ fixture)**: `MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList` 生成稳定可重复的 PlanGraph v2（`readPartition` 含两节点，`actionPartition` 空，refs 空）。
- **Task 15 (dry-run output tests)**: plan / gaps / governance / `projectionRef` / `ruleSetRefs` 齐全，无 Gateway 调用。

### Verified

- Command: `.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py agent/tests/test_semantic_planning_v2.py agent/tests/test_planner_plan_compiler_v2.py -q`
- Result: 330 passed (v1 298 + v2 32)
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: 953 passed, 1 skipped；Eval 7/7 + 13/13 + 9/9 + 10/10 + 3/3 通过
- Command: `openspec validate --all --strict`
- Result: 18 passed, 0 failed

### Deferred

- **`projectionRef` / `ruleSetRefs` 实际引用绑定**: 本期字段已定义并校验非空时来自 snapshot，但 fixture 中默认空；Runbook 17/18 消费时填充实际 projection / RuleSet 引用。
- **`registeredDefault` 实际默认值解析**: schema 与 compiler 已支持 `registeredDefault` 源种类，但本期 fixture 未覆盖实际默认值解析路径；后续 capability 提供默认值后补测。
- **Multi-turn / cross-partition eval cases**: eval runner 为单轮；跨分区 Action proposal eval 需 Runbook 21 配合。

### Next Start Here

1. Archive the OpenSpec change `sap-nexus-semantic-plan-authoring-v2`.
2. Begin Runbook 16 (read plan executor) - execute validated READ DAG with ready-node scheduling and durable ledger.
3. Optionally: schedule `projectionRef` / `ruleSetRefs` binding follow-up once Runbook 17/18 land.

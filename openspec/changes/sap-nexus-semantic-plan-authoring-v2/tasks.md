## 1. PlanGraph v2 Schema

- [x] 1.1 新建 `schemas/plan-graph-v2.schema.json`，含 `planGraphVersion: 2`、`readPartition`、`actionPartition`、`projectionRef`、`ruleSetRefs`，以及 `registeredDefault` 参数源种类（v1 的 node/edge/topologicalOrder/goalOutputs 字段保留）
- [x] 1.2 验证 v1 `schemas/plan-graph.schema.json` 未改动，且 v1 fixtures 仍能通过其校验

## 2. v2 契约与校验器

- [x] 2.1 在 `semantic_planning` 中新增 v2 PlanGraph 契约类型（分区结构 + `registeredDefault` 源种类）
- [x] 2.2 实现 v2 validator，复用 S1 `validate_plan_graph` 校验原语（provenance、edges、cycle、topological order、governance、snapshot、goalOutputs）
- [x] 2.3 新增分区隔离校验：Action / 非 read-only 节点 MUST NOT 出现在 `readPartition`
- [x] 2.4 新增 `projectionRef` / `ruleSetRefs` 引用校验：非空时引用实体 MUST 来自 snapshot；为空时通过（本期默认）

## 3. v2 确定性编译器

- [ ] 3.1 实现 v2 compiler 入口，消费 `EscalationHandoff` + `RegistrySnapshot` + `SemanticSourceDocuments`，绑定与 matcher 相同的 `snapshotId`
- [ ] 3.2 在 `goalConstraint` 之外，author `literal`、`factField`、`registeredDefault` 参数源
- [ ] 3.3 为 `factField` 绑定 author `data` edge，为 snapshot `dependsOn` 关系 author `dependency` edge
- [ ] 3.4 将节点分区到 `readPartition`（READ-only）与 `actionPartition`（Action / write，`requiresApproval=true`）
- [ ] 3.5 编译失败时返回结构化 gaps / failures，含明确 issues（error code、JSON Pointer path、message）；不得返回 `None`
- [ ] 3.6 snapshot 漂移时返回结构化 `PlannerFailure(SNAPSHOT_DRIFT)`（复用 Runbook 13 模式）

## 4. v2 dry-run 输出

- [ ] 4.1 暴露 v2 dry-run 输出，携带 plan、gaps、governance、`projectionRef`、`ruleSetRefs`、`snapshotId`
- [ ] 4.2 验证 v2 dry-run 不调用 Gateway validate / execute，不调用 SAP

## 5. 测试与 fixtures

- [ ] 5.1 双 READ fixture（`MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList`）生成稳定可重复的 PlanGraph v2（`readPartition` 含两节点，`actionPartition` 空，refs 空）
- [ ] 5.2 bad-case 测试：unknown capability、unknown / inconsistent relation、cycle、type mismatch、missing source、snapshot drift、Action-in-READ，全部 fail-closed 并带结构化 issues
- [ ] 5.3 dry-run 输出测试：plan / gaps / governance / `projectionRef` / `ruleSetRefs` 齐全，无 Gateway 调用
- [ ] 5.4 v1 回归：`test_semantic_planning_contract.py` 与 `test_planner_plan_compiler.py` 不改动仍通过

## 6. 验证与文档

- [ ] 6.1 `pytest agent/tests/test_semantic_planning_contract.py agent/tests/test_planner_plan_compiler.py`（+ 新 v2 测试）全绿
- [ ] 6.2 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 6.3 `openspec validate --all --strict` 通过
- [ ] 6.4 更新 Runbook 15 状态 / 版本 + `docs/runbooks/README.md` + roadmap row 26

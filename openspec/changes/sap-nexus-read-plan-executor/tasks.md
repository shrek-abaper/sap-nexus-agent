## 1. PlanGraph v2 消费契约（Python -> Node）

- [ ] 1.1 确定并实现 Python -> Node 的 PlanGraph v2 传递契约（现有 dry-run outcome 是否已携带可消费 plan_graph，或新增 executor 输入契约）
- [ ] 1.2 Node 侧实现 PlanGraph v2 反序列化与 `readPartition` / 节点 / edges / `snapshotId` 解析
- [ ] 1.3 校验 PlanGraph v2 有效性 + `snapshotId` 未漂移，无效/漂移 fail-closed 并记录结构化失败

## 2. 节点状态机 + durable node ledger

- [ ] 2.1 实现 9 态节点状态机（`READY` / `VALIDATING` / `EXECUTING` / `SUCCEEDED` / `FAILED` / `TIMED_OUT` / `CANCELLED` / `BLOCKED_DEPENDENCY` / `BLOCKED_APPROVAL`）与合法转换表
- [ ] 2.2 扩展 `CheckpointRef.nodeState` 落盘节点状态（sequence / attempt / input hash / result ref / trace span），复用 `DurableRunStore`，不建第二套 store
- [ ] 2.3 非法状态转换 fail-closed 并记录非法尝试

## 3. Ready-node 调度 + DAG 并发

- [ ] 3.1 实现 ready-node 选择：依赖闭包（基于 edges）全部 `SUCCEEDED` 才 `READY`，否则 `BLOCKED_DEPENDENCY`
- [ ] 3.2 实现 DAG 独立性决定的有限并发调度
- [ ] 3.3 双 READ 节点（`MM.Inventory.GetAvailability` + `MM.PurchaseOrder.GetList`）并发执行场景验证

## 4. Per-node Gateway validate/execute

- [ ] 4.1 实现 per-node Gateway `validate -> execute`（复用现有 Gateway，不绕过、不批量端点）
- [ ] 4.2 validate 失败节点转 `FAILED`，不调 execute，独立节点继续
- [ ] 4.3 Action / 非 read-only 节点保持 `BLOCKED_APPROVAL`，不执行、不调 Gateway execute

## 5. 超时与取消

- [ ] 5.1 实现节点级超时 -> `TIMED_OUT`，不阻塞独立节点
- [ ] 5.2 实现用户取消 -> 未完成节点 `CANCELLED`，`SUCCEEDED` 保留

## 6. 恢复与幂等重放

- [ ] 6.1 实现 restart 恢复：从 durable ledger 加载，`SUCCEEDED` 不重复执行，`READY`/未完成续跑
- [ ] 6.2 实现幂等重放：相同 idempotency key 不重复执行节点，返回已记录结果
- [ ] 6.3 lease conflict fail-closed（另一 worker 持有 lease 时拒绝操作并记录）

## 7. Per-node SSE 事件

- [ ] 7.1 新增 per-node SSE 事件类型（`node_ready` / `node_validating` / `node_executing` / `node_succeeded` / `node_failed` / `node_timed_out` / `node_cancelled` 等）
- [ ] 7.2 复用现有 SSE 框架，不破坏 `emitEventsFromOutcome` 单能力事件

## 8. 测试（TDD：fake Gateway 先行）

- [ ] 8.1 fake Gateway 完成状态机转换测试（9 态 + 非法转换 fail-closed）
- [ ] 8.2 fake Gateway 完成恢复测试（restart 跳过 `SUCCEEDED`、续跑 `READY`、幂等重放）
- [ ] 8.3 fake Gateway 完成调度测试（双 READ 并发、dependency 阻塞、超时、取消、partial failure、lease conflict）
- [ ] 8.4 接现有 READ integration（真实 Gateway validate/execute，受控 capability）
- [ ] 8.5 v1 回归：现有 orchestrator / call_plan / durable 测试不改动仍通过

## 9. 验证与文档

- [ ] 9.1 `.venv/bin/python -m pytest agent/tests -q` + `npm --prefix frontend run verify` 全绿
- [ ] 9.2 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 9.3 `openspec validate --all --strict` 通过
- [ ] 9.4 更新 Runbook 16 状态/版本 + `docs/runbooks/README.md` + roadmap row 27

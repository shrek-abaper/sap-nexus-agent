# Outcome

WRITE 的状态迁移链从"进程内旁路 trace 文件"升级为 **ApprovalRecord 的一等、不可变、可持久化
回放字段**：每条迁移记录 `from_state → to_state + event + timestamp + actor + evidence_ref`，
可直接随审批记录按 approval_id 读取回放。用户可见行为不变。

# Scope

1. **StateTransition 值对象**（frozen）：`from_state / to_state / event / timestamp /
   actor / evidence_ref`；evidence_ref 为触发该迁移的证据引用（gateway validate/execute
   trace、SAP 执行回执等），只存引用不复制载荷。
2. **ApprovalRecord 增加 `transitions` 字段**（tuple，append-only）：
   - create 时记录初始 `→ pending` 事件；
   - approve / reject / mark_executed 在 `_transition` 内统一追加迁移；
   - to_dict/from_dict 完整序列化，旧记录（无该字段）反序列化兼容为空链。
3. **evidence_ref 接线**：在切换点把可得证据引用（trace id / execution）记入迁移；
   执行路径（continue_action）传入执行回执引用。
4. 提供按 approval_id 读取迁移链的能力（记录自带，无需读 trace 目录）。

# Non-goals

- 不改 ApprovalState 四态、状态合法性、Gateway、审批门禁、确定性补货、MatchDecision；
- 迁移链是审计/证据产物，不参与授权决定（resolve/enforce 边界不变）；
- 不重构 READ 状态机、不做 Change Propagation、不做跨写入编排/补偿事务；
- 现有文件 trace（runtime/traces）本项不强制删除（保留为既有行为；如移除另议）。

# Acceptance examples

- 创建审批：transitions 含 1 条 `None→pending`；
- approve 后：追加 `pending→approved`，带 approver 与证据引用；
- continue_action 执行成功并 mark_executed：追加 `approved→executed`，evidence_ref 指向执行回执；
- reject：追加 `pending/approved→rejected`；
- 旧 ApprovalRecord JSON（无 transitions）：from_dict 成功，transitions=() ；
- 链只追加，无任何条目可被修改或删除。

# Constraints and invariants

- transitions 不可变、只追加；顺序即真实迁移顺序；
- 持久化向后兼容；evidence_ref 只存引用；
- 迁移记录不携带参数明文/敏感载荷（沿用 parametersSummary 式最小信息原则）。

# Decisions

- D1（用户确认方向 A）：只给 WRITE 做迁移链，READ 不纳入；
- D2（Shape 核查后的事实修正）：WRITE 已有文件 trace 形式的迁移日志，**不重复造日志**；
  本项真实缺口是 (a) 链未随 ApprovalRecord 持久化/无法按 id 回放、(b) 缺 evidence_ref、
  (c) trace 位置与记录生命周期不绑定。故工作收敛为"内化持久化 + 证据引用"。

# Open questions

无用户决策待澄清。CONFIRM 已获用户确认（2026-09-25）。

# Verification expectations

- 全量 agent 测试 + 全部 evals 绿；现有行为不变；
- 每次状态切换产生一条带 evidence_ref 的迁移记录，链序与 from/to/event 正确；
- transitions 随记录持久化、可按 approval_id 回放；旧记录反序列化兼容。

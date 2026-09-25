# Outcome

提供只读的 **Change Impact Analysis**：给定一条业务规则或一个语义类型/shape 的变更，
确定性地列出受影响的能力、FactType 与当前活跃在途审批。它是 Change Propagation 的
"Impact Analysis"段；不自动重算、不改任何状态。

# Scope

1. **ImpactGraph 构建**（确定性，可由 registry + business-rules 重建）：
   - 规则节点经 `scope.capabilityId` 连到能力；
   - 能力连到其输出 factType（outputs.factTypeRef）与输入 semanticType；
   - 沿 `satisfiableByFactType` 建立 factType → 下游消费能力的边（传递传播）。
2. **analyze_change API**：输入 ruleId 或 semanticType，返回
   - `affected_capabilities`（含传递可达）；
   - `affected_fact_types`；
   - `affected_approvals`：活跃审批 store 中参数/快照与受影响能力相关者
     （capability_id 命中，或参数键属于受影响能力的输入）。
3. 纯只读、无网络/SAP 访问；结果标注"建议复核"，不触发重算。
4. 图生成纳入一致性校验（可重建，确定性，同输入同结果）。

# Non-goals

- 不做自动重算/重新分类、不要求历史事实携带 ruleVersion provenance；
- 不改 MatchDecision、Gateway、审批门禁、WRITE 迁移链、补货逻辑；
- 分析报告不参与授权（resolve/enforce 边界不变）。

# Acceptance examples

- 变更 rule `pr-quantity-is-supply-gap`：受影响能力含 MM.PR.CreateDraft，
  fact type 含 PurchaseRequisitionCreatedFact；当前若有该能力 pending approval 则列入；
- 变更 semanticType `sapnexus:MaterialNumber`：所有以该类型为输入的能力可达；
- 变更一个 fact type：经 satisfiableByFactType 传播到下游消费能力；
- 无相关变更对象：三个集合均为空，不报错。

# Constraints and invariants

- 影响图只读、确定性；传递闭包计算正确且可复现；
- 不访问第三方系统；affected_approvals 只从审批 store 读取。

# Decisions

- D1（用户授权，自主决策）：只实现 Impact Analysis，不做完整自动传播
  （依据：当前无跨版本事实留存，自动重算会空转）。

# Open questions

无。CONFIRM 基于用户预授权（自主完成剩余项、不再确认）。

# Verification expectations

- 全量 agent 测试 + 全部 evals 绿；行为不变；
- 规则/类型变更的影响集合（含传递）正确可复现；活跃 approval 识别正确。

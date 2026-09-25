# Change Impact Analysis

## Purpose

在不自动重算的前提下，回答"一条规则或语义类型变更会影响哪些能力、FactType 与活跃在途审批"，
作为 Change Propagation 的只读 Impact Analysis 基础。

## Requirements

### Requirement: 确定性影响图

系统 SHALL 从 registry 与 business-rules 构建影响图：规则经 scope.capabilityId 连到能力，
能力连到输出 factType 与输入 semanticType，并经 satisfiableByFactType 连到下游消费能力。
同输入构建结果 MUST 确定、可复现。

### Requirement: 变更影响分析

系统 SHALL 接受 ruleId 或 semanticType 作为变更入口，返回其传递闭包内的
`affected_capabilities`、`affected_fact_types` 与 `affected_approvals`。
affected_approvals MUST 从审批 store 只读识别（capability 命中或参数键属于受影响能力输入）。

### Requirement: 只读且不触发传播

分析 MUST NOT 修改状态、触发重算或访问 SAP/网络；其结果仅为"建议复核"报告，
不参与授权决定。

## Non-goals

- 历史事实版本 provenance、自动重算/重新分类；
- 替换 MatchDecision、Gateway、审批门禁、WRITE 迁移链、补货逻辑。

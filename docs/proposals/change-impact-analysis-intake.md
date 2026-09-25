# Phase 4 立项输入：Change Impact Analysis（Change Propagation 的可落地部分）

- **信号**: HEAVY（新增分析能力，跨 registry/approval）
- **用户授权**: 自主完成，不再中途确认；Jev 除外

## 背景与判断

完整 Change Propagation（语义变更后自动重算历史事实）在当前系统会空转：
影响分析要求持久化事实携带"规则+版本"provenance，而当前 Facts 无跨版本留存，
且只有单一 registry 版本、无"旧规则产物仍存活"的真实对象。
故本项只做 Change Propagation 中有独立价值的 **Impact Analysis** 段，不做自动重算。

## 本次范围

1. **静态影响图**：在 registry/规则目录建立"规则/语义定义 → 其影响的能力/FactType"
   依赖声明（从现有 business-rules + capability 输入输出推导，可确定性生成）。
2. **影响分析 API**：给定一个变更（rule id / 输入语义类型 / shape），返回
   受影响的 capability、factType，以及当前活跃 approval store 中引用这些对象的
   在途审批（按 parameterSnapshotHash/参数键识别）；纯只读。
3. 输出分级：`affected_capabilities / affected_fact_types / affected_approvals`，
   只报告范围与"建议复核"，**不触发重算、不改状态**。
4. codegen/校验：影响图可由 registry 确定性重建，纳入现有 --check 风格一致性校验。

## 明确不变

- MatchDecision、Gateway、审批门禁、WRITE 迁移链、确定性补货全部不动；
- 不要求历史事实带版本 provenance、不做自动重算/重新分类；
- 分析结果是报告，不参与授权（resolve/enforce 边界不变）。

## 成功判据

- 全量 agent 测试 + 全部 evals 绿；行为不变；
- 对一个规则/类型变更，影响集合正确（含传递依赖）、可复现；
- 活跃 approval 受影响识别正确，无第三方数据访问。

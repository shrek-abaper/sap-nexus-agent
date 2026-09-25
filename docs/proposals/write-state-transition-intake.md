# Phase 3 立项输入：WRITE 状态迁移链（Event/State）

- **用途**: 通过 `/comet` 立项时引用
- **信号**: HEAVY（动 approval/WRITE 生命周期）

## 背景

WRITE 生命周期目前由 `ApprovalRecord` 的 4 个**当前状态**承载（pending → approved →
executed / rejected），但只保留"现在是什么态"，**没有记录状态迁移的因果链**：
什么事件（审批通过 / SAP 执行回执 / 拒绝 / 过期失效）在何时、依据什么证据，
把对象从 state(t) 推到 state(t+1)。涉及 SAP 实际写入，出问题时无法回放"为什么变成这样"。

READ 侧为只读，现有 frame status + provenance 已够，不纳入本次。

## 本次范围（最小 A）

1. 新增不可变的 WRITE **状态迁移链**：每条记录
   `from_state → to_state`、`event`、`timestamp`、`actor`、
   `evidence_ref`（gateway trace / approval / fact 回执的引用）；
2. 在现有状态切换点（approve / reject / mark_executed、以及过期/失效）追加迁移记录，
   **复用现有 4 态与全部执行逻辑，不重写控制流**；
3. 迁移链只追加（append-only）、不可变；支持按 approval_id 读取整条链；
4. 持久化与序列化纳入 approval store（to_dict/from_dict 兼容，旧记录迁移链为空）。

## 明确不变

- ApprovalState 四态、Gateway、审批门禁、确定性补货、MatchDecision 全部不动；
- 迁移链是**证据/审计产物**，不参与授权决定（resolve/enforce 边界不变）；
- 不重构 READ 状态、不做 Change Propagation、不做跨写入编排/补偿事务。

## 成功判据

- 全量 agent 测试 + 全部 evals 绿；现有行为完全不变；
- 每个 WRITE 状态切换都产生一条迁移记录，链序、from/to、事件与证据引用正确；
- 链不可变、可按 approval_id 回放；旧 ApprovalRecord 反序列化兼容。

## 风险点（Build 重点）

- 持久化格式向后兼容（无 transitions 字段的旧记录）；
- 迁移记录在所有切换路径（含 continue_action 的 approve/reject、执行失败）上不遗漏；
- evidence_ref 只存引用，不复制敏感载荷。

# Phase 2 立项输入：selector missing 判定单一来源收敛

- **用途**: 通过 `/comet` 立项时引用
- **信号**: HEAVY（改核心 selector 决策逻辑）
- **前置**: Phase 1 已交付 `constraint_runtime.evaluate_preconditions`（缓存、已测）

## 背景

调查发现：selector 的 CLARIFY missing 判定，语义来源**已经是 registry/本体数据**，
但其内部对 required + derivable 的调和逻辑（capability_selector.py:302-343、
`_is_derivable_input`）与 Phase 1 的 `constraint_runtime.evaluate_preconditions`
是**同一规则的两份实现**，存在漂移风险。

## 本次范围

1. selector 的 missing 判定改为调用 `constraint_runtime.evaluate_preconditions`
   （required / requiredWhen / requireAny / fact-satisfiable 调和，已缓存）；
2. 删除 selector 内重复的 derivable/required 调和代码（含 `_is_derivable_input` 若无其他调用者）；
3. 保持决策结果等价：CLARIFY / SELECT / ESCALATE_TO_PLANNER（derivable 升级路径）行为不变；
4. resolve/enforce 不变：runtime 只解析，selector 仍负责决策与强制。

## 明确不变

- MatchDecision 五态、Gateway、WRITE 审批、确定性补货逻辑；
- LLM 路径下 missing 空时由 descriptor 补算的行为（确认 runtime 等价覆盖）；
- visibility 拒绝路径。

## 成功判据

- 全量 agent 测试 + 全部 evals 绿；missing 集合与改造前逐用例一致；
- derivable 升级（ESCALATE_TO_PLANNER）、LLM 补算、requireAny、条件前置均等价；
- selector 内无重复调和逻辑残留。

## 风险点（Build 重点验证）

- runtime 接收 governed 受限 sources 的语义（不可见 producer 不能消除 missing）；
- multi_parameters 提供键的合并；
- LLM 路径 missing 空但 required 未查的补算。

# Outcome

selector 的 CLARIFY missing 判定收敛为**单一权威来源**：由 `constraint_runtime` 统一解析
"必需且未提供"的入参并区分"可由上游推导 / 必须用户补充"，selector 只消费该解析结果做
CLARIFY / ESCALATE_TO_PLANNER / SELECT 路由。删除 selector 内重复的 required/derivable 调和代码。
用户可见行为完全不变。

# Scope

1. **扩展 constraint_runtime**：新增意图路由视角的解析，对给定能力与已提供键，产出
   - `missing_user`：必需、未提供、且受治理集合内不可自动推导的入参（→ CLARIFY）；
   - `missing_derivable`：必需、未提供、但可由受治理集合内自动拉取的生产者推导（→ ESCALATE）；
   推导判定复用 derive_data_dependencies + auto-pull 治理（生产者 active + READ，
   且在本次 governed sources 内），与现 selector 语义一致。
2. **selector 接线**：用 runtime 的分区替换 capability_selector.py:302-343 的内联调和；
   - missing_user 非空 → CLARIFY；
   - missing_user 空、missing_derivable 非空 → ESCALATE_TO_PLANNER；
   - 两者皆空 → 走现有 SELECT。
3. **删除重复逻辑**：selector 内 derivable/required 调和代码；`_is_derivable_input` 若无其他
   调用者则移除（其权威逻辑并入 runtime）。
4. 保持 rule 路径与 LLM 路径（missing 空时 descriptor 补算）、multi_parameters 合并、
   requireAny、条件前置 requiredWhen 的现有行为。

# Non-goals

- 不改 MatchDecision 五态、Gateway、WRITE 审批、确定性补货；
- 不改变任一现有用例的决策结果（CLARIFY/ESCALATE/SELECT 逐用例等价）；
- 不做 Event/State、Change Propagation、Identity；
- resolve/enforce 边界不变：runtime 只解析，selector 决策与强制。

# Acceptance examples

- "建个采购申请"：material/plant/quantity/delivery_date 落入 missing_user → CLARIFY；
  unit/purchasing_group 为 derivable 但同时有 user 缺口 → 仍 CLARIFY；
- 语句只缺 unit/purchasing_group（其余必填齐全）：missing_user 空、missing_derivable 非空
  → ESCALATE_TO_PLANNER（与现 derivable 升级一致）；
- 全部必填已提供：两集合皆空 → SELECT；
- 可见性受限、生产者不在 governed 集合：该入参不判 derivable → 留 missing_user（fail closed）。

# Constraints and invariants

- derivable 的生产者可达性必须在**本次 governed sources** 内判定，不可读全量 registry；
- 推导判定是声明查询，无 Gateway/RFC/SAP 调用（沿用 invariant 2）；
- runtime 解析失败 fail closed（按用户需补充处理，不静默丢弃）。

# Decisions

- D1（用户已确认方向 A）：selector missing 收敛到单一来源，删除重复调和；
- D2（Shape 核查后的实现细化，替代 intake 的"直接调用 evaluate_preconditions"）：
  runtime 须新增**意图路由视角**的分区解析，而非复用执行边界视角的 evaluate_preconditions。
  原因（两个语义陷阱，已核实）：
  1. evaluate_preconditions 把 fact-satisfiable 入参视为"执行边界已满足"，会把
     "需规划器推导"（ESCALATE）误判为 SELECT；
  2. 其 fact_satisfiable 只看消费者自身声明，不查 governed 集合内生产者可达性，
     可见性受限时会错误消除 missing。
  行为保持不变，仅扩展内部 API。

# Open questions

无用户决策待澄清。CONFIRM 已获用户确认（2026-09-25）。

# Verification expectations

- 全量 agent 测试 + 全部 evals 绿；missing 分区与现 selector 逐用例一致；
- derivable 升级、LLM 补算、multi_parameters、requireAny、条件前置、受限生产者全部等价；
- selector 无重复调和逻辑；runtime 单一权威。

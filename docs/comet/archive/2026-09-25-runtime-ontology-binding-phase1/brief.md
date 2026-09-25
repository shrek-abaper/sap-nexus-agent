# Outcome

将"约束如何被运行时判定"从"手写 Python 解释 registry YAML"标准化为"构建时由 YAML 生成
标准 SHACL/SKOS 产物，运行时由标准引擎解析，确定性代码负责强制"。

用户可见行为不变：能力选择、参数澄清、校验拦截、补货提案、审批执行结果与改造前完全一致
（已由 shadow spike 的 28 用例五维度 100% 等价证明）。变化集中在约束解释器的实现形态。

# Scope

1. **codegen 正式化**：将 spike 的 `build_bundle.py` 提升为项目正式构建步骤；
   registry YAML 为唯一作者源 → 生成 SKOS + SHACL canonical bundle，产物按
   registrySnapshotId 绑定哈希，同输入可复现；新增"产物与 YAML 一致"的校验。
2. **参数校验标准化**：`_valid_semantic_input_value` 对长度/模式/类型的定制解释，
   改为由 **pyshacl** 对生成的 SHACL NodeShape 求值；两处调用点（批量 preflight、
   READ authority）统一切换。
3. **前置条件图查询解析器**：required / requiredWhen（含条件前置 K→cost_center、
   requireAny 分组）的图查询解析器建成并受测试；查询计划预编译/缓存。生产 selector 的
   CLARIFY 完全切换到图查询为紧邻下一增量（用户已确认选项 A），不在本次。
4. **resolve/enforce 分离**：图只产出"满足/不满足"的解析结果；拦截、控制流、副作用
   仍由现有确定性代码执行。

# Non-goals

- 不改 MatchDecision 五态决策、Gateway、WRITE 人工审批流程（ApprovalRecord 仍是
  执行唯一凭证）、确定性补货缺口算法；
- 不引入全量 Semantica 平台（仅用 rdflib + pyshacl 轻量组件）；
- 不做能力 SKOS 召回接入、WRITE ODRL 权限运行时绑定（属后续 Phase）；
- 不做 Event/State 状态迁移链、Change Propagation、跨系统 Identity（已登记为候选）；
- 语义层不持有任何 SAP 凭据、不直连 SAP。

# Acceptance examples

- 输入 `plant=5260`：SHACL 求值"满足 pattern ^[A-Z0-9]{4}$"→ 放行，行为同旧路径；
- 输入 `plant=12`：SHACL 报告 pattern 冲突 → 确定性代码拦截，行为同旧路径；
- 语句缺 material/plant：前置查询返回对应缺失项 → CLARIFY，与 engine 旧输出（执行边界口径）一致；
- 间采 K 未给成本中心：条件前置返回 cost_center 缺失 → CLARIFY；
- PR 审批缺失/过期/版本不符/重复提交：权限结果与改造前一致（True/False 不变）。

# Constraints and invariants

- registry YAML 为唯一人工作者源；生成产物不可手工编辑，须与快照哈希一致；
- WRITE 必须存在 recorded human confirmation，模型/本体结论不可豁免；
- 校验失败必须在到达 SAP 前拦截（validate-before-execute）；
- 控制流、权限、副作用留在确定性代码，图只 resolve；
- 依赖仅新增 rdflib、pyshacl（agent pyproject），不引入重型数据平台。

# Decisions

- D1（已确认）：采用 rdflib + pyshacl 轻量自建，不引入 Semantica 全平台
  （依据：spike 仅使用其能力小子集，且均可由标准轻量组件替代）；
- D2（已确认）：生成产物提交入库（仓库无运行时构建管线），由测试强制"产物与 YAML 同步"；
- D3（实现选择）：旧定制解释器在两处生产调用点切换并验证稳定后已删除；
  最终强制仍在确定性代码。
- D4（用户已确认，选项 A）：前置条件图解析器本阶段交付为受测试能力；selector
  CLARIFY 的生产切换列为下一增量。

# Open questions

无用户决策待澄清；intake 与既往讨论已解决全部实质性分叉。CONFIRM 已获用户确认（2026-09-25）。

# Verification expectations

- 全量 agent 测试与全部 evals 全绿；28 用例口径下行为与改造前一致；
- codegen 同输入哈希可复现；生成产物与 YAML 一致性校验通过；
- 前置/权限查询经计划缓存后延迟可接受（spike 未缓存约 40ms，缓存后须显著改善并实测记录）。

# Outcome

交付统一、确定性、可持久化的 READ 对话上下文治理：把 LLM 与历史内容降级为 advisory candidates，通过 typed `ReadContextFrame`、纯 `ContextReducer`、fail-closed decision gate 和 durable conversation protocol 管理槽位继承、替换、清空、冲突与确认，确保歧义输入不会生成错误 `CallPlan` 或到达 SAP。

# Scope

- 覆盖库存、采购订单以及后续所有已注册 READ capabilities；共用 `ConversationReadState`、`SlotBinding`、`PendingInteraction`、evidence arbitration 和 decision gate。
- Python Agent 负责候选提取、semantic validation、纯 Reducer、Frame-to-`MatchDecision` gate、resolution evidence 与 READ CallPlan authoring。
- TypeScript durable runtime 负责 versioned Session、conversation lease、`stateVersion` CAS、`turnId` 幂等以及 persist-before-execute 两阶段协议。
- Java Gateway 从 Registry 读取可选 input pattern，作为第二道防御校验；至少保证 READ capability 的 `plant="工厂"` 在 SAP 前返回 `INVALID_PARAMETER`。
- 先冻结真实失败证据并运行 Frame v2 shadow comparison，再将 Frame v2 切换为 READ 权威路径；所有 hard gates 通过后才移除生产中的 destructive `LastContext` merge/write bridge。
- 扩展 deterministic fixtures、recorded bad LLM payload、multi-turn Eval 与现有 release gate，使 false `SELECT`、non-READY Gateway call、wrong slot role、并发覆盖和 READ-to-WRITE authority leakage 成为不可抵消的 hard failures。

# Non-goals

- 不改变 `MM.PR.CreateDraft`、`ApprovalRecord`、Human Approval、PlanExecution、Action continuation 或 SAP WRITE 执行行为，也不从 READ 上下文推导 WRITE 权限。
- 不选择 PostgreSQL、Redis 或其他 multi-worker shared store 产品；JSON 文件实现继续作为 local/single-worker baseline。
- 不建立 embedding memory、跨 conversation 相似检索、自动历史 frame 恢复或长期用户偏好记忆。
- 不通过扩大 prompt/history 窗口、模型 confidence 投票或 SAP business error 自动交换 material/plant。
- 不允许模型、history、summary、Session 或请求提供 RFC、binding、URL、credential、principal、visibility 或 approval authority。
- 不自动运行 live LLM、live SAP READ 或任何 SAP WRITE smoke；未单独授权的 live smoke 必须记录为 `not_run`。

# Acceptance examples

- 输入 `DEMOA2 在工厂 5100 还有多少可用库存` 时，Frame 以 material=`DEMOA2`、plant=`5100` 进入 `READY`，唯一 READ CallPlan 可执行一次。
- 在上一轮后输入 `查下这个物料 1000 工厂库存` 时，确定性证据把 `1000` 绑定为 plant，并继承已确认 material；结果为 `{material:DEMOA2, plant:1000}` 的 `SELECT`。
- 在上一轮后先输入 `换个物料能查吗` 时，只把 material 标记为 `CLEARED`、保留 plant=`5100` 并返回 `CLARIFY`，Gateway 调用为 0；随后输入 `查下这个物料 1000 工厂库存` 仍保持 material unresolved/conflicted、plant=`1000`，继续 `CLARIFY` 且 Gateway 调用为 0。
- 用户再明确 `这个物料是指上面的 DEMOA2，1000 是工厂` 后，material=`DEMOA2 / CONFIRMED`、plant=`1000 / EXPLICIT`，Frame 进入 `READY` 并只执行正确 CallPlan。
- recorded LLM 返回 `{material:1000, plant:工厂}` 时，`plant=工厂` 被记录为 `invalid_semantic_value`，`material=1000` 仍是 `MODEL_CANDIDATE`，不得直接成为 resolved slot；结果是 `CLARIFY`、null CallPlan、Gateway 调用为 0。
- 同 conversation 并发 turn、CAS conflict、lease conflict、duplicate `turnId`、principal mismatch、stale Registry binding 或 pending binding mismatch 时，状态不得被覆盖，Gateway 调用为 0。
- Registry/Gateway 收到 READ plant=`工厂` 时在 SAP 前返回 `INVALID_PARAMETER`；`5100` 与 `1000` 保持有效。
- 任一 READ Frame、PendingInteraction 或历史文本不得创建、恢复、确认或执行 `ApprovalRecord`；WRITE execute 计数保持 0。

# Constraints and invariants

- `GovernedContext` 是 principal、tenant、role、data scope、visible capability 与 Registry snapshot 的唯一执行权威；`ConversationReadState` 仅保存 READ 业务焦点和 advisory semantics。
- Frame 状态仅为 `COLLECTING | READY | CONFLICTED | STALE`；Slot 状态仅为 `RESOLVED | CONFLICTED | CLEARED`；来源至少区分 `EXPLICIT | CONFIRMED | INHERITED | MODEL_CANDIDATE | INHERITED_LEGACY`。
- 当前轮明确纠正/确认 > 合法 pending answer > 当前轮确定性标签/句法 > active Frame 已确认值 > LLM candidate。LLM candidate 单独不得 resolve required slot；同 token 槽位角色不明或证据冲突必须澄清。
- 只有 unique visible READ capability、全部 required slots resolved、无 conflict、当前 Registry schema/version 有效且 pending 已确定性消费的 `READY` Frame 才能生成 `SELECT` 和 READ CallPlan。
- `COLLECTING`、`CONFLICTED`、`STALE`、lease/CAS/store failure 和 duplicate/in-flight turn 均不得调用 Gateway validate/execute。
- conversation runtime 必须先 claim/load/resolve，再 CAS 持久化 next state；只有 CAS 成功后的 `SELECT` 可通过 server-owned continuation 执行 READ。
- `PendingInteraction` 必须绑定 `frameId + stateVersion + registrySnapshotId`，与 WRITE approval 分离；一个 conversation 同时最多一个 READ pending interaction。
- migrated schema-v1 Session 初始必须为 `STALE`，不得直接执行；迁移失败不得删除或静默覆盖原文件。
- READ 不得调用 `BAPI_TRANSACTION_COMMIT` 或 `BAPI_TRANSACTION_ROLLBACK`；本变更不授权或执行 SAP WRITE。

# Decisions

- 范围采用所有 READ capabilities 的统一上下文模型，而不是只修库存 prompt。
- 采用 deterministic evidence arbitration；任何不能唯一解释的 required slot 都进入 `CLARIFY`，不使用 confidence 阈值猜测。
- 采用 typed `ReadContextFrame + SlotBinding + PendingInteraction`，纯 `ContextReducer` 是 conversation semantic state 的唯一修改入口。
- durable Session 是结构化业务上下文权威；最近三轮 history 继续作为不可信语言上下文，不扩大窗口来替代状态机。
- 采用 conversation lease + `stateVersion` CAS + `turnId` idempotency；Run lease、PlanExecution lease 与 Approval claim 继续独立。
- contextual READ 采用两阶段 `resolve_read_turn -> CAS -> continue_resolved_read`，解决当前 Python 调用 Gateway 早于 TypeScript Session save 的时序缺口。
- rollout 顺序为 failure fixture、shadow v2、READ authority switch、pending/durability convergence、hard-gate 后移除 destructive legacy bridge；保留只读 schema-v1 stale migration decoder。
- Gateway 只做 Registry-derived pattern/type/length validation，不承担自然语言指代、槽位交换或 SAP error intent recovery。
- 2026-08-06 用户已确认本 brief 与完整目标规格，允许按上述 READ-only、fail-closed 和 live-smoke 边界进入 Build。

# Open questions

无。

# Verification expectations

- 按 TDD 逐层验证 Python contracts/candidates/Reducer/decision gate、TypeScript Session/lease/CAS/idempotency、Java Registry pattern validation、orchestrator two-phase integration 和 release hard gates。
- 必须运行 `.venv/bin/python -m pytest agent/tests`、`scripts/verify-agent-callplan-evidence.sh`、`npm --prefix frontend run verify`、`cd services/gateway && ./gradlew :core:test :app:test`、`openspec list --json`、`openspec validate --all --strict` 与 `git diff --check`。
- Eval 必须使用脱敏的真实 bad payload `{material:1000, plant:工厂}`，不能只 mock 理想 LLM 输出；exact failure sequence 每轮都要断言 Frame、decision、CallPlan 和 Gateway delta。
- hard gates 要求 false `SELECT`、non-READY Gateway call、wrong CallPlan slot role、visibility leakage、closed-set escape、duplicate-turn Gateway call、CAS/lease conflict overwrite、stale-frame execution 与 READ-created WRITE authority 全部为 0；deterministic core 与 clarification recovery 为 100%。
- Native Verify 的每个 acceptance item 必须绑定当前 snapshot 的真实 receipt。未运行、失败、stale 或 live-only 检查不得记录为 passed；live smoke 默认 `not_run`。

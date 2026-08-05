# Outcome

在 Runbooks 16-20 的 component/runtime 基础与既有 sandbox Action approval/Gateway 契约之上，建立从单个 `ActionProposal` 到真实、可核验 `PlanApprovalRecord` 的受治理闭环；Human Approval 后重新校验完整 plan/fact/projection/rule/proposal/parameter 快照，并通过 durable continuation 与 Gateway atomic claim 保证 `MM.PR.CreateDraft` 最多执行一次。

# Scope

- 新增 plan-aware approval domain contract，绑定 `runId`、`planId`/plan hash、`snapshotId`、`actionNodeId`、`capabilityId@version`、parameter hash、fact-set/projection/rule-set/proposal hashes、requester/approver、expiry、revocation 与 separation-of-duty result。
- 将 Runbooks 16-20 的 PlanGraph、PlanExecutionRecord、MaterialSupplySnapshot、RecommendationPlan、ActionProposal 与 governed event/runtime 接成一个单终点 READ-to-WRITE continuation；只接受已注册的 `MM.PR.CreateDraft`，不接受模型提供的 RFC/binding/approval token。
- 复用现有 trusted principal、durable run/session、durable approval store、run lease/idempotency、Gateway `ApprovalGuard`/atomic claim 和 ActionResult/trace，不建立第二套 identity、approval、store 或 execution authority。
- 在 approve/reject/expire/revoke/duplicate continuation 时进行服务端状态转换；approve 后、Gateway 前重新计算并核对 principal、snapshot、plan、proposal、parameters、facts、projection、RuleSet 与 capability/version。
- 对批准后的单 Action 使用稳定 idempotency identity 与 durable result lookup；并发或重试只能取得已有结果、进行中/冲突状态，不能产生第二次 Gateway WRITE execute。
- 扩展 governed events、Workbench approval/action 状态和审计链，使 intent -> plan -> READ nodes -> facts -> projection -> recommendation -> proposal -> approval -> ActionResult -> SAP RETURN 可在同一 run/trace 回放。
- 用 fake/sandbox boundary 和自动化测试覆盖成功与所有 fail-closed 路径；本 change 默认不执行新的真实 SAP WRITE。

# Non-goals

- 不实现多 WRITE、WRITE batch、Saga、自动补偿、自动审批、自由 Tool Calling、Dynamic Planner、Knowledge/RAG 或 Memory。
- 不允许生产 client 自动提交，不把 `ActionProposal.pending_approval`、UI label/button、chat sentence、fixture 或模型输出当作 Human Approval。
- 不让 request body、prompt 或模型携带/覆盖 approver principal、approval token、RFC name、bindingId、credential 或 technical payload。
- 不新增 Action capability 或 executor family；只复用已注册的 sandbox/dev `MM.PR.CreateDraft` 与既有 Gateway/JCo WRITE contract。
- 不在 Runbook 21 宣称 L1/L2/L3 release gate 已通过；完整 E2E 成熟度升级属于 Runbook 22。
- 不执行任何新的 live sandbox/dev SAP WRITE；如验证确需真实写入，必须另行取得针对 capability 与不可变参数快照的明确 Human Approval。

# Acceptance examples

- 给定同一非空 snapshot 下已完成的双 READ plan、完整/fresh projection、确定性 recommendation 与唯一 `pending_approval` proposal，系统向当前用户展示不可变 Action 参数及其受治理依据，并创建一个 pending `PlanApprovalRecord`；在用户显式确认前不调用 Gateway WRITE。
- run owner 对展示的精确 Action subject 显式确认且所有绑定对象仍完全一致时，系统记录 Human-in-the-loop confirmation、原子占用 approval，构造一个 `MM.PR.CreateDraft` Action CallPlan，并在 fake/sandbox Gateway boundary 最多执行一次；ActionResult 与 SAP RETURN 摘要进入同一 trace。
- reject、expire 或 revoke 后 continuation 返回结构化终态，Gateway WRITE 调用数为 0；必须基于当前事实/规则/参数重新形成 proposal 与新 approval，不能复活旧记录。
- principal/tenant/role/data-scope 不符，或 snapshot、plan、action node、capability/version、parameter、facts、projection、RuleSet、proposal 任一 hash 漂移时 fail closed，Gateway WRITE 调用数为 0，并留下不泄密的审计原因。
- 同一 approval 的并发/跨重启/重复 approve 或 continuation 最多产生一个 Gateway WRITE execute；已完成重试返回同一 durable ActionResult，进行中或冲突重试返回明确幂等状态。
- replay/refresh/cursor reconnect 只重放已持久事件与 ActionResult，不触发 approval、continuation 或 Gateway execute；Workbench 明确区分 proposed、pending、approved、rejected/expired/revoked、executing 与 executed。

# Constraints and invariants

- Human Approval 必须是服务端可检查、绑定 trusted principal 与不可变 approval subject 的记录；用户最初提出“开始 Runbook 21”只授权 Shape，不构成 Action approval。
- `PlanApprovalRecord` 是既有原子 `ApprovalRecord` 的 plan-aware 扩展/封套，共用同一 approval identity 与 durable lifecycle；Gateway 继续持有 capability/parameter hash/atomic claim 的最终执行权威。
- approval 只授权一个 Action node、一个已注册 capability version 和一份 canonical parameters；任何漂移均使当前 approval 不可执行，不能在 approve 后静默重算或替换输入。
- READ 成功、RecommendationPlan、ActionProposal、Narrative、Workbench 控件和事件均不自动授予执行权；未审批路径的 Gateway WRITE execute 计数必须为 0。
- Human-in-the-loop confirmation 由创建并拥有该 run 的 trusted principal 完成；其他 principal、cross-tenant、不可见 capability、无权限 role/data-scope 或 identity provider 不可用时 fail closed。
- exactly-once 由 durable idempotency result + run lease + Gateway approval atomic claim 共同保证；不得只依赖 UI 禁用、进程内 flag 或聊天历史。
- replay、恢复与 retry 只能加载原始结构化 plan/evidence/approval 状态，不能从 summary、Memory、LLM 或 UI fixture 重建执行权威。
- 审计事件只持久化 allowlist/redacted 字段；credentials、technical binding、raw SAP payload 与 raw model response 不进入事件、trace、fixture 或测试输出。

# Decisions

- 采用“plan-aware envelope + 既有 atomic ApprovalRecord/Gateway guard”的组合，而不是替换 Gateway 或建立第二套 approval store；plan 层负责全 subject revalidation，Gateway 负责 capability/parameters 与原子执行占用。
- 继续以 TypeScript durable runtime 作为 Runbooks 16-20 对象的组合与 continuation 层，并对 Python/Java ApprovalRecord/Gateway contract 做最小兼容扩展；不把业务 plan 对象下沉为 Gateway 执行输入。
- approval subject 使用 canonical、版本化 hash 引用，不把可变对象副本或自由文本作为授权依据；显示需要的安全摘要与执行权威分离。
- revoke/expire/stale 均使旧 approval 永久不可执行；若业务仍需动作，必须从当前 snapshot/facts/rules 重新生成 proposal 和 approval。
- duplicate continuation 优先返回同一 durable ActionResult；若首次执行仍在进行或 request subject 冲突，则返回结构化 in-progress/conflict，不再次调用 Gateway。
- 本次 Build/Verify 默认仅使用 fake/sandbox boundary；任何新的真实 SAP WRITE 均不在当前确认范围内。
- Human Approval 是单用户 Human-in-the-loop confirmation，不是多人协同审批流：创建并拥有 run 的当前 trusted principal 查看不可变 Action 参数与依据后显式 approve/reject；系统记录 actor/time/subject hash，其他 principal 仍按既有隔离契约 fail closed。
- 本 MVP 不强制 separation-of-duty；`PlanApprovalRecord.separationOfDutyResult` 固定记录 `not_applicable`，不引入第二审批人、审批角色路由或跨 principal approval access。local-first placeholder principal 可完成其自身 run 的显式 Action 确认，但 request body/chat/LLM 仍不能提供身份或 approval token。
- 用户于 2026-08-05 确认本 brief 与完整目标 specification；该确认授权进入 Build，但不等于任何具体 Action 的 Human Approval，也不授权新的真实 SAP WRITE。

# Open questions

- 无。

# Verification expectations

- 按 TDD 先固化 PlanApprovalRecord、状态机、完整 subject revalidation、revocation/staleness、idempotent continuation、Gateway guard 和 event/replay 的失败测试，再写最小实现。
- 运行 `.venv/bin/python -m pytest agent/tests -q`、`npm --prefix frontend run verify`、Gateway 相关 focused Gradle tests、`.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json`、`scripts/verify-agent-callplan-evidence.sh` 与 `openspec validate --all --strict`。
- 所有自动化验证使用 fake/sandbox boundary；验证报告必须明确记录未运行 live SAP WRITE，不能把测试替身或 UI 结果描述为真实 SAP execution evidence。
- Native Verify 为每个 acceptance item 绑定 fresh evidence，并记录未审批 Gateway WRITE 调用为 0、批准后最大调用为 1、duplicate/cross-restart 结果稳定及全部漂移路径 fail closed。

# Outcome

在不接入生产 multi-capability orchestrator、不创建新的 Human Approval、也不执行 SAP WRITE 的前提下，把 Runbooks 16-19 已稳定的 PlanGraph、node ledger、ReasoningFact、OutputProjection、RecommendationPlan、NarrativeEnvelope 和 ActionProposal 契约投影为可持久化重放的 SSE 事件，并由 Workbench 在同一 run/trace 中形成可追溯的 plan/evidence 体验。

# Scope

- 扩展 `AgentRunEvent`、redacted artifact 与 view-model 契约，加入 `intent_recognized`、`capability_recalled`、`plan_compiled`、`plan_node_state`、`fact_emitted`、`projection_completed`、`recommendation_completed`、`narrative_completed`、`action_proposed`、`approval_updated`、`action_executed` 事件族；新事件绑定非空 `runId`、`traceId`、`sequence`、`snapshotId` 与 typed object refs。
- 提供纯投影式 event producer：只消费调用方显式提供的 governed domain objects，生成脱敏、稳定排序的事件；不负责 plan 编译、节点调度、事实计算、建议推导、叙事生成、审批或执行。
- 复用现有 JSONL durable run store 与 cursor SSE，保证 refresh/reconnect 按 sequence 重放、重复事件去重、顺序缺口显式暴露，且 replay 不触发节点或 Action。
- 扩展 Workbench 为 Conversation、Intent/Recall、Plan、Execution、Evidence、Recommendation/Narrative、Action/Approval、Trace/Replay 分区；桌面端支持 plan/evidence 并排，移动端按同一语义顺序堆叠。
- 显示 PlanGraph 拓扑与每节点状态；节点详情只展示脱敏的 CallPlan/result/trace 摘要；NarrativeEnvelope 的每个 claim 可导航到对应 evidence refs。
- 用可审查 fixtures 和组件/集成测试覆盖单能力、多 READ、partial failure、READ-to-WRITE proposal，以及 loading/empty/error/replay、desktop/mobile 与基本无障碍状态。

# Non-goals

- 不把 Python PlanGraph v2、TypeScript PlanExecutor、OutputProjection、RecommendationDecision 和 grounded narrative 接成生产 orchestrator；不宣称 live end-to-end multi-capability composition。
- 不填充或发布真实 `projectionRef` / `ruleSetRefs`，不新增 capability、RuleSet、projection、executor family 或业务规则。
- 不把 `ActionProposal` 当成 `ApprovalRecord`；proposal-only 视图不提供 approve/execute 控件。现有 approval continuation 继续由服务端校验，Runbook 21 才负责新的 proposal-to-approval 与 exactly-once Action 闭环。
- 不调用 Gateway、JCo、OData 或 SAP，不执行任何 SAP WRITE，不新增多 Action、多 WRITE、Saga、补偿、Knowledge/RAG、Memory、自由 Tool Calling或 Dynamic Planner。
- 不展示 technical binding、RFC/URL/raw SQL、credential、raw SAP payload、raw model response 或不可见 capability。

# Acceptance examples

- 给定一个单能力 run fixture，Workbench 保持现有 conversation/result/timeline 行为，并能从新的统一分区查看 intent、capability、safe execution evidence 与 trace；旧事件仍可兼容读取。
- 给定同 snapshot 的双 READ PlanGraph、node ledger、facts、complete `MaterialSupplySnapshot`、RecommendationPlan 与 NarrativeEnvelope，event producer 生成 sequence 单调递增的完整事件链；桌面端 plan/evidence 并排、移动端顺序堆叠，每个 claim 能定位到存在的 evidence ref。
- 给定节点 failed/timed-out/cancelled 的 partial failure fixture，Workbench 明确显示失败节点、`partial`/`incomplete` projection、limitations 与未执行依赖，不能把结果渲染为 complete。
- 给定包含单个 `pending_approval` ActionProposal 的 READ-to-WRITE fixture，Workbench 显示 proposal 参数来源、facts/rules refs 与“待审批”状态，但不出现可执行审批按钮，也不生成 ApprovalRecord/Gateway 请求。
- 同一 durable event log 在 refresh/reconnect 后从 cursor 继续按 sequence 展示；重复 delivery 不重复 artifact，sequence gap/corrupt reference 进入显式 error/limited 状态，且没有执行副作用。
- loading、empty、error 和 replay 状态可由键盘访问并具有可识别 label/status；移动端不丢失 plan、evidence、limitations、proposal 或 trace 内容。

# Constraints and invariants

- UI 是观察与审核入口，不是执行权威；ledger、Gateway result、approval binding 与 trace 才可作为 execution evidence，UI label 永远不是证据。
- 新 plan/evidence 事件必须绑定同一个非空 `runId`、`traceId` 与 `snapshotId`；typed refs 必须解析到本 run 的受治理、脱敏对象，未知/跨 run/跨 snapshot 引用 fail closed。
- 事件 append-only；sequence 在单 run 内严格递增。cursor replay 只返回 `sequence > cursor`，客户端按 identity/sequence 幂等消费，不通过 replay API 触发任何 continuation。
- Narrative 只消费 `NarrativeEnvelope`；claims、evidence refs、limitations、recommendation/proposal/approval state 以确定性对象为准，自由文本不能改写业务状态。
- `ActionProposal.pending_approval` 不是 Human Approval。只有已有、可校验的 ApprovalRecord 才可沿用现有 approval control；本 change 不创建该记录或扩大 WRITE 权限。
- 所有展示对象先经过 allowlist projection 与 redaction；raw SAP/model/runtime secret 不进入 durable event、fixture 或 UI。
- 保持现有单能力 READ、sandbox Action、batch confirmation、principal ownership、durable lease/idempotency 和 SSE reconnect 契约兼容。

# Decisions

- 依据 Runbook 20 与完整 Agent 设计，将本 change 定位为 event contract + durable replay + component/UI integration，而不是生产 orchestrator 或 E2E release gate。
- 现有 legacy event names 保持兼容；新增领域事件承载 Runbooks 16-19 对象，不通过重命名破坏既有单能力/approval/batch 流程。
- Workbench 使用稳定 typed refs 和专用 view models，不把任意 artifact JSON 当作业务状态；原始脱敏 JSON 可保留为排障详情。
- partial failure 采用显式节点状态、projection completeness 与 limitations 展示，不以成功节点数量推断完整性。
- proposal-only 与 approval-ready 是不同 UI 状态：前者只读，后者仅对已有 ApprovalRecord 复用现有服务端 continuation。
- 正式实现遵循 TDD，先以四类 fixture 固化 event/replay/view behavior，再做最小 runtime/UI 扩展。
- 用户于 2026-08-05 明确确认本 brief 与完整目标 specification；该确认只授权 Runbook 20 Build，不构成 Human Approval 或 SAP WRITE 授权。

# Open questions

- 无。

# Verification expectations

- 先运行相关 focused tests，证明 event schema/projector、durable replay、view-model、claim-to-evidence、proposal/approval 边界及 responsive/accessibility 状态。
- 运行 `npm --prefix frontend run verify`，并检查 production build、TypeScript、unit/component tests 的真实结果。
- 运行 `.venv/bin/python -m pytest agent/tests -q`、`scripts/verify-agent-callplan-evidence.sh` 与 `openspec validate --all --strict`，确认既有 Agent、CallPlan/Gateway 与 spec store 无回归；这些检查不得执行 SAP WRITE。
- Native Verify 为每个 acceptance item 绑定 fresh evidence，并在 `verification.md` 记录实际命令、结果、跳过项、spec consistency 与已知限制。

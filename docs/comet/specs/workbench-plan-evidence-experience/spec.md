# Workbench Plan Evidence Experience Specification

## Purpose

定义 Runbook 20 的完整目标行为：将受治理的 Agent plan/evidence 对象投影为同 run/trace/snapshot 的 durable SSE 事件，并由 Workbench 提供可重放、可追溯、响应式且不越过执行权威边界的观察体验。本能力不创建生产 orchestrator、Human Approval 或 SAP WRITE 执行路径。

## Requirements

### Requirement: Governed domain events have one traceable envelope

系统 SHALL 支持 `intent_recognized`、`capability_recalled`、`plan_compiled`、`plan_node_state`、`fact_emitted`、`projection_completed`、`recommendation_completed`、`narrative_completed`、`action_proposed`、`approval_updated` 和 `action_executed` 事件。每个新事件 MUST 包含非空 `runId`、`traceId`、`snapshotId`、正整数 `sequence`、timestamp 和与事件类型匹配的 typed object refs。一个 run 内的 plan、ledger、facts、projection、recommendation、narrative、proposal、approval 与 action evidence MUST 绑定相同 snapshot；未知、缺失、跨 run 或跨 snapshot 引用 MUST fail closed。

事件 producer SHALL 只投影调用方显式提供的 governed objects，MUST NOT 编译 plan、调度节点、构建事实、计算 projection/recommendation、生成 narrative、创建 ApprovalRecord 或调用执行接口。legacy 单能力、approval 与 batch event types SHALL 保持兼容读取。

#### Scenario: Complete multi-READ bundle yields one ordered event chain

- **WHEN** 调用方提供同 run/trace/snapshot 的 PlanGraph、node ledger、ReasoningFacts、OutputProjection、RecommendationPlan 和 NarrativeEnvelope
- **THEN** producer 生成类型匹配、sequence 严格递增且 refs 全部可解析的事件链
- **AND** 不调用 Gateway、SAP 或任何 continuation

#### Scenario: Cross-snapshot reference is rejected

- **WHEN** narrative claim、proposal、fact 或 node ref 指向另一 run/snapshot 或不存在的对象
- **THEN** producer 返回结构化 contract failure
- **AND** 不持久化伪完整事件链、不以自由文本修补引用

### Requirement: Durable replay is ordered, idempotent and side-effect free

新事件 SHALL 复用现有 append-only durable run store 与 cursor SSE channel。单 run 的 sequence MUST 严格递增；reconnect 只返回 `sequence > cursor` 的已持久化事件。客户端 SHALL 按 run/event identity 与 sequence 幂等消费重复 delivery，并在 gap、重复冲突或 corrupt reference 时显示明确 replay/error 状态，而不是静默重排成成功结果。

读取、刷新、重连、切换桌面/移动布局或展开详情 MUST NOT 触发 PlanExecutor node、approval continuation、Action、Gateway 或 SAP。terminal event 只有在先前事件已可回放后才能关闭 stream。

#### Scenario: Reconnect resumes without duplicate artifacts

- **WHEN** 客户端已消费到 cursor N 后断线，并收到包含重复 N 与新增 N+1..M 的 delivery
- **THEN** UI 只应用尚未消费且 identity 一致的新事件
- **AND** artifact、node state 与 evidence link 不重复
- **AND** 不重新执行节点或 Action

#### Scenario: Sequence gap remains visible

- **WHEN** durable log 或 stream 从 N 跳到 N+2，或同 sequence 出现冲突 payload
- **THEN** Workbench 进入显式 limited/error replay 状态
- **AND** 不把不完整链路显示为完整 execution evidence

### Requirement: Workbench presents one plan and evidence workspace

Workbench SHALL 在同一 run 下提供 Conversation、Intent/Recall、Plan、Execution、Evidence、Recommendation/Narrative、Action/Approval、Trace/Replay 语义分区。Plan 区 SHALL 显示 PlanGraph nodes/edges/topological order/read/action partition 与 governance；Execution 区 SHALL 显示每节点 ledger state、attempt、dependency/blocking 与安全摘要；Evidence 区 SHALL 显示 facts、projection completeness/freshness/lineage/limitations。桌面端 SHALL 支持 plan 与 evidence 并排比较；移动端 SHALL 按相同语义顺序堆叠且不丢字段。

UI MUST NOT 依据标签、颜色或前端计算推断节点成功、approval 或 Action execution。状态只来自对应 ledger、projection、ApprovalRecord、Gateway result 和 trace refs。

#### Scenario: Complete multi-READ run is inspectable

- **WHEN** Workbench 消费 complete 双 READ fixture
- **THEN** 用户可从 PlanGraph node 导航到对应 ledger、CallPlan/result safe summary、facts、projection lineage 与 trace
- **AND** desktop/mobile 均保留完整 evidence 与状态语义

#### Scenario: Partial failure is not rendered as complete

- **WHEN** 至少一个节点 failed、timed out、cancelled 或 blocked，且 projection 为 partial/incomplete
- **THEN** Workbench 显示失败节点、受影响依赖、missing facts 与 limitations
- **AND** 不使用 complete/success 文案掩盖失败

### Requirement: Narrative claims resolve to governed evidence

Workbench SHALL 只将 `NarrativeEnvelope` 作为组合叙事输入。每个业务 claim MUST 展示可访问的 evidence navigation，并解析到本 run/snapshot 中存在的 ReasoningFact、projection、rule/recommendation、proposal state 或 trace ref。limitations、completeness、recommendation status、proposal ref 与 approval state MUST 直接展示确定性对象值；自由文本 MUST NOT 创建、删除或改绑 evidence/state。

#### Scenario: Claim navigates to its evidence

- **WHEN** NarrativeEnvelope claim 含一个或多个有效 evidence refs
- **THEN** 用户可从 claim 定位到全部引用对象及其安全摘要
- **AND** claim identity 与 refs 在 replay 后保持不变

#### Scenario: Unsupported claim is visibly rejected

- **WHEN** claim 没有 evidence ref 或引用未知对象
- **THEN** Workbench 不把该 claim 呈现为受支持业务结论
- **AND** 显示结构化 grounding/error 状态

### Requirement: Proposal, approval and execution remain distinct states

Workbench SHALL 区分 `ActionProposal.pending_approval`、已有 `ApprovalRecord` 的 approval state 与带 Gateway/trace evidence 的 executed state。proposal-only view SHALL 展示 capability、参数、parameter sources、facts/rules refs、proposal hash 与待审批状态，但 MUST NOT 显示可执行 approve/execute control。只有服务端已提供属于当前 principal/run/snapshot/proposal 的可校验 ApprovalRecord 时，现有 approval control 才可用；服务端仍须重新校验 principal、hash 和状态。

UI label、button state、fixture 或 `action_proposed` event MUST NOT 成为 Human Approval 或 execution evidence。本能力 MUST NOT 创建 ApprovalRecord、把 proposal 发送到 Gateway、执行 SAP WRITE 或改变 exactly-once 语义。

#### Scenario: Pending proposal is read-only

- **WHEN** run 只有 `pending_approval` ActionProposal 且没有 ApprovalRecord
- **THEN** Workbench 显示“待审批”及完整来源
- **AND** 不出现可执行 approval control、不发 continuation 请求

#### Scenario: Existing approval evidence remains server-authoritative

- **WHEN** legacy sandbox Action run 已包含有效 ApprovalRecord
- **THEN** Workbench 可沿用现有 approve/reject control
- **AND** UI 仅提交 identifier/decision，服务端负责 principal/hash/state 校验
- **AND** replay 不重复提交 approval 或 Action

### Requirement: Sensitive and technical data never enters the experience

进入 durable event 与 Workbench 的对象 SHALL 经过 allowlist projection 和 redaction。系统 MUST NOT 持久化或展示 technical binding、RFC name、URL、raw SQL、credential、token、destination config、raw SAP payload、raw live model response 或不可见 capability。节点详情只可展示 redacted CallPlan/result/trace safe summary；测试 fixture 只能包含脱敏合成数据。

#### Scenario: Unsafe fields are removed before persistence

- **WHEN** 输入 artifact 含 technical binding、credential-like field 或 raw payload
- **THEN** event producer 在 append 前移除或拒绝该内容
- **AND** durable log、SSE 与 UI 均不包含原值

### Requirement: Four run classes and responsive states are reviewable

项目 SHALL 提供可审查 fixtures 与自动化测试，至少覆盖单能力、多 READ、partial failure 和 READ-to-WRITE proposal 四类 run，以及 loading、empty、error、replay、desktop、mobile 与键盘/label/status 基本无障碍行为。测试 SHALL 证明 event/ref contract、sequence replay、claim grounding、proposal/approval separation、redaction 和 legacy event compatibility；fixtures 与 UI 状态不构成 live execution evidence。

#### Scenario: Workbench verification matrix passes

- **WHEN** 运行 focused event/replay/view tests 与 frontend verification
- **THEN** 四类 run 与全部关键 UI 状态通过
- **AND** 既有 single-capability、batch、approval、principal ownership 与 SSE cursor tests 无回归
- **AND** 测试过程中不执行 SAP WRITE

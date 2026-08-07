# Governed READ Context Specification

## Purpose

定义 SAP Nexus Agent 在变更完成后的统一 READ 多轮上下文行为。系统必须把模型与自然语言历史限制为 advisory evidence，以 typed Frame、纯 Reducer、当前 governed visibility/Registry 和 durable concurrency protocol 确定槽位状态；任何歧义、冲突、陈旧或持久化失败都必须在 Gateway 和 SAP 前停止。

## Requirements

### Requirement: READ conversation semantics and execution authority remain separate

系统 SHALL 将上下文分为 `GovernedContext`、`ConversationReadState` 和 `RunEvidence` 三层。`GovernedContext` MUST 从受信服务端重新建立 principal、tenant、role、data scope、visible capability set 与 Registry snapshot；`ConversationReadState` SHALL 只保存 READ capability focus、slots、references、recent frames 与 pending interaction；`RunEvidence` SHALL 保存本轮不可变 envelope、resolution report、decision、CallPlan 和执行结果。conversation/history/model/state MUST NOT 提供或恢复 principal、visibility、technical binding、credential、approval 或 WRITE authority。

#### Scenario: Conversation state cannot expand visibility

- **WHEN** persisted Frame 或历史文本包含当前 principal 不可见的 capability hint
- **THEN** 当前 `GovernedContext` 的 visible set 拒绝该 capability
- **AND** decision 不为 `SELECT`，Gateway validate/execute 调用数为 0

#### Scenario: READ context cannot create WRITE authority

- **WHEN** READ Frame、pending reply、history 或 model candidate 包含 `MM.PR.CreateDraft`、approval wording 或 WRITE-shaped parameters
- **THEN** 系统不得创建、恢复、确认或执行 `ApprovalRecord`
- **AND** WRITE Gateway execute 调用数为 0

### Requirement: Versioned READ state is typed and structurally valid

系统 SHALL 使用 schema-versioned `ConversationSessionV2`，其 TypeScript 实现为 `SessionStateV2`，并包含 `stateVersion`、principal binding、一个 active `ReadContextFrame`、最多两个 recent Frames、最多一个 `PendingInteraction`、recent turns、`lastAppliedTurnId` 与 `lastRunId`。Frame status MUST 限于 `COLLECTING | READY | CONFLICTED | STALE`；Slot state MUST 限于 `RESOLVED | CONFLICTED | CLEARED`；Slot provenance MUST 区分 `EXPLICIT | CONFIRMED | INHERITED | MODEL_CANDIDATE | INHERITED_LEGACY`。

#### Scenario: Invalid READY frame is rejected

- **WHEN** serialized Frame 声明 `READY` 但含 `CLEARED`/`CONFLICTED` required slot、空 capability、空 snapshot 或不合法 enum
- **THEN** deserialization/validation 返回结构化 context error
- **AND** 该 Frame 不可生成 MatchDecision 或 CallPlan

#### Scenario: Only explicit restoration reactivates a recent frame

- **WHEN** active capability 已切换且 recent Frames 中存在旧库存 Frame
- **THEN** 相似措辞、embedding 或模型偏好不得自动恢复旧 Frame
- **AND** 只有“回到刚才的库存查询”等确定性显式引用可重新激活它

### Requirement: LLM and history produce advisory candidates only

LLM/rule front door SHALL 输出 `IntentEnvelope` 与 `ContextCandidateSet`，不得直接写 Session、resolved slot 或 executable parameters。Registry aliases、examples、semantic name/type、binding kind、length 与 pattern MAY 用于 language hints 和 semantic exclusion；模型 confidence MUST NOT 升级候选权威。RFC、OData URL、binding、credential、principal 或 approval 等 technical/governance fields MUST 被丢弃并记录 discard reason。

#### Scenario: Recorded wrong model payload remains non-authoritative

- **WHEN** recorded model 返回 capability `MM.Inventory.GetAvailability` 和 parameters `{material:1000, plant:工厂}`
- **THEN** `plant=工厂` 记录 `invalid_semantic_value`，`material=1000` 仅保持 `MODEL_CANDIDATE`
- **AND** candidate extraction 不得产生 trusted resolved material/plant

#### Scenario: LLM unavailable does not relax the gate

- **WHEN** LLM unavailable、超时、JSON malformed 或 schema invalid
- **THEN** 系统只使用 deterministic spans、labels、pending 与 Frame evidence
- **AND** 证据不足时返回 `CLARIFY`，不得因为 fallback 而放宽 required-slot 或 visibility checks

### Requirement: ContextReducer is the only conversation semantic transition authority

系统 SHALL 使用无副作用、可确定性回放的 `ContextReducer` 处理 `CONTINUE_FRAME`、`REPLACE_SLOT`、`CLEAR_SLOT`、`SWITCH_CAPABILITY`、`CONFIRM_PENDING`、`REJECT_PENDING` 与 `NEW_MULTI_GOAL`。证据优先级 MUST 为：当前轮明确纠正/确认、合法 pending answer、当前轮确定性标签/句法、active Frame 已确认值、LLM candidate。Reducer MUST 返回 immutable next state、operation、changed slots、issues 和 resolution evidence。

#### Scenario: Clear one slot preserves unrelated confirmed slots

- **WHEN** active inventory Frame 为 material=`DEMOA2`、plant=`5100`，用户说 `换个物料能查吗`
- **THEN** Reducer 将 material 变为 `CLEARED`，plant 保持 `5100 / INHERITED`
- **AND** 创建只期待 material 的 `SLOT_CLARIFICATION`，Frame 为 `COLLECTING`

#### Scenario: Conflicting evidence requires clarification

- **WHEN** 同一 token 可属于多个槽位，两个同级明确值互斥，或模型 candidate 与确定性证据冲突
- **THEN** 受影响 Slot/Frame 进入 `CONFLICTED` 或保持 unresolved
- **AND** 系统不得通过投票、confidence 或 SAP error 自动选择一个角色

#### Scenario: Capability switch does not inherit incompatible slots

- **WHEN** 用户明确从库存切换到采购订单 READ
- **THEN** 旧 Frame 移入 recent Frames，新建目标 capability Frame
- **AND** 只有目标 Registry schema 中语义兼容且有合法证据的 slots 可继续使用

### Requirement: Decision gate is the only path from Frame to READ CallPlan

系统 SHALL 在当前 `VisibleCapabilitySet` 和 Registry snapshot 上计算 Frame decision。只有 capability 唯一可见、Frame snapshot/schema/version 当前有效、每个 required slot 为 `RESOLVED`、无 conflict 且 pending 已确定性消费时，Frame 才可为 `READY` 并产生 `SELECT`。`COLLECTING`/`CONFLICTED` SHALL 产生 `CLARIFY`，bounded capability ambiguity SHALL 产生 `SHOW_OPTIONS`，multiple goals SHALL 产生 `ESCALATE_TO_PLANNER`，closed-set/visibility/technical violation SHALL 产生 `REJECT`。

#### Scenario: Non-READY frame never reaches Gateway

- **WHEN** Frame 状态为 `COLLECTING`、`CONFLICTED` 或 `STALE`
- **THEN** decision 不为 `SELECT` 且 CallPlan 为 null
- **AND** Gateway validate/execute 调用数均为 0

#### Scenario: READY frame creates plan only from resolved slots

- **WHEN** 当前 visible inventory Frame 为 `READY`，material=`DEMOA2 / CONFIRMED`、plant=`1000 / EXPLICIT`
- **THEN** READ CallPlan parameters 精确等于 `{material:DEMOA2, plant:1000}`
- **AND** MODEL_CANDIDATE、CLEARED、CONFLICTED、technical 或 unknown fields 不进入 CallPlan

### Requirement: The reported multi-turn failure is blocked and recoverable

系统 SHALL 将真实失败序列作为 deterministic 与 recorded-LLM regression。每轮必须断言 Frame slots/status、decision、CallPlan 和 Gateway validate/execute delta，不得只断言最终回复文本。

#### Scenario: Direct plant switch succeeds

- **WHEN** Turn 1 查询 material `DEMOA2`、plant `5100` 成功，Turn 2 输入 `查下这个物料 1000 工厂库存`
- **THEN** material 从 active Frame 以 `INHERITED` 保留，plant 以 `EXPLICIT` 更新为 `1000`
- **AND** Turn 2 decision 为 `SELECT`，Gateway parameters 为 `{material:DEMOA2, plant:1000}`

#### Scenario: Cleared material is not silently revived

- **WHEN** Turn 1 查询成功，Turn 2 输入 `换个物料能查吗`，Turn 3 输入 `查下这个物料 1000 工厂库存`，同时 recorded model 返回 `{material:1000, plant:工厂}`
- **THEN** Turn 2 material 为 `CLEARED`、plant 保留 `5100`；Turn 3 plant 为 `1000` 而 material 仍 unresolved/conflicted
- **AND** Turns 2 和 3 都为 `CLARIFY`、CallPlan 为 null、Gateway delta 为 0

#### Scenario: Explicit correction recovers the query

- **WHEN** 上述 Turn 3 后用户说 `这个物料是指上面的 DEMOA2，1000 是工厂`
- **THEN** material 为 `DEMOA2 / CONFIRMED`、plant 为 `1000 / EXPLICIT`，Frame 为 `READY`
- **AND** 只执行一次 parameters 为 `{material:DEMOA2, plant:1000}` 的 READ CallPlan

### Requirement: Pending interactions are singular, bound and separate from approval

系统 SHALL 用一个 `PendingInteraction` 表示 `SLOT_CLARIFICATION`、`CAPABILITY_CHOICE`、`BATCH_CONFIRMATION` 或 `PLANNER_CONFIRMATION`，并绑定 `frameId + stateVersion + registrySnapshotId + expiresAt`。一个 conversation 同时最多一个 READ pending interaction。pending answer 只能解决其 `expectedFields`；binding 不匹配或 15 分钟过期时 MUST 失效并重新澄清。READ pending MUST NOT 复用或替代 WRITE approval state。

#### Scenario: Valid pending answer resolves only the requested field

- **WHEN** pending 期待 material 且 binding 当前有效，用户明确回答 `DEMOA2`
- **THEN** material 变为 `CONFIRMED`，未被询问的 resolved plant 保持不变
- **AND** pending 被一次性消费，不修改 approval state

#### Scenario: Stale pending answer cannot execute

- **WHEN** pending 的 Frame、stateVersion、snapshot 任一不匹配或已经过期
- **THEN** 系统丢弃该 pending 并生成新的澄清结果
- **AND** Gateway validate/execute 调用数均为 0

### Requirement: Durable conversation protocol prevents lost updates and duplicate execution

TypeScript runtime SHALL 为 contextual READ 执行 `claim -> load -> resolve -> compareAndSwap -> decide/execute -> evidence -> release`。JSON local baseline SHALL 使用 per-conversation serialization、lease ownership、atomic rename 与 `stateVersion` CAS。lease conflict 返回 `CONVERSATION_BUSY`；CAS conflict 返回 `CONTEXT_VERSION_CONFLICT`；principal mismatch 和 malformed Session fail closed。相同 `turnId` 重试 MUST 返回已保存结果，不得重复应用 transition 或调用 Gateway。

#### Scenario: Concurrent turns cannot overwrite each other

- **WHEN** 两个 worker 针对同 conversation/stateVersion 并发处理不同 turn
- **THEN** 只有 lease owner 和第一个合法 CAS 可保存 next state
- **AND** loser 返回 structured conflict，状态不被覆盖，Gateway 调用为 0

#### Scenario: Duplicate turn is exactly once at the conversation boundary

- **WHEN** 已完成 `turnId` 被重试、客户端重连或进程重启后重新提交
- **THEN** runtime 返回原 run/result 并保持 `lastAppliedTurnId`
- **AND** Reducer application 和 Gateway execute 次数都不增加

#### Scenario: Malformed session is preserved

- **WHEN** Session 文件无法反序列化或 schema conversion 失败
- **THEN** runtime 返回 `CONTEXT_DESERIALIZATION_FAILED` 并保留原文件用于诊断
- **AND** 不写空 Session、不恢复 slots、不调用 Gateway

### Requirement: Contextual READ persists before execution through a two-phase protocol

Python Agent SHALL 提供 `resolve_read_turn`，在不构造或调用 Gateway client 的情况下返回 decision、next state、resolution report 和可选 READ CallPlan。TypeScript runtime MUST 在成功 CAS next `SessionStateV2` 后才可调用 server-internal `continue_resolved_read`。continuation MUST 重新校验 `turnId + frameId + stateVersion + registrySnapshotId + principalId`、READ side-effect classification 和 immutable CallPlan binding，不得重跑 LLM 或 Reducer，也不得接受浏览器提供的 continuation payload。

#### Scenario: CAS succeeds before one READ execution

- **WHEN** resolution 产生 READY Frame 和 SELECT，conversation CAS 成功且 execution binding 当前有效
- **THEN** runtime 在 CAS 后调用一次 `continue_resolved_read`
- **AND** continuation validate/execute 精确的 server-owned READ CallPlan 并保存 RunEvidence

#### Scenario: CAS or binding failure prevents execution

- **WHEN** CAS 失败、lease 丢失、principal/snapshot/frame/version/turn binding 漂移或 CallPlan 不是 READ
- **THEN** continuation fail closed，返回对应 structured error
- **AND** Gateway validate/execute 调用数均为 0

### Requirement: Registry drift and time expiry make context stale

active READ Frame SHALL 在 30 分钟无活动后标记 `STALE`。capability version/input schema/semantic type/governance/visibility 或 required inputs 变化时，旧 Frame MUST 标记 `STALE` 并在当前 snapshot 下重新校验；不得继续使用旧 visible capability set。capability schema 未变化时 MAY 重新绑定当前 snapshot，但仍需当前 principal visibility。

#### Scenario: Registry drift blocks continuation

- **WHEN** active Frame 的 required input、semantic type、governance 或 visibility 与当前 Registry 不一致
- **THEN** Frame 为 `STALE` 并要求 revalidation/clarification
- **AND** 不生成 SELECT 或 Gateway 调用

#### Scenario: Restart does not auto-execute a READY frame

- **WHEN** 服务重启后加载一个此前 READY 的 persisted Frame，但没有新的 user turn
- **THEN** runtime 只恢复 state，不自动创建 Run 或 continuation
- **AND** Gateway 和 SAP 调用数为 0

### Requirement: Legacy sessions migrate safely and rollout is observable

schema-v1 `LastContext` SHALL 惰性转换为 `INHERITED_LEGACY` slots 和 `STALE` Frame，首次合法保存时升级为 schema v2；不得批量重写、删除或直接执行旧 Session。rollout MUST 先冻结失败 fixture，再以 shadow 模式同时计算 legacy/frame-v2 decision，记录脱敏 decision/slot diff 而不增加 Gateway 调用或写 authoritative v2 state；随后只把 READ 切换为 Frame v2 权威。只有所有 hard gates 通过、diff 已分类且调用方迁移后，才可删除生产中的 destructive legacy merge/write；只读 stale migration decoder保留在本变更中。

#### Scenario: Legacy session cannot execute immediately

- **WHEN** runtime 首次加载含 successful `LastContext` 的 schema-v1 Session
- **THEN** 转换后的 Frame 为 `STALE` 且 slots provenance 为 `INHERITED_LEGACY`
- **AND** 用户未重新确认/校验前 decision 不为 SELECT、Gateway 调用为 0

#### Scenario: Shadow mode has no additional side effects

- **WHEN** legacy path 与 Frame v2 对同一 turn 产生不同 decision
- **THEN** shadow evidence 记录 `legacyDecision`、`frameV2Decision`、redacted slot diff、`wouldBlockLegacyExecution` 与 `wouldClarify`
- **AND** shadow computation 不额外调用 Gateway、不写 authoritative Session、不暴露 raw history/model payload

### Requirement: Gateway enforces Registry-declared READ input patterns before SAP

Registry input descriptors SHALL 支持可选、预校验的 full-string `pattern`。本变更 SHALL 为 in-scope READ capabilities 的 `sapnexus:Plant` 输入声明 `^[A-Z0-9]{4}$`，不得修改 `MM.PR.CreateDraft` WRITE definition。Java Registry loader MUST 在启动/load 时拒绝 invalid regex；Gateway validation MUST 在 dispatch/SAP 前组合 required/type/min/max/pattern checks，并继续返回 allowlisted `INVALID_PARAMETER`。

#### Scenario: Invalid language token is rejected before SAP

- **WHEN** READ request parameters 含 plant=`工厂`
- **THEN** Gateway validation 返回 `INVALID_PARAMETER` 和 field-safe message
- **AND** technical dispatcher、JCo/OData 与 SAP 调用数为 0

#### Scenario: Valid plant identifiers remain accepted

- **WHEN** READ request plant 为 `5100` 或 `1000` 且其他 required inputs 有效
- **THEN** pattern validation 通过并继续既有 READ validation/execution 路径
- **AND** Gateway 不交换 material/plant，也不根据 SAP business error 改写参数

### Requirement: Eval and release gates make unsafe context behavior non-compensable

项目 SHALL 提供 deterministic multi-turn fixtures、脱敏 recorded LLM fixtures 和 production-boundary fake-Gateway scenarios。每个 turn MUST 声明 expected Frame/slots/decision/CallPlan/Gateway deltas。release evaluator MUST 将 false `SELECT`、non-READY Gateway call、wrong slot role、visibility leakage、closed-set escape、duplicate-turn Gateway call、state overwrite after lease/CAS conflict、stale-frame execution 和 READ-created WRITE authority 的允许值设为 0；deterministic core pass rate 与 successful clarification recovery rate MUST 为 100%。missing/skipped/stale evidence MUST fail affected level，且其他分数不得抵消 hard gate。

#### Scenario: One false SELECT fails the release target

- **WHEN** 任一 context-conflict case 产生错误 SELECT、wrong CallPlan slot role 或 non-READY Gateway call
- **THEN** 对应 hard gate 失败且 requested release target exit 非零
- **AND** 报告列出 case、turn、stage、decision、Gateway delta 和 evidence refs

#### Scenario: Offline verification remains honest about live behavior

- **WHEN** deterministic、recorded 和 fake-Gateway suites 全部通过但未授权 live smoke
- **THEN** release report 可记录 offline governed-context pass，并保持 `liveSmoke.status=not_run`
- **AND** 文档不得宣称已验证 live SAP correctness、live LLM drift 或任何 SAP WRITE

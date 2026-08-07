---
role: technical-design
status: implemented
date: 2026-08-06
scope: governed-read-context
workflow: native-change-complete
---

# Governed READ Context Design

## 1. Status and purpose

本文档定义 SAP Nexus Agent 的统一 READ 对话上下文治理方案。设计已完成讨论确认，并已通过 Task 1-9 实施完成（Task 9 的收尾范围调整见 §20）；当前运行时的治理 READ 路径（`resolve_read_turn` / `continue_resolved_read` / `run_query` 携带 `read_state` 时）已不再触达 `LastContext` 合并或 `resolve_with_context`。`LastContext`、短历史窗口和 LLM-first `hybrid` 路径本身作为一条独立保留的非治理 legacy 模式（`--context` CLI 场景）继续存在，详见 §20；本文档的问题陈述与已批准决策（§2-§19）未因此变更。

本设计解决以下实测失败：

```text
Turn 1: DEMOA2 在工厂 5100 还有多少可用库存
Result: material=DEMOA2, plant=5100, success

Turn 2: 换个物料能查吗
Result: parameters={}, missing=[material, plant]

Turn 3: 查下这个物料1000工厂库存
LLM result: material=1000, plant=工厂
Gateway validation: success
SAP result: Material 1000 does not exist
```

失败并非单一 prompt 问题，而是三个边界同时失效：

1. `CLARIFY` 用空参数覆盖了此前有效上下文。
2. LLM 正常返回时，其参数直接进入后续选择路径，确定性上下文合并没有参与仲裁。
3. Gateway 只校验必填、类型和长度，`plant="工厂"` 仍可通过并触发 SAP READ。

## 2. Goals and non-goals

### 2.1 Goals

- 统一治理库存、采购订单及后续 READ capability 的多轮上下文。
- 将 LLM 输出降级为 advisory candidate，禁止模型直接写 Session 或执行参数。
- 使用确定性 Reducer 管理槽位继承、替换、清空、冲突和确认。
- 冲突或参数角色不明确时输出 `CLARIFY`，并保证 Gateway 调用为零。
- 复用现有 durable Session、RunEvidence、五态 `MatchDecision` 和 Registry snapshot 边界。
- 支持跨重启恢复、同 conversation 串行化、幂等 turn 和旧 Session 惰性迁移。
- 为每次上下文决策保留可解释、可回放的来源与仲裁证据。

### 2.2 Non-goals

- 不把 Conversation State 升级为执行权威。
- 不从聊天历史、summary 或模型输出恢复 principal、visibility、approval 或 WRITE 权限。
- 不改变现有 Human Approval、`ApprovalRecord`、PlanExecution 或 Action exactly-once 契约。
- 不实现跨会话相似问题检索、embedding memory 或用户业务事实长期记忆。
- 不选择 PostgreSQL、Redis 或其他 multi-worker shared store 产品。
- 不通过扩大 prompt 历史窗口代替结构化状态管理。
- 不允许模型生成或覆盖 RFC、OData URL、binding、credential 或其他技术执行字段。

## 3. Design decisions

| ID | Decision | Choice |
|---|---|---|
| D1 | Scope | 所有 READ capability，共用一种上下文模型 |
| D2 | WRITE boundary | READ Context 与 `ApprovalRecord`/Action 状态机完全分离 |
| D3 | Conflict policy | 确定性证据仲裁；歧义必问；非 READY 不执行 |
| D4 | State model | Typed `ReadContextFrame` + `SlotBinding` + `PendingInteraction` |
| D5 | LLM role | 只产生 `IntentEnvelope` 和 slot candidates，不产生可信执行参数 |
| D6 | State transition | 单一无副作用 `ContextReducer` 是唯一状态修改入口 |
| D7 | Storage | 扩展现有 durable Session，不建设第二套 event store |
| D8 | Concurrency | conversation lease + state version CAS + turn idempotency |
| D9 | History | 短窗口仅用于语言理解；结构化 frame 承载业务焦点 |
| D10 | Migration | 影子比较 -> READ 权威切换 -> pending/CAS -> 移除 legacy bridge |

## 4. Three-layer authority model

“上下文”拆成三个不可混用的层级：

| Layer | Content | Authority | Lifecycle |
|---|---|---|---|
| `GovernedContext` | principal、tenant、role、data scope、visible capability、Registry snapshot | execution authority | 每个 Run 重新建立 |
| `ConversationReadState` | READ 目标、槽位、指代、待澄清项、最近业务焦点 | advisory context | conversation 级持久化 |
| `RunEvidence` | `IntentEnvelope`、resolution report、`MatchDecision`、CallPlan、Gateway/SAP result | evidence and audit authority | 每个 Run 不可变保存 |

强制不变量：

- `ConversationReadState` 不能包含或提供身份、审批、credential、RFC、binding 或 WRITE 权限。
- Conversation State 保存成功不表示执行成功。
- 服务重启后不得因为发现一个 `READY` frame 就自动调用 Gateway。
- summary、Memory 和历史消息都不能重建 PlanExecution 或 Approval authority。

## 5. Target data flow

```text
Current utterance
        +
ConversationReadState
        +
GovernedContext / VisibleCapabilitySet / RegistrySnapshot
        |
        v
Candidate Extractors
├── LLM IntentEnvelope
└── deterministic spans / aliases / semantic validators
        |
        v
Deterministic ContextReducer
├── classify context operation
├── resolve explicit changes
├── inherit confirmed slots
├── validate semantic roles
├── detect conflicts
└── produce next state + resolution report
        |
        v
Read Decision Gate
├── READY --------------------> SELECT
├── COLLECTING / CONFLICTED --> CLARIFY
├── capability ambiguity -----> SHOW_OPTIONS
└── multiple goals -----------> ESCALATE_TO_PLANNER
        |
        v
Only SELECT may create a READ CallPlan
```

## 6. Core domain model

### 6.1 ConversationSessionV2

```text
ConversationSessionV2
├── schemaVersion: 2
├── stateVersion: integer
├── principalId
├── activeFrame: ReadContextFrame | null
├── recentFrames: ReadContextFrame[]
├── pendingInteraction: PendingInteraction | null
├── recentTurns: Turn[]
├── lastAppliedTurnId
└── lastRunId
```

约束：

- 同一时刻最多一个 active frame。
- `recentFrames` 最多保留 2 个已完成或已切换的 frame。
- recent frame 只能被“回到刚才的库存查询”等显式引用重新激活。
- 不根据 embedding、相似度或模型偏好自动恢复历史 frame。

### 6.2 ReadContextFrame

```text
ReadContextFrame
├── frameId
├── capabilityId
├── slots: Map<parameterName, SlotBinding>
├── status: COLLECTING | READY | CONFLICTED | STALE
├── createdTurnId
├── updatedTurnId
├── registrySnapshotId
└── capabilityVersion
```

状态含义：

- `COLLECTING`：至少一个 required slot 尚未解决。
- `READY`：capability 唯一、所有 required slot 均已解决、无冲突且 schema 有效。
- `CONFLICTED`：槽位角色不明确、候选互相冲突或模型与确定性证据冲突。
- `STALE`：Registry schema、capability version、visibility 或会话时效要求重新校验。

### 6.3 SlotBinding

```text
SlotBinding
├── name
├── value | candidates
├── state: RESOLVED | CONFLICTED | CLEARED
├── provenance: EXPLICIT | CONFIRMED | INHERITED | MODEL_CANDIDATE
├── sourceTurnId
├── sourceSpan
└── issues[]
```

`issues` 保存结构化原因，例如：

```text
invalid_semantic_value
ambiguous_slot_role
model_context_conflict
registry_schema_drift
invalid_by_gateway
```

模型 candidate 可以进入候选或 conflict evidence，但不能单独把 required slot 变为 `RESOLVED`。

### 6.4 PendingInteraction

```text
PendingInteraction
├── type:
│   SLOT_CLARIFICATION
│   CAPABILITY_CHOICE
│   BATCH_CONFIRMATION
│   PLANNER_CONFIRMATION
├── frameId
├── expectedFields
├── candidates
├── stateVersion
├── registrySnapshotId
└── expiresAt
```

约束：

- 一个 conversation 同时最多一个 READ pending interaction。
- pending 必须绑定 `frameId + stateVersion + registrySnapshotId`。
- 任一绑定不匹配时，pending 失效并重新澄清。
- `PendingInteraction` 不能替代 `ApprovalRecord`。

## 7. Context operation classification

Reducer 在合并参数前先把当前话语归类为上下文操作：

```text
CONTINUE_FRAME
REPLACE_SLOT
CLEAR_SLOT
SWITCH_CAPABILITY
CONFIRM_PENDING
REJECT_PENDING
NEW_MULTI_GOAL
```

| Utterance | Operation | Transition |
|---|---|---|
| `这个物料在 1000 工厂库存` | `CONTINUE_FRAME` | 继承 material，只更新 plant |
| `工厂改成 1000` | `REPLACE_SLOT(plant)` | material 保持，plant 更新 |
| `换个物料` | `CLEAR_SLOT(material)` | 仅清空 material，plant 保持 |
| `不查库存了，查采购订单` | `SWITCH_CAPABILITY` | 旧 frame 移入 recent，新建 PO frame |
| `对，就是 DEMOA2` | `CONFIRM_PENDING` | 只解决 pending 指定槽位 |
| `查库存并看看采购订单` | `NEW_MULTI_GOAL` | active frame 不被静默覆盖，进入 planner handoff |

## 8. Evidence precedence and arbitration

ContextReducer 按可解释证据等级仲裁，而不是使用一个数值 confidence 决定执行：

| Priority | Evidence | Example | May resolve required slot |
|---:|---|---|---|
| 1 | 当前轮明确纠正或确认 | `1000 是工厂`、`物料改成 M001` | Yes |
| 2 | 对 pending clarification 的合法回答 | 系统问工厂，用户答 `1000` | Yes |
| 3 | 当前轮确定性标签或句法 | `工厂 1000`、`1000 工厂`、`物料 DEMOA2` | Yes |
| 4 | active frame 中已确认值 | `这个物料` 继承 `DEMOA2` | Yes, as `INHERITED` |
| 5 | LLM candidate | 模型返回 `plant=1000` | No, advisory only |

仲裁规则：

1. 当前轮明确值可以覆盖继承值。
2. `CLEARED`、`CONFLICTED` 和仅由模型推测的值不得继承。
3. 同一 token 可能属于多个槽位时进入 `CONFLICTED`。
4. LLM candidate 与确定性证据冲突时不投票，直接 `CLARIFY`。
5. 当前轮出现两个互斥的同级明确值时进入 `CONFLICTED`。
6. semantic validator 只能排除非法值，不能靠格式唯一确定业务角色。

例如 `sapnexus:Plant` 的 validator 可以排除 `plant="工厂"`，但 `1000` 可能同时满足物料和工厂的字符串形态，因此仍需要句法、pending question 和 frame evidence 仲裁。

## 9. Frame state machine and decision gate

```text
                    required slots complete
        ┌─────────────────────────────────────────┐
        v                                         |
     COLLECTING --valid slot evidence----------> READY
        |                                          |
        | conflict                                 | explicit slot change
        v                                          v
    CONFLICTED --user clarification------------> READY
        |
        | capability/schema snapshot drift
        v
       STALE --revalidate----------------------> COLLECTING / READY
```

只有同时满足以下条件才能生成 `SELECT`：

```text
capability is unique
AND every required slot is RESOLVED
AND conflicts is empty
AND capability is visible to the current principal
AND frame is compatible with the current Registry schema
AND pending interaction is empty or deterministically consumed
```

否则：

- 缺参或槽位冲突 -> `CLARIFY`
- 少量能力候选无法唯一选择 -> `SHOW_OPTIONS`
- 多目标 -> `ESCALATE_TO_PLANNER`
- 不可见、未知、危险或技术覆盖 -> `REJECT`

## 10. Clarification behavior

`CLARIFY` 只修改有变化或冲突的槽位，不得用本轮空参数覆盖整个 frame。

目标行为：

```text
Previous:
  material=DEMOA2 / RESOLVED
  plant=5100 / RESOLVED

User: 换个物料能查吗

Next:
  material=CLEARED
  plant=5100 / RESOLVED / INHERITED
  pending=SLOT_CLARIFICATION(material)
  frame.status=COLLECTING
```

推荐回复：

> 可以，请提供新物料编号。工厂暂时沿用 5100，如需更换也可以一起说明。

### 10.1 Real failure sequence under the target model

在用户已经说过“换个物料”后，再说“查下这个物料 1000 工厂库存”：

- `1000 工厂` 为 plant 提供强确定性证据。
- “这个物料”试图恢复此前 material。
- material 已被显式 `CLEAR_SLOT`，不能自动复活。
- frame 保持 `CONFLICTED`/`COLLECTING`，Gateway 调用为零。

推荐回复：

> 你要查询的工厂是 1000。你说的“这个物料”是之前的 DEMOA2，还是要换一个新物料？

用户回答“这个物料是指上面的 DEMOA2，1000 是工厂”后：

```text
material=DEMOA2 / RESOLVED / CONFIRMED
plant=1000 / RESOLVED / EXPLICIT
frame=READY
decision=SELECT
```

## 11. Persistence and concurrency

### 11.1 Store contract

扩展现有 `DurableConversationStore`：

```text
load(conversationId, principalId)
claim(conversationId, workerId, ttl)
compareAndSwap(conversationId, expectedVersion, nextState)
release(conversationId, workerId)
```

当前 JSON 文件实现继续作为 local/single-worker baseline：

- 进程内 conversation mutex 串行化同一 conversation。
- `stateVersion` 检测陈旧写入。
- 临时文件加原子重命名保证文件完整性。
- store-agnostic interface 为未来 shared store 保留。

### 11.2 Turn protocol

```text
1. claim conversation lease
2. load session + stateVersion
3. build current GovernedContext / RegistrySnapshot
4. run candidate extractors
5. run deterministic ContextReducer
6. persist next state with compareAndSwap
7. derive MatchDecision
8. create READ CallPlan only for SELECT
9. append RunEvidence and response
10. release conversation lease
```

约束：

- lease 冲突返回 `CONVERSATION_BUSY`，Gateway 调用为零。
- CAS 失败返回 `CONTEXT_VERSION_CONFLICT`，Gateway 调用为零。
- 相同 `turnId` 重试时返回原结果，不重复应用状态转换或 Gateway 调用。
- Conversation lease 不替代 Run lease、PlanExecution lease 或 Approval claim。

### 11.3 Persist-before-execute rule

| Decision | State persisted first | Gateway |
|---|---|---:|
| `CLARIFY` | frame、conflicts、pending question | No |
| `SHOW_OPTIONS` | options、pending choice | No |
| `ESCALATE_TO_PLANNER` | planner confirmation handoff | No |
| `SELECT` | READY frame、resolution report、run reference | Yes, only after CAS success |
| store/CAS/lease failure | structured run error only | No |

## 12. History, expiry, and schema drift

### 12.1 History responsibilities

- `ReadContextFrame` 是业务焦点和 slot 的结构化来源。
- `recentTurns` 仅帮助理解自然语言和生成澄清问题。
- 初期继续使用最近 3 轮窗口，不通过扩大 prompt 修复状态问题。
- 历史进入 LLM 时继续作为不可信 `<durable_context_data>` 注入。
- 从历史中提取的值仍是 `MODEL_CANDIDATE`。
- Conversation summary 可以压缩叙事，但不能重建 Slot、Pending、CallPlan 或 Approval。

### 12.2 Expiry policy

时间值是服务端策略，不写入 capability 业务定义。初始策略：

- pending interaction 15 分钟未处理即失效。
- active READ frame 30 分钟无活动后标记 `STALE`，下次使用前确认。
- recent frame 随 conversation retention 清理。
- 用户创建新 conversation 时清空所有 READ frame 和 pending。

### 12.3 Registry drift

- capability version 和 input schema 未变化时，可重新绑定当前 snapshot。
- required input、semantic type、governance 或 visibility 变化时，frame 标记 `STALE`。
- stale frame 重新校验前不得生成 `SELECT`。
- 不得使用旧 visible capability set 继续执行。

## 13. Error handling

| Failure | Conversation state | User outcome | Gateway |
|---|---|---|---:|
| LLM unavailable | deterministic extractor + frame | 能确定则继续，否则澄清 | READY only |
| malformed LLM JSON | discard model candidates | deterministic path or clarify | no relaxed gate |
| invalid semantic value | record issue, discard candidate | clarify exact field | 0 |
| ambiguous slot role | frame=`CONFLICTED` | show known values and ask | 0 |
| conversation lease conflict | unchanged | previous turn still processing | 0 |
| CAS failure | no overwrite | retry/reload | 0 |
| Session deserialize failure | preserve source file, do not restore slots | context recovery failure | 0 |
| Registry drift | frame=`STALE` | revalidate/clarify | 0 |
| Gateway `INVALID_PARAMETER` | retain frame, record affected issue | request correction | no SAP execute |
| SAP `BUSINESS_ERROR` | do not infer new intent or rewrite slots | show SAP fact, allow explicit correction | one READ already occurred |
| crash after READ execute | RunEvidence determines known result | recover result or report unknown | no Session-driven replay |

`Material 1000 does not exist` 能证明 SAP 对该物料查询失败，但不能单独证明用户原意一定不是物料 `1000`。系统必须等待用户明确纠正，不能根据 SAP 错误自动交换 material/plant。

## 14. Security and governance boundaries

- principal、tenant、role、data scope 和 visibility 只来自受信 `GovernedContext`。
- Conversation State 和历史不得供应 capability visibility。
- technical fields 在候选提取阶段丢弃，并在 Gateway 再次防御。
- READ Frame 不能创建、恢复、确认或执行 `ApprovalRecord`。
- pending READ interaction 与 pending WRITE approval 不得合并。
- prompt/history injection 不得改变 closed set、required slot、side effect 或 governance。
- model、summary、Memory 和 recent frame 都不能升级 READ 为 WRITE。

## 15. Acceptance and test strategy

### 15.1 Test layers

| Layer | Subject | Core assertion |
|---|---|---|
| Reducer unit | inherit/replace/clear/conflict/confirm | exact next state and resolution report |
| Model contract | correct, wrong, malformed, malicious JSON | model cannot create trusted Slot |
| Session | CAS, lease, restart, migration | no lost update or duplicate application |
| Orchestrator integration | Frame -> MatchDecision -> CallPlan | non-READY means zero Gateway calls |
| Eval/release gate | complete multi-turn scenarios | false SELECT and wrong execution are zero |

### 15.2 Mandatory regression cases

#### Case A: direct plant switch

```text
Turn 1: DEMOA2 在工厂 5100 还有多少可用库存
Turn 2: 查下这个物料 1000 工厂库存
```

Expected:

```text
material=DEMOA2 / INHERITED
plant=1000 / EXPLICIT
decision=SELECT
Gateway calls=1
```

#### Case B: clear material before ambiguous reference

```text
Turn 1: DEMOA2 在工厂 5100 还有多少可用库存
Turn 2: 换个物料能查吗
Turn 3: 查下这个物料 1000 工厂库存
```

Expected:

```text
Turn 2: material=CLEARED, plant=5100, decision=CLARIFY, Gateway calls=0
Turn 3: plant=1000, material unresolved/conflicted, decision=CLARIFY, Gateway calls=0
```

#### Case C: explicit correction

```text
Turn 4: 这个物料是指上面的 DEMOA2，1000 是工厂
```

Expected:

```text
material=DEMOA2 / CONFIRMED
plant=1000 / EXPLICIT
decision=SELECT
Gateway parameters={material:DEMOA2, plant:1000}
```

#### Case D: recorded bad LLM payload

```json
{
  "capabilityId": "MM.Inventory.GetAvailability",
  "parameters": {
    "material": "1000",
    "plant": "工厂"
  }
}
```

Expected:

```text
plant="工厂" -> invalid_semantic_value
material=1000 -> MODEL_CANDIDATE, not RESOLVED
decision=CLARIFY
CallPlan=null
Gateway calls=0
```

### 15.3 Additional coverage

- Single-slot and multi-slot replacement.
- Explicit capability switching without incompatible slot inheritance.
- Explicit recent frame restoration.
- SHOW_OPTIONS candidate binding.
- Batch confirmation bound to exact frame/version.
- LLM-unavailable deterministic continuation.
- Snapshot drift before continuation.
- Two concurrent turns against one conversation.
- Duplicate `turnId` retry.
- Principal mismatch and history isolation.
- Prompt/history technical override injection.
- READ frame inability to restore WRITE authority.
- SAP failure followed by explicit parameter correction.

### 15.4 Hard gates

| Metric | Required |
|---|---:|
| false `SELECT` in context-conflict cases | 0 |
| Gateway calls from non-READY frame | 0 |
| wrong slot role entering CallPlan | 0 |
| visibility leakage | 0 |
| closed-set escape through prompt/history | 0 |
| duplicate Gateway call for same `turnId` | 0 |
| state overwrite after CAS/lease conflict | 0 |
| stale frame execution without revalidation | 0 |
| READ context creating WRITE authority | 0 |
| deterministic core scenario pass rate | 100% |
| direct execution from migrated legacy Session | 0 |
| successful recovery after clarification | 100% |

非硬门禁指标用于观察体验，不能抵消硬门禁：平均澄清轮数、conflict rate、模型 candidate 丢弃率、legacy/v2 decision diff、用户重述率、SAP invalid/business error rate。

### 15.5 LLM evaluation evidence

维护三类证据：

1. Deterministic fixtures：固定 utterance、prior frame、Registry snapshot 和预期 transition，作为合并门禁。
2. Recorded LLM fixtures：包含正确输出、错误输出、恶意输出和脱敏后的真实 bad case。
3. Live LLM canary：观察模型漂移，但不能成为唯一合并门禁。

Recorded fixtures 必须包含本次 `material=1000, plant=工厂`，不能只保存理想模型结果。

## 16. Backward-compatible migration

### 16.1 Legacy Session conversion

首次读取旧 Session 时惰性转换：

```text
LastContext.parameters
-> SlotBinding(
     state=RESOLVED,
     provenance=INHERITED_LEGACY
   )
```

由于旧状态缺少来源证据：

- migrated frame 初始为 `STALE`，不能直接执行。
- 用户下一轮明确引用时重新确认。
- 不批量重写现有 Session 文件。
- 保存下一轮结果时自然升级为 `schemaVersion=2`。
- 迁移失败不删除原文件，也不回退成空上下文后静默执行。

### 16.2 Rollout phases

#### Phase 0: freeze failure evidence

- 将本次真实对话和错误模型 payload 加入 Eval。
- 增加“非 READY 时 Gateway 调用为零”的断言。
- 不改变运行行为，先证明测试能暴露当前缺口。

#### Phase 1: introduce Frame and Reducer in shadow mode

- 新增 typed state、candidate extraction、Reducer 和 decision gate。
- 新旧路径同时计算，legacy 仍为权威路径。
- v2 只输出脱敏 decision diff，不调用 Gateway，不写正式 Session。

Shadow evidence:

```text
legacyDecision
frameV2Decision
slotDiff
wouldBlockLegacyExecution
wouldClarify
```

#### Phase 2: make Frame v2 authoritative for READ

- 库存和采购订单统一进入 Reducer。
- 只有 READY frame 能产生 SELECT。
- 保留 `LastContext` compatibility adapter 供未迁移调用方读取。
- WRITE capability 继续走现有审批链路。

#### Phase 3: unify READ pending and durability protocol

- 合并 CLARIFY、SHOW_OPTIONS、batch confirmation 和 planner confirmation。
- 增加 conversation lease、CAS 和 turn idempotency。
- 启用旧 Session 惰性迁移。
- 验证跨重启、并发和 Registry drift。

#### Phase 4: remove legacy bridge

满足以下条件后才移除 `LastContext` 和旧 `resolve_with_context`：

- 所有 hard gate 连续通过。
- shadow decision diff 均已分类并处理。
- frontend、CLI、Eval 和 release gate 已迁移。
- 没有未迁移调用方。
- 当前文档与 historical archive 的 implemented/proposed 边界明确。

## 17. Suggested module boundaries

新增 Python 模块：

```text
agent/sap_nexus_agent/
├── read_context.py
├── context_candidates.py
├── context_reducer.py
├── context_decision_gate.py
└── context_migration.py
```

修改边界：

| Module | Responsibility after migration |
|---|---|
| `llm_intent.py` | Produce advisory envelope and candidates only |
| `conversation_context.py` | Compatibility types during migration; no merge policy |
| `capability_selector.py` | Consume reducer-normalized result and emit five-state decision |
| `orchestrator.py` | Route decision; no embedded context merge rules |
| `registry_loader.py` | Load semantic types and validation metadata required by candidates/reducer |
| `frontend/src/runtime/durable/types.ts` | Versioned Session and frame mirror types |
| `DurableConversationStore` | Lease, CAS, migration-safe load/save |
| `agent-runtime-adapter.ts` | Turn sequencing and context transport |
| Gateway validation | Registry-derived parameter constraints; no language/coreference logic |

## 18. Verification scope for implementation

The implementation is expected to touch Python Agent, frontend durable runtime, Gateway validation, Eval and cross-language tests. It therefore meets the project HEAVY signal (`>2 modules` and `>5 files`) and should enter Comet Native through `/comet`.

This is not a structural OWL/Neo4j migration and does not require Classic/OpenSpec routing. It does not authorize or execute SAP WRITE and does not require Human Approval for implementation or READ verification.

Relevant verification is expected to include:

```bash
git status --short
scripts/verify-agent-callplan-evidence.sh
npm --prefix frontend run verify
```

If Registry/Gateway parameter schema changes, also run:

```bash
openspec list --json
openspec validate --all --strict
```

Inside the eventual Native change, every mandatory acceptance item must have current snapshot-bound evidence recorded through the Native workflow.

## 19. Deferred decisions

The following decisions are intentionally deferred and do not block this design:

- Multi-worker shared store product selection.
- Cross-conversation user preference memory.
- Long-history summarization implementation.
- Semantic retrieval of old frames.
- WRITE batch context and per-combination approval semantics.
- Automatic correction from SAP master-data errors.

Any future work in these areas must preserve the authority separation and zero-false-execution gates defined here.

## 20. Task 9 closeout: scope decision on §16.2 Phase 4

§16.2 Phase 4 originally called for removing `LastContext` and the legacy `resolve_with_context`
merge entirely once all Phase 0-3 conditions were satisfied. During Task 9 implementation, an
investigation found that the concrete deletion target (`intent.py`'s
`resolve_with_context` auto-dispatch, invoked when `context.last_context is not None`) is still
exercised end-to-end by an active, currently-passing test
(`agent/tests/test_conversation_context.py::test_core_scenario_clarify_then_select`) backing a
shipped, documented product feature: the CLI `--context` flag's sticky CLARIFY->SELECT
continuation (`agent/sap_nexus_agent/cli.py`; documented in `docs/runbooks/README.md` and
`docs/runbooks/12-conversational-context-and-multi-value-batch.md`).

This was escalated to the user, who confirmed a narrowed scope ("Option A") in place of the
literal Phase 4 text:

- `_read_context_mode()` (`agent/sap_nexus_agent/orchestrator.py`) no longer recognizes the
  string `"legacy"` as an opt-out rollout value; it now falls through to the `"v2"` default,
  identically to any other unrecognized value.
- A contract test was added proving the governed (Frame v2) READ path never calls
  `llm_intent.resolve_with_context`.
- `intent.py`'s auto-dispatch block, `llm_intent.resolve_with_context` itself, the CLI
  `--context` flag, and `test_conversation_context.py` were explicitly left untouched. They
  remain an intentionally-retained, non-governed legacy mode — a separate, already-shipped
  feature, not a residual of this design's rollout.

Full removal of `LastContext` and `resolve_with_context` (the original Phase 4 scope) is
deferred to a future, separately-scoped and separately-reviewed change if the `--context` CLI
feature is ever formally retired. See
`docs/superpowers/reports/2026-08-06-governed-read-context-verify.md` for the verification
evidence backing this task's narrowed scope.

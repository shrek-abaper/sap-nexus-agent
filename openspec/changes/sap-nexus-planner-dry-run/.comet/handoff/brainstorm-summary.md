# Brainstorm Summary

- Change: sap-nexus-planner-dry-run
- Date: 2026-07-25

## 确认的技术方案

基于 open 阶段 6 项高层决策（D1-D6）+ design 阶段 5 个 Open Question 澄清：

**S2-A - MatchDecision 决策层**

- D1 + Q4：`MatchDecision` 五态对象替代 `SelectionResult`（保留窄视图兼容）。SSE 混合映射：SELECT/CLARIFY/REJECT 复用现有 capability_selected/clarification/failure 路径；新增 `match_decision` 事件仅承载 SHOW_OPTIONS / ESCALATE_TO_PLANNER（含 candidates / handoff）。
- D2 + Q1 + Q2：rule 路径 `parse_intent` 改为扫描全部能力关键词集合（不再首命中即返回）；命中 >1 -> ESCALATE_TO_PLANNER；关键词歧义（弱匹配多能力，非明确多意图）-> SHOW_OPTIONS。LLM 路径 prompt 改为 detect all，`_payload_to_parse_result` 解析多候选。
- Q1：`ESCALATE_TO_PLANNER` handoff = `{ reason, matched_intents: [{capabilityId, parameters, missing}], utterance, registry_snapshot_id }`。S2-A 只检测收集，S2-B 从 matched_intents + Registry 构造 GoalSpec/CapabilityCard。
- D3 + Q3：visibility pre-filter 基于 governance + dataClassification。写能力（sideEffect=sap_write）在 handoff 可见（标记 requiresApproval），S2-B dry-run 可规划但标注需审批不执行；执行层不可见（S3 gate）。

**S2-B - Planner dry-run 层**

- D4 + Q5：`CapabilityCard` 从 Registry descriptor 投影 = `{ capabilityId, name, inputs, governance, visibility, producesFactTypes (from outputs.factTypeRef) }`。`PlanCompiler` 复用 S1 `semantic-planning-foundation` 的 PlanGraph validator（provenance/edges/governance/topological order），不重新实现图校验。
- D5：dry-run 输出 = `PlanGraph` + `gaps`（缺参/缺能力）+ `governanceFlags`（需审批/写副作用），可审计，不执行 Gateway/SAP。
- D6：Workbench 前端只读展示 MatchDecision 五态 + dry-run 预览（节点/边/参数来源/缺口/治理，折叠式）。

## 关键取舍与风险

- **MatchDecision 替代 SelectionResult**：保留 SelectionResult 窄视图（SELECT/CLARIFY/REJECT）渐进迁移，避免一次性破坏 orchestrator/eval。风险：窄视图可能长期残留 -> 缓解：一个发布周期后评估移除。
- **rule 多意图扫描**：关键词集合精化是关键，避免单意图误判为多意图（如"采购订单"含"订单"不应误匹配 PR）。风险：误判 -> 缓解：matcher Eval 覆盖单意图/多目标/歧义。
- **SSE 混合事件**：SELECT 复用 capability_selected，SHOW_OPTIONS/ESCALATE 新事件。风险：前端处理两种路径 -> 缓解：view-model 统一 MatchDecision 视图。
- **S2-B 复用 S1 validator**：PlanGraph 校验依赖 S1 契约稳定。风险：S1 契约变更 -> 缓解：S1 已归档，契约锁定。
- **写能力 dry-run 可见**：handoff 含写能力标记 governance。风险：用户误以为可执行 -> 缓解：前端明确标注"需审批/不执行"。
- **S2-A/S2-B 同 change**：范围偏大。缓解：tasks.md 分阶段，S2-A 先过 matcher Eval 再 S2-B。

## 测试策略

- **S2-A matcher Eval**：五类决策（SELECT 单意图齐参 / CLARIFY 缺参 / REJECT 技术覆盖 / SHOW_OPTIONS 关键词歧义 / ESCALATE_TO_PLANNER 多目标）；`false SELECT`（多目标静默降级为单 SELECT）作为回归失败项。
- **现有回归**：inventory / PO / PR eval 不破坏；`scripts/verify-agent-callplan-evidence.sh` 通过。
- **S2-B dry-run cases**：PlanCompiler 输出 PlanGraph + gaps + governanceFlags；断言不调用 Gateway validate/execute；PlanGraph 通过 S1 validator。
- **前端**：`summarizeTurn` / `buildChatBubbleState` 回归 + MatchDecision 五态渲染测试（纯函数 view-model）。
- **门禁**：`npm --prefix frontend run verify`、`openspec validate --all --strict`、`scripts/verify-agent-callplan-evidence.sh`。

## Spec Patch

- `semantic-match-decision/spec.md`：SHOW_OPTIONS 触发条件细化为"关键词歧义（utterance 弱匹配多能力关键词集合，非明确多意图）"。
- `planner-dry-run/spec.md`：CapabilityCard 字段明确含 `producesFactTypes`（from `outputs.factTypeRef`），供 PlanCompiler 从 GoalSpec desiredFactType 匹配。
- `agent-callplan-evidence/spec.md`：无需额外 patch（open 阶段 MODIFIED 已覆盖 MatchDecision 升级与多意图 ESCALATE）。

## 1. S2-A MatchDecision 决策对象

- [x] 1.1 定义 `MatchDecision` dataclass（`decision_type` / `candidates` / `rationale` / `handoff`），`decision_type` 为五态枚举
- [x] 1.2 `SelectionResult` 退为 `MatchDecision` 在 SELECT/CLARIFY/REJECT 三态的窄视图（向后兼容 wrapper）
- [x] 1.3 单元测试：五态构造与窄视图兼容

## 2. S2-A 多意图检测（修复 D-1）

- [x] 2.1 改 `parse_intent` rule 路径：扫描全部能力关键词集合，统计命中数，不再首命中即返回
- [x] 2.2 命中 >1 -> `ESCALATE_TO_PLANNER`；单命中走原参数提取逻辑
- [x] 2.3 改 LLM 路径 system prompt：从 "Select exactly one" 改为 "detect all matching capabilities；if >1, return escalation"
- [x] 2.4 改 `_payload_to_parse_result` 解析多候选并产出升级决策
- [x] 2.5 单元测试：多目标 utterance 升级、单意图不误判

## 3. S2-A selector 输出 MatchDecision

- [x] 3.1 `select_capability` 输出 `MatchDecision`（SELECT/CLARIFY/REJECT/SHOW_OPTIONS/ESCALATE_TO_PLANNER）
- [x] 3.2 `orchestrator.run_query` 适配 `MatchDecision`：SELECT 进 CallPlan，CLARIFY 返回澄清，REJECT 返回拒绝，SHOW_OPTIONS/ESCALATE 返回 handoff（不执行 Gateway）
- [x] 3.3 `agent-runtime-adapter.ts` / `workbench_output.py` 适配 `MatchDecision` 序列化

## 4. S2-A visibility pre-filter

- [x] 4.1 `CapabilityCard` 投影：从 `registry_loader` descriptor 生成（`capabilityId` / `inputs` / `governance` / `visibility`）
- [x] 4.2 visibility pre-filter：`sideEffect=none` + `dataClassification=internal` 默认可见；写能力 dry-run 可见但不可执行
- [x] 4.3 单元测试：读写能力可见性边界

## 5. S2-A matcher Eval

- [x] 5.1 新增 `evals/` matcher cases 覆盖五类决策（SELECT/CLARIFY/REJECT/SHOW_OPTIONS/ESCALATE_TO_PLANNER）
- [x] 5.2 `false SELECT`（多目标静默降级为单 SELECT）作为回归失败项
- [x] 5.3 现有 inventory/PO/PR eval 回归不破坏
- [x] 5.4 matcher Eval 退出标准全过（SHOW_OPTIONS case pending is_ambiguous，见 5.5）
- [x] 5.5 在 `intent.py` 实现 `is_ambiguous` 关键词歧义检测（主/弱关键词阈值表，Design Doc § 错误处理与边界条件）；un-skip matcher SHOW_OPTIONS case；复跑 matcher Eval 5/5 全过

## 6. S2-A Workbench 展示

- [ ] 6.1 `run-event-schema.ts` 新增 `MatchDecision` artifact kind（仅展示层，不改 Gateway/SAP 契约）
- [ ] 6.2 `view-model.ts` 渲染五态决策与候选
- [ ] 6.3 `AgentConsole.tsx` / `globals.css` 只读展示 `MatchDecision`（含 ESCALATE/SHOW_OPTIONS 的 handoff/候选）
- [ ] 6.4 前端测试（`summarizeTurn` / `buildChatBubbleState`）回归

## 7. S2-B planner 模块骨架

- [ ] 7.1 新增 `agent/sap_nexus_agent/planner/` 模块（`CapabilityCard` / `GoalSpec` / `PlanDraft` / `PlanCompiler`）
- [ ] 7.2 `CapabilityCard` discovery 实现（从 Registry 闭集 + Snapshot 投影）
- [ ] 7.3 `GoalSpec` / `PlanDraft` candidate 生成（复用 S1 `semantic-planning-foundation` schema）

## 8. S2-B PlanCompiler dry-run

- [ ] 8.1 deterministic `PlanCompiler` 实现：`GoalSpec` + Registry Snapshot -> `PlanGraph`
- [ ] 8.2 复用 S1 `PlanGraph` validator 校验（provenance / edges / governance / topological order），不重新实现
- [ ] 8.3 dry-run 输出：`PlanGraph` + `gaps` + `governanceFlags`，可审计
- [ ] 8.4 `PlanCompiler` 不调用 Gateway validate/execute 的断言测试

## 9. S2-B handoff 接入与展示

- [ ] 9.1 `ESCALATE_TO_PLANNER` handoff 接入 `PlanCompiler`，产出 dry-run 候选
- [ ] 9.2 Workbench 前端 dry-run 预览展示（节点/边/参数来源/缺口/治理，折叠式）
- [ ] 9.3 dry-run cases 进 eval

## 10. 验证与归档准备

- [ ] 10.1 `npm --prefix frontend run verify`（typecheck + test + build）通过
- [ ] 10.2 `openspec validate --all --strict` 通过
- [ ] 10.3 `scripts/verify-agent-callplan-evidence.sh` 通过
- [ ] 10.4 `docs/runbooks/10-capability-composition-contract.md` 更新（S2-A 完成、S2-B 完成、下一推荐）+ README index 同步

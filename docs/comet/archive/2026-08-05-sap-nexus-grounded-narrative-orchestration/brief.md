# Outcome

在不接生产 orchestrator、不创建 Human Approval、不调用 Gateway/SAP 且不执行 SAP WRITE 的前提下，实现 Runbook 19 的 grounded Narrative component/Eval：仅消费已归档 Runbooks 17-18 提供的 facts、`MaterialSupplySnapshot`、`RecommendationPlan` 与只读 proposal state，构造可逐 claim 追溯的 `NarrativeEnvelope`；LLM 仅改写该确定性输入，失败或返回 invalid JSON 时使用 deterministic template fallback。

# Scope

- 在 `frontend/src/runtime/narrative/` 新增 narrative input projection、`NarrativeEnvelope`/claim/evidence/state contracts、prompt contract、LLM candidate parser/validator、deterministic template renderer 和中英文状态文案。
- 输入只接受 `ReasoningFact[]`、`MaterialSupplySnapshot`、`RecommendationPlan` 与显式只读 proposal state；builder 将这些对象投影为稳定、有类型且带 source/evidence refs 的 content items。
- 输出至少包含 `summary`、`claims[]`、`evidenceRefs[]`、`limitations[]`、`recommendationRef`、`proposalRef`、`approvalState` 和 `templateFallbackUsed`；每个业务 claim 必须至少绑定一个已提供 evidence ref。
- LLM candidate 只能按已提供 claim identity 逐项改写，不得新增、删除、重复或改绑 claim/evidence/state；解析失败、invalid JSON、shape/identity/reference mismatch 或 model unavailable 均整体 fallback。
- 新增 component tests 与 versioned narrative Eval fixtures，覆盖 complete、partial、clarify、proposal pending、approved、executed、failed，以及 unsupported claim、invalid JSON、LLM failure 和 deterministic replay。

# Non-goals

- 不新增、推导或计算业务事实，不改变 `MaterialSupplySnapshot`、`RecommendationPlan` 或 `ActionProposal` 的内容、hash、状态和参数。
- 不接生产 orchestrator、`projectionRef`、SSE、Workbench、durable runtime、Gateway、JCo、OData 或 SAP。
- 不创建 `ApprovalRecord`/Human Approval，不把展示状态当作审批或执行证据，不执行任何 Action/SAP WRITE。
- 不实现 Runbook 20 Workbench、Runbook 21 governed Action 或 Runbook 22 end-to-end release gate。
- 不建设通用自然语言事实验证器；本期 validator 校验候选 JSON 与确定性 content projection 的完整一一对应和引用闭包，模型文本不得成为下游事实、建议、proposal、审批或执行输入。

# Acceptance examples

- complete snapshot + `RECOMMEND` plan + pending proposal 生成 100% grounded claims，proposal 文案明确为“待审批”/`pending approval`，不出现已批准或已执行表述。
- partial/incomplete snapshot 显式展示 completeness、freshness/missing-fact/limitation 信息；这些内容来自 projection，不由 LLM 补造。
- `CLARIFY` recommendation 显式展示需要补充的信息且没有 proposal；不猜数量、日期、采购组或 Action 参数。
- 只读 proposal state fixtures 分别渲染 pending、approved、executed、failed，状态 ref 原样保留；fixtures 不创建 approval 或执行 side effect。
- model unavailable、抛错、空响应、invalid JSON、未知/重复/缺失 claim、未知 evidence ref 或错误状态均使用 deterministic template fallback，facts、recommendation、limitations 和状态仍完整展示。
- Eval 中 claim grounding rate 为 100%，unsupported claim rate 为 0；相同确定性输入和 locale 产生相同 fallback envelope，所有 claim 可追溯到 fact/projection/rule/recommendation/proposal state。

# Constraints and invariants

- facts、projection、recommendation 和 proposal state 是唯一内容来源；LLM prompt 不接收 raw Gateway payload、conversation text、自由检索内容、凭据或执行接口。
- narrative input builder 与 template fallback 必须 deterministic；LLM candidate validation 必须 fail closed，不能部分接受可疑输出。
- 每个 content item 和 claim 都有稳定 identity、source kind/ref 与非空 evidence refs；envelope 顶层 `evidenceRefs` 是 claim refs 的确定性去重并集。
- LLM 只可返回与提供 content items 一一对应的 JSON 改写；它不能改变 recommendation/proposal refs、limitations、approval state 或 `templateFallbackUsed`。
- `pending_approval` proposal 不是 Human Approval；approved/executed/failed 仅作为外部只读 proposal state fixture 输入，不新增状态转换、审批记录或执行能力。
- 本 change 只证明 component/Eval 成熟度，不得描述为 live end-to-end multi-capability orchestration。

# Decisions

- 延续 Runbooks 17-18 的 TypeScript component/Eval 落点，在 `frontend/src/runtime/narrative/` 实现纯组件，并复用现有 projection/recommendation contracts；不修改 Python 单能力 narrator 或生产 orchestrator。
- `NarrativeProposalState` 作为只读展示输入，区分 `none`、`pending_approval`、`approved`、`executed`、`failed`；它引用 proposal/state evidence，但不修改已归档 `ActionProposal`（其状态仍仅为 `pending_approval`）。
- narrative content 先由 deterministic builder 冻结为 typed content items，再交给可注入的 model adapter 返回 JSON；validator 要求 claim IDs、source refs 和 evidence refs 与输入完全一致，否则整体 fallback。
- 中英文模板使用固定状态词和确定性排序；LLM 不可改写 limitations、recommendation/proposal refs 或 proposal/approval state。
- grounding 指标按业务 claims 计算：有且仅有输入引用闭包中的 evidence refs 才算 grounded；任何未知 claim/source/evidence 都算 unsupported 并使候选无效。Eval 目标固定为 grounding 100%、unsupported 0%。
- 用户于 2026-08-05 确认本 brief 与完整目标 specification；该确认仅授权 component/Eval Build，不构成 Human Approval，也不授权 SAP WRITE。

# Open questions

- 无。

# Verification expectations

- 按 TDD 先新增 narrative contracts/builder/validator/fallback/Eval 失败测试，再实现最小代码使其通过。
- 运行 narrative focused tests、`npm --prefix frontend run verify` 和 Runbook 19 指定的 `.venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -q`。
- 运行 `scripts/verify-agent-callplan-evidence.sh`、`openspec validate --all --strict` 和 `git diff --check`；这些命令只验证既有 contracts/component，不执行 SAP WRITE。
- Native Verify 为每个 acceptance item 绑定 fresh receipt，并在 `verification.md` 记录实际结果、跳过项、spec consistency 和已知限制。

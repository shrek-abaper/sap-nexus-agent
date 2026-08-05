# Outcome

在不接生产 orchestrator、不调用 Gateway/SAP、不执行 SAP WRITE 的前提下，实现可重放的 Recommendation Decision component：消费同一 RegistrySnapshot 下的 `MaterialSupplySnapshot`、versioned `RuleSet` 和用户显式约束，输出可解释的 `RecommendationPlan`，并在输入充分且规则命中时最多生成一个 `pending_approval` 的 `ActionProposal`。

# Scope

- 在 frontend runtime 新增 recommendation 领域类型、精确版本 `RuleSetRegistry`、确定性 decision engine 和 canonical hash。
- `RuleSet` 声明 projection 版本、必需用户约束、freshness 上限、允许的 Action capability 和确定性 shortage 策略；本期 component/Eval 使用显式注册的规则，不发布隐式生产默认规则。
- 输入门禁覆盖 projection completeness/freshness、同 snapshot 绑定、required constraints、事实唯一性与单位、RuleSet 冲突、Action capability 注册/支持状态。
- 输出 `RecommendationPlan` 的 facts、rules、assumptions、limitations、rejected alternatives，以及至多一个带完整 parameters / parameterSources / factsUsed / ruleSetRefs / proposalHash 的 `ActionProposal`。
- 新增 component tests 与 recommendation Eval cases；回归 frontend、Agent call-plan、既有 PR Eval 和 OpenSpec。

# Non-goals

- 不接生产 orchestrator、`projectionRef`、SSE、Workbench 或 durable runtime。
- 不调用 LLM、Gateway、JCo、OData 或 SAP；不创建 ApprovalRecord，不执行任何 Action/SAP WRITE。
- 不实现 grounded narrative（Runbook 19）、Workbench（Runbook 20）、审批与 exactly-once Action（Runbook 21）或 E2E release gate（Runbook 22）。
- 不实现多 Action、多 WRITE、Saga、补偿、ML prediction、Knowledge/RAG、Dynamic Planner 或业务阈值管理 UI。

# Acceptance examples

- 完整且 fresh 的 `MaterialSupplySnapshot` + 同 snapshot 的已注册 RuleSet + `requiredQuantity`、`targetDate`、`purchasingGroup`，当可用库存不足时，稳定地产生同一 RecommendationPlan 和一个 `MM.PR.CreateDraft` proposal；参数及其来源完整，状态仅为 `pending_approval`。
- 可用库存满足需求时输出 `NO_ACTION` RecommendationPlan，保留 facts/rules/rejected alternative，且没有 proposal。
- 缺 `requiredQuantity`、`targetDate` 或 `purchasingGroup` 时输出 `CLARIFY` 和明确缺项，不猜数量、日期、采购组或其他 Action 参数。
- partial/incomplete 或 stale projection、unknown RuleSet、同 tuple 重复/冲突 RuleSet、snapshot 不一致、unsupported/unregistered Action 均 fail-closed 为 `INSUFFICIENT_INPUT`，不产生 proposal。
- facts 输入顺序变化不改变 plan/proposal hash；输出始终至多一个 proposal，且 component 没有执行接口或 SAP side effect。

# Constraints and invariants

- LLM 只可在后续叙事层表达，不参与本期计算；所有判断、参数派生和 hash 均为确定性逻辑。
- RuleSet、projection、proposal capability 和 decision request 必须绑定同一个非空 `snapshotId`；RuleSet 仅按精确 `ruleSetId@version` 解析。
- MVP 对 `partial` 和 `incomplete` projection 一律阻断 proposal；freshness 上限由 RuleSet 显式声明，engine 不提供隐藏默认值。
- `MaterialSupplySnapshot` 的 PO `orderQuantity` 缺交期/未清量语义，不作为可用供应自动抵扣；该候选做法必须记录为 rejected alternative，不可猜测。
- shortage quantity 仅由用户 `requiredQuantity` 与唯一的 `availableQuantity` fact 按已注册规则计算；material/plant/unit 来自同一受治理 fact，delivery date/purchasing group 来自用户显式约束。
- `ActionProposal` 不是审批或执行证明；本期不得触发 SAP WRITE。

# Decisions

- 使用与 Runbook 17 相邻的 TypeScript runtime component（`frontend/src/runtime/recommendation/`），复用现有 canonical JSON / SHA-256 工具和 projection 类型。
- 采用面向首个固定场景的 versioned material-shortage RuleSet，而不是建设通用表达式语言或自由规则执行器。
- 结果状态区分 `RECOMMEND`、`NO_ACTION`、`CLARIFY`、`INSUFFICIENT_INPUT`：用户可补齐的显式约束缺失归入 `CLARIFY`，治理/事实/版本/freshness 失败归入 `INSUFFICIENT_INPUT`。
- 规则 freshness 阈值由每个 RuleSet 显式提供；Eval 数据固定具体阈值与时间以保证重放，不推断生产 SLA。
- PO facts 可作为 plan facts/limitations 证据，但由于当前 fact contract 不含交付日、open quantity 或收货状态，不参与 shortage 数量计算。
- proposal 参数固定映射为 `material`、`plant`、`quantity`、`unit`、`delivery_date`、`purchasing_group`；每项都携带可检查的来源。
- 用户于 2026-08-05 确认本 brief 与完整目标 specification；该确认仅授权 component/Eval Build，不构成 Human Approval 或 SAP WRITE 授权。

# Open questions

- 无。

# Verification expectations

- 按 TDD 先写 recommendation registry/engine/Eval 失败测试，再实现最小代码使其通过。
- 运行 recommendation focused tests，并运行 `npm --prefix frontend run verify`。
- 运行 `.venv/bin/python -m pytest agent/tests -q`、`.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json`、`scripts/verify-agent-callplan-evidence.sh` 和 `openspec validate --all --strict`；均只验证既有 READ/Action 契约，不执行 SAP WRITE。
- Native Verify 为每个 acceptance item 绑定 fresh receipt，并在 `verification.md` 记录实际结果、跳过项、spec consistency 和已知限制。

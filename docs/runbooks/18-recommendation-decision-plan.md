# Recommendation and Decision Plan Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `18-recommendation-decision-plan` |
| Version | `v0.2.0` |
| Status | `Implemented / Archived` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbook 17 |
| Unblocks | Runbooks 19 and 21 |

## 1. Goal

通过已注册 `RuleSet` 将组合事实与用户约束转换为可解释的 `RecommendationPlan`，并在输入充分时最多形成一个 `ActionProposal`。

## 2. Current Baseline

- 技术架构已有 `RecommendationPlan` 契约，sandbox `MM.PR.CreateDraft` Action 与 approval 纵切已验证。
- Runbook 17 已实现并归档 versioned `OutputProjectionRegistry` 与 `MaterialSupplySnapshot` component/Eval 基线；completeness、limitations、lineage 和 output hash 可作为 RuleSet 输入门禁。
- Runbook 18 已实现 snapshot-bound versioned `RuleSetRegistry`、确定性 `RecommendationDecisionEngine`、input sufficiency、可重放 `RecommendationPlan` 与最多一个 `pending_approval` Action proposal，范围仅为 component/Eval。
- 生产 orchestrator / `projectionRef` 仍未接线；本 runbook 不得顺带把 component projection 描述为 live end-to-end composition。
- 库存和 PO 事实不足以单独推导 PR 数量、交付日期和采购组。

## 3. Contracts and Data Flow

```text
MaterialSupplySnapshot + user constraints + registered RuleSet@version
-> input sufficiency check
-> RecommendationPlan
-> optional ActionProposal { capabilityId, parameters, parameterSources,
                             factsUsed, ruleSetRefs, proposalHash }
```

`RecommendationPlan` 必须列出 facts、rules、assumptions、limitations 和 rejected alternatives。缺少 required rule input 时返回 `CLARIFY` 或 `INSUFFICIENT_INPUT`，不得生成半成品 Action 参数。

## 4. Scope and Non-goals

- Scope：RuleSet registry/schema、确定性 decision engine、input sufficiency、RecommendationPlan、单 Action proposal。
- Non-goal：不执行 Action、不由 LLM 计算、不支持多 WRITE/Saga、不自动补偿、不接 ML prediction 或 Knowledge/RAG。

## 5. Safety Boundaries

- LLM 不可生成数量、日期、采购组、account assignment 或其他 Action 参数。
- RuleSet、参数来源和 proposal capability 必须存在于同一 RegistrySnapshot。
- partial/incomplete projection 默认不得形成 WRITE proposal，除非规则显式且经治理允许；MVP 一律阻断。

## 6. Acceptance Criteria

- 输入充分时建议与 proposal 可重放，facts/rules/parameter sources 完整。
- 缺需求量、目标日期或采购组时产生明确澄清，不猜值。
- conflicting rules、stale projection、unknown RuleSet 和 unsupported Action fail-closed。
- 每个 plan 最多一个终点 Action proposal，且状态仅为 `pending_approval`。

## 7. Verification

```bash
npm --prefix frontend run verify
.venv/bin/python -m pytest agent/tests -q
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

进入 Runbook 19：基于已归档 RecommendationPlan / ActionProposal component contract 实现 grounded `NarrativeEnvelope` 与 template fallback。生产 orchestrator / `projectionRef` 接线仍 deferred；Action 执行仍等待 Runbook 21 的 Human Approval，不得把 `pending_approval` proposal 当作执行授权。

## Session Closeout - 2026-08-05

### Completed

- Native change `sap-nexus-recommendation-decision-plan` 完成 Shape、Build、Verify 和 Archive。
- 新增 TypeScript recommendation contracts、snapshot-bound exact `RuleSetRegistry`、deterministic decision engine 和 canonical proposal/plan hash。
- 实现同 snapshot/projection/RuleSet/Action 治理、freshness/completeness/constraint/fact gates，以及 `RECOMMEND` / `NO_ACTION` / `CLARIFY` / `INSUFFICIENT_INPUT` 四态。
- 新增 19 个 reviewable recommendation Eval cases；PO ordered quantity 因缺 delivery/open/receipt semantics 不参与 shortage 计算并记录 rejected alternative。
- proposal 仅为单个 `pending_approval` 数据对象；本期未接 orchestrator、Gateway、Approval 或 SAP WRITE。

### Verified

- `npm --prefix frontend run verify`：31 files / 316 tests 通过，production build 成功。
- `.venv/bin/python -m pytest agent/tests -q`：954 passed / 1 skipped。
- `.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json`：9/9 passed。
- `scripts/verify-agent-callplan-evidence.sh`：954 passed / 1 skipped，Eval 7/7 passed。
- `openspec validate --all --strict`：20 passed / 0 failed。

### Blockers

- 无 Runbook 19 component/Eval blocker。
- 生产 orchestrator、Narrative、Workbench、Human Approval 和 SAP WRITE 仍分别由 Runbooks 19-22 管理，不属于本次完成范围。

### Next Start Here

1. 阅读 `docs/runbooks/19-grounded-narrative-orchestration.md`。
2. 仅消费 grounded RecommendationPlan/projection evidence 构建 `NarrativeEnvelope`；不得从 LLM 补造事实、规则或 Action 参数。
3. 保持生产 orchestrator 与 SAP WRITE deferred。

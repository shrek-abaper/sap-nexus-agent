# Recommendation and Decision Plan Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `18-recommendation-decision-plan` |
| Version | `v0.1.1` |
| Status | `Planned / Current Entry` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbook 17 |
| Unblocks | Runbooks 19 and 21 |

## 1. Goal

通过已注册 `RuleSet` 将组合事实与用户约束转换为可解释的 `RecommendationPlan`，并在输入充分时最多形成一个 `ActionProposal`。

## 2. Current Baseline

- 技术架构已有 `RecommendationPlan` 契约，sandbox `MM.PR.CreateDraft` Action 与 approval 纵切已验证。
- Runbook 17 已实现并归档 versioned `OutputProjectionRegistry` 与 `MaterialSupplySnapshot` component/Eval 基线；completeness、limitations、lineage 和 output hash 可作为 RuleSet 输入门禁。
- 当前多能力路径没有组合事实到建议的 runtime。
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
.venv/bin/python -m pytest agent/tests -q
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

先基于已归档 `MaterialSupplySnapshot` 契约设计 RuleSet registry 与 input sufficiency bad cases，再形成可重放的 `RecommendationPlan` 和最多一个已注册 Action proposal。建议生成完成后进入 Runbook 19；Action 执行仍等待 Runbook 21。

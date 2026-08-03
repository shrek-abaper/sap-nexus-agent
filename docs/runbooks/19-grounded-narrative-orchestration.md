# Grounded Narrative Orchestration Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `19-grounded-narrative-orchestration` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbooks 17-18 |
| Unblocks | Runbook 20 |

## 1. Goal

实现跨能力的 grounded narrative：以 facts、projection、recommendation 和 proposal 状态为唯一内容来源，输出可校验 claims/evidence/limitations，再渲染自然语言。

## 2. Current Baseline

- 单能力 narrator 已受 `ReasoningFact` 约束并有 narrative grounding Eval。
- 当前没有跨节点 `NarrativeEnvelope`，也没有统一展示 partial、limitation、proposal 和 approval 状态。

## 3. Contracts and Data Flow

```text
ReasoningFact[] + MaterialSupplySnapshot + RecommendationPlan + ActionProposal status
-> deterministic narrative input builder
-> LLM narrative candidate
-> claim/evidence validator
-> NarrativeEnvelope
-> localized rendering
```

`NarrativeEnvelope` 至少包含 `summary`、`claims[]`、`evidenceRefs[]`、`limitations[]`、`recommendationRef`、`proposalRef`、`approvalState` 和 `templateFallbackUsed`。每个业务 claim 必须绑定 evidence ref。

## 4. Scope and Non-goals

- Scope：narrative input projection、LLM prompt contract、claim validator、模板 fallback、中英文状态文案。
- Non-goal：不新增事实、不做计算、不改变建议或 proposal、不把模型文本作为审批/执行输入。

## 5. Safety Boundaries

- LLM 只能改写已提供字段；无 evidence 的 claim 删除或使 narrative validation 失败。
- incomplete/partial、freshness 和 limitation 必须显式展示。
- “建议”“待审批”“已批准”“已执行”不得混写；UI/叙事标签不是执行证据。
- LLM 不可用或输出不合法时必须使用 deterministic template fallback。

## 6. Acceptance Criteria

- claim grounding rate 100%，unsupported claim rate 0。
- complete、partial、clarify、proposal pending、approved、executed、failed 状态均有 fixture。
- LLM failure/invalid JSON 不影响 facts、recommendation 和状态展示。
- narrative 可按 claim 追溯到 fact/projection/rule/proposal。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -q
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

冻结 `NarrativeEnvelope` 后进入 Runbook 20。Workbench 不应直接消费自由文本，必须消费 envelope 与引用对象。

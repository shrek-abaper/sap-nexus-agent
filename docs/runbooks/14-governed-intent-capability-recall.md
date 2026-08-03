# Governed Intent and Capability Recall Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `14-governed-intent-capability-recall` |
| Version | `v0.1.1` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbook 13 |
| Unblocks | Runbook 15 |

## 1. Goal

形成完整的 LLM-first `IntentEnvelope` 与受治理 capability recall：既理解多目标、指代和约束，又只在当前主体可见的已注册能力闭集中输出五态 `MatchDecision`。

## 2. Current Baseline

- `hybrid` 模式已经是 LLM 优先，仅 `LlmUnavailable` 回退规则。
- 五态 `MatchDecision`、多意图/歧义检测和 matcher Eval 已实现。
- 当前 `IntentParseResult`、`matched_intents` 与 planner handoff 可工作，但意图、目标、约束、证据和 recall score 尚未形成统一版本化 envelope。
- 当前能力规模小，不需要 embedding 或 Knowledge/RAG。

## 3. Contracts and Data Flow

```text
utterance + governed conversation context + VisibleCapabilitySet
-> LLM IntentEnvelope candidate
-> deterministic normalization / parameter allowlist
-> lexical + alias + example recall
-> optional bounded rerank
-> parameter-fit + governance validation
-> MatchDecision
```

`IntentEnvelope` 至少包含：目标列表、候选 capability、参数候选、用户约束、歧义、引用 turn、model evidence 和 `snapshotId`。模型输出未知 capability、技术字段或非法参数时丢弃并产生结构化原因。

## 4. Scope and Non-goals

- Scope：LLM-first parsing、多目标拆分、closed-set recall、bounded rerank、五态决策、跨轮 CLARIFY/SHOW_OPTIONS/ESCALATE continuation。
- Non-goal：不执行能力、不生成任意工具、不接 embedding/vector store/Knowledge/RAG、不做跨会话相似问题检索。

## 5. Safety Boundaries

- LLM candidate 永远是 advisory；deterministic matcher 才能产生 `MatchDecision`。
- `SELECT` 必须唯一且 required parameters 满足；多个目标必须进入 planner。
- Action intent 只能形成 proposal 方向，不能因措辞强烈而执行。
- LLM 不可补写 Registry 未声明的参数或 capability relation。

## 6. Acceptance Criteria

- 单能力、歧义、多目标、能力缺口、技术覆盖、越权和跨轮用例全部有 Eval。
- false `SELECT` rate 为 0；visibility leakage rate 为 0。
- LLM 不可用时规则 fallback 行为可解释且不扩大执行能力。
- 每个 decision 可回放到 envelope、候选、过滤原因和 snapshot。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests/test_llm_intent.py agent/tests/test_match_decision.py agent/tests/test_capability_selector.py -q
.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

先冻结 `IntentEnvelope` 和 `MatchDecision` 版本，再进入 Runbook 15。能力规模未达到阈值前，不引入 embedding/RAG 基础设施。

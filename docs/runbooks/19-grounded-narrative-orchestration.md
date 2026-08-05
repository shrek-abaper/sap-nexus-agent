# Grounded Narrative Orchestration Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `19-grounded-narrative-orchestration` |
| Version | `v0.2.0` |
| Status | `Implemented / Archived` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbooks 17-18 |
| Unblocks | Runbook 20 |

## 1. Goal

实现跨能力的 grounded narrative：以 facts、projection、recommendation 和 proposal 状态为唯一内容来源，输出可校验 claims/evidence/limitations，再渲染自然语言。

## 2. Current Baseline

- 单能力 narrator 已受 `ReasoningFact` 约束并有 narrative grounding Eval。
- Runbooks 17-18 已归档 `MaterialSupplySnapshot`、`RecommendationPlan` 与单个 `pending_approval` `ActionProposal` component contracts。
- Runbook 19 已实现 deterministic narrative input projection、strict lossless LLM rewrite validation、model timeout/invalid JSON fallback、grounding metrics、`NarrativeEnvelope` 与中英文状态文案，范围仅为 component/Eval。
- 生产 orchestrator、Workbench、Human Approval 和 SAP WRITE 仍未接线；只读 approved/executed/failed fixtures 不是运行时审批或执行证据。

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

- LLM 只能对已提供 claim 做 lossless 标点/空白改写；任何数值、标识、状态、词序、claim/source/evidence identity 变化均使整份 candidate 失败并回退模板。
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

Runbook 19 已通过 Native change `sap-nexus-grounded-narrative-orchestration` 完成并归档。下一实施入口为 Runbook 20：Workbench 只消费 envelope 与引用对象，不直接消费自由文本；不得顺带接入 Human Approval 或 SAP WRITE。

## Session Closeout - 2026-08-05

### Completed

- 实现 `NarrativeSourceInput -> NarrativeInputProjection -> NarrativeEnvelope` 的纯 TypeScript component，唯一内容源为 facts、projection、recommendation 和只读 proposal state。
- 冻结 claim/source/evidence identity、limitations、recommendation/proposal refs、completeness 与 approval state；重复 identity、snapshot/projection/proposal mismatch 均 fail-closed。
- LLM candidate 采用 strict JSON 一一对应契约，只接受保持正文、内部标点与 whitespace 边界不变的 lossless 展示改写；数值、ID、状态、completeness 或任意内容变化整体 fallback。
- model unavailable、throw、timeout、empty/invalid JSON、missing/duplicate/unknown claim/reference 均回退 deterministic 中英文模板，不保留部分 model text。
- 新增 versioned narrative Eval，覆盖 complete、partial、incomplete、clarify、pending、approved、executed、failed、invalid JSON、unsupported claim、timeout 和 replay。

### Verified

- Narrative focused tests：2 files / 36 tests 通过；claim grounding rate 100%，unsupported claim rate 0%。
- `npm --prefix frontend run verify`：TypeScript、33/33 Vitest files、352/352 tests、Next.js production build 全部通过。
- `.venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py -q`：45 passed。
- `scripts/verify-agent-callplan-evidence.sh`：954 passed / 1 skipped，Eval 7/7、13/13、9/9、10/10、3/3，strict OpenSpec 20/20。
- `openspec validate --all --strict`：20 passed / 0 failed；`git diff --check` 通过。
- 独立 code review 两轮修复自由文本状态/数值篡改、timeout、grounding coverage、duplicate identity、内部标点与 whitespace 绕过后，最终 Critical/Important/Minor 为 0/0/0。

### Blockers

- 无 Runbook 20 component/UI blocker。
- 生产 orchestrator / `projectionRef`、durable narrative event、Human Approval 和 SAP WRITE 仍为明确 deferred 边界，不能把本期 component/Eval 描述为 live end-to-end orchestration。

### Next Start Here

1. 阅读 `docs/runbooks/20-workbench-plan-evidence-experience.md`。
2. Workbench 只消费 `NarrativeEnvelope`、claims/evidence refs、limitations 和只读状态对象；不得直接信任自由文本。
3. 保持 Human Approval 与 SAP WRITE deferred 到 Runbook 21。

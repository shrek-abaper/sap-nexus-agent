# Comet Design Handoff

- Change: ontology-goal-model-interpreter
- Phase: design
- Mode: compact
- Context hash: 9b112b72b5456a4398e469e06412c1176c5299f9079a61aa78eb82ab88f84fd5

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/ontology-goal-model-interpreter/proposal.md

- Source: openspec/changes/ontology-goal-model-interpreter/proposal.md
- Lines: 1-21
- SHA256: 7f0be10c516145c8bbddb2b48b214c6df3057b8cc85cfd433be34ad1f29c2dae

```md
## Why

The ontology read-analysis path ships with a fixture-driven `FakeGoalInterpreter`: the new DSH tool only answers the six closed `questionType` cases. The environment already configures a paid OpenAI-compatible model (DeepSeek-V4-Flash via LLM_*). C3 step 3 lets the model act as goal interpreter — producing only an untrusted SemanticGoalDraft — behind an explicit live flag, with one bounded repair turn, while every existing downstream guard (schema, technical scan, allowlist, visible READ producers, WRITE rejection) remains the sole authority.

## What Changes

- New `ModelGoalInterpreter` in `ontology_planning` reusing `OpenAiCompatibleLlmClient.chat_json`: system prompt describes only the release allowlist (fact types, fields, object selectors, four operators, READ-only/caliber rules) and demands the SemanticGoalDraft v1 JSON shape.
- Two-turn bounded draft loop in the Python coordinator/planner service: draft → validate; on failure feed structured issues back once; terminal classification unchanged (unknown field after repair → semantic_gap; technical/bounds → rejected).
- Live gate on both sides: the DSH handler selects the model only when `SAP_NEXUS_LLM_LIVE=1`; the Python side independently rejects `interpreter:"model"` unless the same flag is set. Free-form `question` utterance becomes the model input; `questionType` remains the fake/offline path.
- DSH tool spec gains optional `question` parameter; description states model is draft-only and offline default.
- Live evaluation harness `evals/ontology-read-analysis/model-eval.py` (manual, never in default test runs) for Q1-Q7-style utterances; recorded evidence report.

## Capabilities

- Modified: `ontology-analysis-chat-tool` — model-interpreter selection and live flag.

## Impact

- Python: new `model_interpreter.py`, shared draft pipeline helper; coordinator/planner_service changes; tests with scripted fake clients (no paid calls in CI).
- TS: handler/registry live routing and optional `question` param; unit tests with injected runners.
- Costs only when the flag is on; default behavior stays fully offline.

```

## openspec/changes/ontology-goal-model-interpreter/design.md

- Source: openspec/changes/ontology-goal-model-interpreter/design.md
- Lines: 1-21
- SHA256: a6d22333518b615f0ad8e410fcfa98cabaf95421ffe494028c954f35b785fcb0

```md
## Context

C3 shipped flag-gated DSH access with FakeGoalInterpreter. This change adds the paid model as an alternative draft producer behind SAP_NEXUS_LLM_LIVE. Reuses OpenAiCompatibleLlmClient (existing DeepSeek-V4-Flash configuration).

## Decisions

- **D1 shared draft pipeline**: extract draft selection/WRITE-precheck/validation/repair into one helper used by both coordinator and planner_service (they currently duplicate the flow), preventing drift between CLI and TS planner modes.
- **D2 dual live gate**: TS handler picks interpreter; Python re-checks the env flag (defense in depth; TS can be bypassed).
- **D3 prompt from release**: allowlist/operator vocabulary rendered from the pinned release, never hard-coded duplicates; JSON example for stock/grouping shapes included.
- **D4 two-call cap**: interpreter tracks calls; tests assert counts; timeout/max_tokens bounded via existing client settings.
- **D5 manual live eval only**: model-eval.py prints pass/gap table; not executed in CI; evidence recorded in the verify report from one authorized run.

## Risks / mitigations

- Model cost → flag default off, ≤2 calls/analysis, repair only on validation failure.
- Hallucinated fields/operators → existing draft validation rejects; terminal mapping converts to semantic_gap/rejected.
- Prompt drift from C1 assets → prompt generated from pinned release.

## Rollback

Unset flag (immediate); delete additive files for full removal; fake path and four semantic tools untouched.

```

## openspec/changes/ontology-goal-model-interpreter/tasks.md

- Source: openspec/changes/ontology-goal-model-interpreter/tasks.md
- Lines: 1-25
- SHA256: 434a3611cd90416243fee54c89ce413020c076bf42aa8c09e673aebbef5a548e

```md
# Tasks — ontology-goal-model-interpreter

## 1. Shared draft pipeline + fake interpreter feedback seam

- [ ] 1.1 Extract draft selection/write-precheck/validation into `draft_pipeline.py` used by coordinator + planner_service; interpreter Protocol gains optional `feedback` arg.
- [ ] 1.2 Tests: fake path unchanged across CLI/coordinator/planner; dedup regression.

## 2. ModelGoalInterpreter

- [ ] 2.1 New `model_interpreter.py`: allowlist-derived system prompt (facts/fields/operators/selectors/caliber rules), chat_json call, SemanticGoalDraft-compatible dict; repair feedback; call counter.
- [ ] 2.2 Tests with scripted fake LLM client: valid draft, repaired draft (2 calls), persistent rejection (2 calls), non-JSON failure → failed.
- [ ] 2.3 Prompt unit tests: no BAPI_/URL, lists four operators and allowlisted fields.

## 3. Live gates and wiring

- [ ] 3.1 Python: interpreter "model" requires SAP_NEXUS_LLM_LIVE=1 else MODEL_INTERPRETER_NOT_AUTHORIZED; CLI/analyze mode passes interpreter through; TS handler selects model vs fake and forwards `question`.
- [ ] 3.2 DSH tool spec gains optional `question`; registry/handler tests for flag on/off with injected runner.

## 4. Live evaluation (manual, paid)

- [ ] 4.1 `evals/ontology-read-analysis/model-eval.py`: Q1-Q7-style utterances → table of draft validity/status/calls; run once with live flag, save report under evals/ontology-read-analysis/model-eval-report.md.

## 5. Gates and archive

- [ ] 5.1 Full offline suites (Python + npm verify), openspec strict; record evidence; verify; archive local.

```

## openspec/changes/ontology-goal-model-interpreter/specs/ontology-analysis-chat-tool/spec.md

- Source: openspec/changes/ontology-goal-model-interpreter/specs/ontology-analysis-chat-tool/spec.md
- Lines: 1-47
- SHA256: aa836ab6c37861194b91a28d8cc8f23967594c25db3dac550807a29aa46d421c

```md
# Ontology Analysis Chat Tool — model interpreter delta

## ADDED Requirements

### Requirement: Flag-gated model interpreter selection

The DSH ontology tool SHALL send the user's free-form `question` to the paid model interpreter only when `SAP_NEXUS_LLM_LIVE=1`; otherwise it SHALL use the offline fake interpreter keyed by `questionType`. The Python runtime SHALL independently reject `interpreter: "model"` unless the same flag is set, regardless of TS behavior.

#### Scenario: Live flag off stays offline

- **WHEN** a request carries `interpreter: "model"` without `SAP_NEXUS_LLM_LIVE=1`
- **THEN** the response is `rejected` with `MODEL_INTERPRETER_NOT_AUTHORIZED` and no model API call is made

#### Scenario: Live flag on routes free text to the model

- **WHEN** `SAP_NEXUS_LLM_LIVE=1` and the tool receives a `question` utterance
- **THEN** the model is invoked exactly once with a system prompt containing only allowlisted fact fields and the four operator ids, and its output is parsed as SemanticGoalDraft v1

### Requirement: Bounded single repair turn

On an invalid first draft the system SHALL feed the structured validation issues to the model exactly once and retry. It SHALL never make more than two model calls per analysis, and SHALL classify the final outcome using the existing terminal rules: unreleasable fields → semantic_gap; technical keys/bounds/schema violations → rejected.

#### Scenario: Repaired draft succeeds

- **WHEN** the first model draft references a non-allowlisted field and the second draft uses only allowlisted fields
- **THEN** exactly two model calls occur and the analysis completes

#### Scenario: Persistent bad draft terminates

- **WHEN** both drafts fail validation with DRAFT_TECHNICAL_KEY
- **THEN** the response is `rejected`, no execution occurs, and exactly two calls were made

### Requirement: Model prompt confinement

The model SHALL receive no credentials, gateway URLs, capability RFC names, or SAP technical bindings, and its prompt SHALL state the read-only/caliber rules (order quantity is not arrival/ATP; no arrival/demand facts exist in this release).

#### Scenario: Prompt contains only semantic vocabulary

- **THEN** the rendered system prompt lists the allowlisted fact fields and the four operator ids, and contains no `BAPI_` strings or URLs

### Requirement: Offline default regression

With the flag unset, the six `questionType` cases, 24-case matrix, and all existing DSH semantic-tool behavior SHALL remain green without any model call.

#### Scenario: Matrix stays offline

- **THEN** the default test suites pass with no network access required and the fake interpreter path is unchanged

```

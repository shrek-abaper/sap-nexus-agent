# Tasks — ontology-goal-model-interpreter

## 1. Shared draft pipeline + fake interpreter feedback seam

- [x] 1.1 Extract draft selection/write-precheck/validation into `draft_pipeline.py` used by coordinator + planner_service; interpreter Protocol gains optional `feedback` arg.
- [x] 1.2 Tests: fake path unchanged across CLI/coordinator/planner; dedup regression.

## 2. ModelGoalInterpreter

- [x] 2.1 New `model_interpreter.py`: allowlist-derived system prompt (facts/fields/operators/selectors/caliber rules), chat_json call, SemanticGoalDraft-compatible dict; repair feedback; call counter.
- [x] 2.2 Tests with scripted fake LLM client: valid draft, repaired draft (2 calls), persistent rejection (2 calls), non-JSON failure → failed.
- [x] 2.3 Prompt unit tests: no BAPI_/URL, lists four operators and allowlisted fields.

## 3. Live gates and wiring

- [x] 3.1 Python: interpreter "model" requires SAP_NEXUS_LLM_LIVE=1 else MODEL_INTERPRETER_NOT_AUTHORIZED; CLI/analyze mode passes interpreter through; TS handler selects model vs fake and forwards `question`.
- [x] 3.2 DSH tool spec gains optional `question`; registry/handler tests for flag on/off with injected runner.

## 4. Live evaluation (manual, paid)

- [x] 4.1 `evals/ontology-read-analysis/model-eval.py`: Q1-Q7-style utterances → table of draft validity/status/calls; run once with live flag, save report under evals/ontology-read-analysis/model-eval-report.md.

## 5. Gates and archive

- [x] 5.1 Full offline suites (Python + npm verify), openspec strict; record evidence; verify; archive local.

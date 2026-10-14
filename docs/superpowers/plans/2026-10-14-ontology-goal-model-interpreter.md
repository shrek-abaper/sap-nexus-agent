---
change: ontology-goal-model-interpreter
design-doc: docs/superpowers/specs/2026-10-14-ontology-goal-model-interpreter-design.md
base-ref: 82444b0
archived-with: 2026-10-14-ontology-goal-model-interpreter
---

# Ontology Goal Model Interpreter — Implementation Plan

> Subagents disabled; TDD; paid calls only behind SAP_NEXUS_LLM_LIVE.

- [x] Task 1: shared draft_pipeline (selection/precheck/fact gate/one repair); coordinator + planner_service reuse
- [x] Task 2: ModelGoalInterpreter (allowlist-derived prompt, chat_json, normalize_document, repair feedback, bounded calls)
- [x] Task 3: dual SAP_NEXUS_LLM_LIVE gate (Python + TS handler), question param
- [x] Task 4: model-eval.py + one authorized live run (8/8 terminals, 8 calls); report committed
- [x] Task 5: gates + archive

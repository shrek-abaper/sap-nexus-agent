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

# SAP Nexus End-to-End Agent Eval Release Gate Verification

## Conclusion

Runbook 22 passed Native Verify with `42/42` acceptance items and is archived at `docs/comet/archive/2026-08-05-sap-nexus-end-to-end-agent-eval-release-gate/`. The offline gate selected `L3_ACTION_GOVERNED` from `9/9` passing cases with all four non-compensable hard gates passing. This is fake/sandbox evidence only; live SAP READ and WRITE smoke remain `not_run`.

## Scope Verified

- Governed Python-to-TypeScript composition handoff and server READ Gateway adapter.
- Production `CompositionCoordinator` wiring across executor, facts, projection, recommendation, narrative and durable evidence.
- Agent runtime L2 replay and Runbook 21 plan-aware L3 approval/continuation reuse.
- Versioned L1/L2/L3 fixtures, evaluator, hard gates, deterministic scenario runner and CLI report.
- PlanExecutor timeout timer cleanup required for a promptly terminating CLI process.

## Commands and Results

| Command | Result |
|---|---|
| `npm --prefix frontend run verify` | PASS: TypeScript typecheck, `50` test files / `428 passed`, Next.js production build |
| `.venv/bin/python -m pytest agent/tests -q` | PASS: `959 passed, 1 skipped` |
| `scripts/verify-agent-callplan-evidence.sh` | PASS: registry/semantic contracts, Agent tests, Eval `7/7 + 13/13 + 9/9 + 10/10 + 3/3`, OpenSpec `20/20` |
| `.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json` | PASS: `9/9` |
| `openspec list --json` | PASS: no active Classic changes |
| `openspec validate --all --strict` | PASS: `20 passed, 0 failed` |
| `npm --prefix frontend run release-gate -- --profile all` | PASS twice: `9/9`, `L3_ACTION_GOVERNED`, `liveSmoke=not_run` |
| normalized report comparison | PASS: deleting only `startedAt/completedAt` produced no diff |

## Release Metrics

| Level | Cases | Visibility leakage | Approval bypass | Unsupported claims | Fact lineage |
|---|---:|---:|---:|---:|---:|
| L1 | `3/3` | `0` | `0` | `0` | `100%` |
| L2 | `3/3` | `0` | `0` | `0` | `100%` (`32/32` in E2E projection) |
| L3 | `3/3` | `0` | `0` | `0` | `100%` (`32/32` in E2E projection) |

## Safety Evidence

- Static deterministic and recorded fixtures produce fixture/recording refs only; only real execution scenarios produce `run:` refs.
- L2 replay reads the durable run twice without increasing two READ Gateway execute calls.
- L3 records one pending approval with WRITE execute count `0`, then exact approval and duplicate continuation leave total WRITE execute count at `1`.
- Report payloads are allowlisted and contain no credential, raw model response or raw SAP payload.
- No live LLM or SAP service was contacted by the release gate.

## Skipped Checks

- Live SAP READ smoke: `not_run`; no live environment evidence was requested for this change.
- Live SAP WRITE smoke: `not_run`; no exact-subject Human Approval was provided, so execution is prohibited.

## Residual Risks

- Local JSONL/file stores prove durable replay but are not a shared multi-worker/HA production store.
- `LocalPlaceholderPrincipalInjector` is a server-owned local baseline, not a production identity provider.
- Offline fake/sandbox results do not prove SAP data freshness, live connectivity or live transaction behavior.
- Knowledge/RAG, general Dynamic Planner, multi-WRITE/Saga and automatic compensation remain reserved/out of scope.

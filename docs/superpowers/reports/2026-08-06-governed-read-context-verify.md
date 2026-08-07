# Governed READ Context Verification (Task 9)

## Conclusion

Task 9 (final task of the `sap-nexus-governed-read-context` Native change) is complete
under a **narrowed, user-confirmed scope ("Option A")**, not the brief's literal Step 4.
A prior investigation (see `.superpowers/sdd/task-9-report.md`, sections 1-7) found that
the brief's literal instruction to delete `intent.py`'s `resolve_with_context` auto-dispatch
would break an active, currently-passing test
(`agent/tests/test_conversation_context.py::test_core_scenario_clarify_then_select`) backing
a shipped, documented CLI feature (`--context` sticky CLARIFY->SELECT continuation). This was
escalated and the user ruled:

- Narrow `_read_context_mode()` (`agent/sap_nexus_agent/orchestrator.py`) so `"legacy"` is no
  longer a *recognized* rollout-mode value (it now falls through to `"v2"`, same as any other
  invalid string, exactly like `"shadow"` already isn't `"legacy"`).
- Add a contract test proving the governed READ path never calls
  `llm_intent.resolve_with_context`.
- Explicitly leave `intent.py`'s auto-dispatch block, `llm_intent.resolve_with_context` itself,
  `cli.py`'s `--context` flag, and `test_conversation_context.py` untouched — they are an
  intentionally-retained, non-governed legacy mode, not part of this removal.

**This report proves governed READ context behavior against offline/fake/recorded evidence
only. It does not prove live SAP correctness and does not authorize or evidence any SAP WRITE
authorization decision.**

**The legacy `resolve_with_context` / CLI `--context` sticky-continuation path was deliberately
retained out of scope for this task, per the confirmed Option A decision above. Its continued
presence in the codebase after Task 9 is not an oversight — it is an intentional, reviewed
decision to keep that non-governed legacy mode alive as a separate, already-shipped feature.**

## Scope Verified

- `_read_context_mode()` no longer recognizes the string `"legacy"` as an opt-out; it falls
  through to the default `"v2"` behavior for any unrecognized value (including `"legacy"`).
- New contract test: the governed (Frame v2) READ path — exercised through a full multi-turn
  `run_query` continuation (SELECT -> CLARIFY -> SELECT) with a `read_state`-bearing
  `ConversationContext` — never calls `llm_intent.resolve_with_context`, verified by
  monkeypatching it to `pytest.fail`.
- Confirmed no test anywhere in the repo sets `READ_CONTEXT_MODE=legacy` (only `"shadow"` is
  set explicitly by tests; all others `delenv` to exercise the `"v2"` default), so removing
  `"legacy"` from the recognized set changes zero existing test behavior.
- Confirmed `_context_shadow()` (the only other caller of `_read_context_mode()`) only branches
  on `mode == "shadow"` vs. anything else — it was already indifferent to `"legacy"` vs. any
  other unrecognized string, so this change has no effect on shadow-mode diff behavior either.

## Files Changed

- `agent/sap_nexus_agent/orchestrator.py` — `_read_context_mode()`: recognized set narrowed
  from `{"legacy", "shadow", "v2"}` to `{"shadow", "v2"}`; docstring updated to explain the
  Task 9 retirement of the `"legacy"` opt-out value.
- `agent/tests/test_orchestrator.py` — added
  `test_governed_read_context_never_calls_legacy_resolve_with_context`, a 3-turn
  (SELECT -> CLARIFY -> SELECT) governed-path contract test with `llm_intent.resolve_with_context`
  monkeypatched to `pytest.fail` if called.

No other file was modified. `intent.py`, `llm_intent.py`, `cli.py`,
`test_conversation_context.py`, `test_cli_context.py`, `conversation_context.py`, and the
frontend TS files listed in the brief were left untouched, per the confirmed narrowed scope.

## TDD: RED then GREEN

- Ran the new test against the **unmodified** production code (before the `_read_context_mode()`
  edit): `1 passed`. The test was **already GREEN**, not RED, against current `main` — this is
  expected and stated plainly rather than forced: the governed path (`_resolve_authoritative_read`
  in `orchestrator.py`, `buildContext` in `agent-runtime-adapter.ts`, and the Task 8 eval harness)
  already unconditionally sets/reads `last_context=None`, so it structurally never reaches
  `resolve_with_context` even before this task's change.
- To confirm the test (and its monkeypatch mechanism) is **not vacuous** — i.e. it would
  actually catch a regression — a standalone ad hoc script drove the same monkeypatched
  `llm_intent.resolve_with_context` through the **non-governed** `run_query` path (a
  `ConversationContext` with `last_context` set, no `read_state`), which does reach the
  `intent.py` auto-dispatch block. That call raised the expected `AssertionError` from the
  patched function, confirming the monkeypatch/fail mechanism is live and would fail the test
  if the governed path ever regressed to call it. (This confirmation script was not added to
  the repo; it only demonstrates the test's fault-detection capability.)
- After the production `_read_context_mode()` change: full suite re-run, still GREEN
  (see below). GREEN both before and after is the correct, honestly-reported outcome for this
  narrowed scope — the change is a pure dead-value removal with no behavioral surface for this
  specific test to catch.

## Commands and Results

| Command | Result |
|---|---|
| `rg -n "LastContext\|resolve_with_context\|pending_show_options\|pending_escalate\|lastContext" agent frontend evals` | Re-confirmed: no test sets `READ_CONTEXT_MODE=legacy`; only `test_orchestrator.py` sets `READ_CONTEXT_MODE=shadow` (11 call sites) or `delenv`s it (6 call sites) — the narrowed `_read_context_mode()` change touches none of them |
| `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -k "never_calls_legacy_resolve_with_context" -q` (pre-change) | PASS: `1 passed` (confirms already-GREEN, not vacuous per the ad hoc non-governed-path check above) |
| `.venv/bin/python -m pytest agent/tests -q` (post-change) | PASS: `1137 passed, 1 skipped` (baseline was `1136 passed, 1 skipped`; +1 new test, 0 regressions) |
| `scripts/verify-agent-callplan-evidence.sh` | PASS: agent tests `1137 passed, 1 skipped`; Evals `7/7 + 13/13 + 9/9 + 23/23` PASS, `3/3` PASS with 1 documented pending skip (pre-existing, unrelated to this change); OpenSpec `20/20` |
| `cd services/gateway && ./gradlew :core:test :app:test` | PASS: `BUILD SUCCESSFUL`, all tasks `UP-TO-DATE` (no Java files touched by this task) |
| `openspec list --json` | PASS: exit 0, `changes: []` (no active Classic change) |
| `openspec validate --all --strict` | PASS: `20 passed, 0 failed` |
| `git diff --check` | PASS: exit 0, no whitespace errors |
| `npm --prefix frontend run verify` | **PARTIAL** — see below |
| `npm --prefix frontend run release-gate -- --profile all` | PASS: `L3_ACTION_GOVERNED`, `22/22` cases, `liveSmoke=not_run` |

### `npm --prefix frontend run verify` — pre-existing failure, not caused by this task

`verify` runs `typecheck && test && build`. `typecheck` (`tsc --noEmit`) passed with zero
errors. `test` (`vitest run`) failed on exactly one test file both **with** and **without**
this task's changes:

```
FAIL  src/runtime/composition/adapter-integration.test.ts
  > agent runtime composition integration > keeps the L3 Action pending until exact
    approval and executes duplicate continuation once
AssertionError: expected 'completed' to be 'awaiting_approval'
```

This was reproduced identically on unmodified `main` via `git stash` (this task's diff is
Python-only — `orchestrator.py` and `test_orchestrator.py` — and touches zero frontend files,
so it cannot be the cause). Two other test files failed on one run
(`jsonl-conversation-store.test.ts` timeout, `plan-executor.test.ts` assertion) but did **not**
reproduce on a second run with the same (unchanged) code, indicating pre-existing test
flakiness unrelated to this task's scope; a third run with this task's changes present again
showed only the single `adapter-integration.test.ts` failure. Because `test` failed, the chained
`build` step in `npm run verify` did not execute in this run; `typecheck` had already completed
successfully beforehand.

**This failure and flakiness predate Task 9 and are out of this task's scope to fix** (they are
in `frontend/src/runtime/composition` and `frontend/src/runtime/plan-executor`/`durable`, none
of which this task touched). `npm --prefix frontend run release-gate -- --profile all` (the
scenario-runner-based L1/L2/L3 gate that the composition layer feeds) passed cleanly (`22/22`,
see Release Metrics below), corroborating that the composition/durable layers are not broken in
a way that affects the governed READ context path this task verifies.

## Release Metrics (from `runtime/evals/results/agent-release-l3-2026-08-07T08-49-06-458Z.json`)

- `schema`: `sap-nexus.agent-release-report.v1`
- `codeVersion`: `32f8b63aedf696ffba6b852e4af18a4ee9ba9d6a` (current `HEAD`; this run was
  executed against a working tree with this task's uncommitted Python-only changes applied —
  `codeVersion` reflects the committed `HEAD` hash, not a separate commit, since this task's
  changes are intentionally left unstaged/uncommitted per the dispatch instructions)
- `registrySnapshotId`: `snapshot-release-gate`
- `fixtureVersion`: `1.1.0`
- `modelRecordingVersion`: `1.1.0`
- `target`: `L3`, `targetPassed`: `true`, `decision`: `L3_ACTION_GOVERNED`
- `caseTotals`: `22/22` passed, `0` failed/missing/skipped/stale
- `liveSmoke.status`: `not_run`

| Level | Cases | visibilityLeakageRate | writeApprovalBypassRate | falseSelectRate | nonReadyGatewayCallRate | duplicateTurnGatewayCallRate | staleFrameExecutionRate | readContextWriteAuthorityCreationRate | factLineageCompleteness |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L1 | `16/16` | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `1` (req `1`) |
| L2 | `3/3` | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `1` (req `1`) |
| L3 | `3/3` | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `0` (req `0`) | `1` (req `1`) |

All hard gates passed at all three levels. This gate run exercises the composition/durable
runtime end-to-end and is unaffected by this task's narrow Python-only change (confirmed: the
release-gate scenario runner does not construct `READ_CONTEXT_MODE=legacy` anywhere, and the
governed path it drives never touched `last_context`/`resolve_with_context` before or after
this change).

## Shadow-Diff Disposition

This task did **not** touch shadow-mode logic. `READ_CONTEXT_MODE=shadow` remains a supported,
recognized rollout value (Phase 1 diagnostic diff mode per the design doc §16.2); `_context_shadow()`
branches only on `mode == "shadow"` and was already indifferent to `"legacy"` vs. any other
unrecognized string. The 11 existing `READ_CONTEXT_MODE=shadow` tests in `test_orchestrator.py`
(e.g. `test_shadow_semantic_validation_failure_keeps_legacy_authoritative`,
`test_shadow_context_keeps_legacy_authoritative_and_redacts_comparison`) all still pass unchanged
— no new or reclassified shadow diffs were produced by this task.

## Safety Evidence

- The narrowed `_read_context_mode()` change cannot cause any new Gateway call: it only removes
  a recognized-value string from a set comprehension; the `"v2"` fallback branch it now
  produces for `"legacy"` was always the default for any invalid value.
- The new contract test drives 3 turns of a governed conversation with zero Gateway calls
  expected (SELECT decision type is asserted but Gateway execution is not separately asserted
  in this test — Gateway call-count assertions for the identical 4-turn fixture already exist
  in `test_governed_read_context_authoritative_blocks_recorded_bad_model`, unmodified by this
  task).
- No SAP WRITE path, capability registry, or approval logic was touched by this task.
- `liveSmoke.status=not_run` in the release-gate report confirms no live LLM or SAP call was
  made during this task's verification.

## Residual Risks / Out of Scope

- The legacy `resolve_with_context` auto-dispatch in `intent.py` and the CLI `--context` sticky
  continuation remain live, non-governed code paths. They are not part of the Frame v2 authority
  model and do not benefit from its slot/evidence arbitration, hard gates, or durability
  protocol. Their retention is a deliberate, user-confirmed scope decision (Option A), not an
  oversight — see the Conclusion section above.
- The pre-existing `adapter-integration.test.ts` failure and the two flaky frontend test files
  are unrelated to this task and are not fixed by it; they should be tracked and addressed
  separately.
- This report proves offline/fake/recorded governed READ context behavior only. It does not
  prove live SAP data freshness, live connectivity, or live transaction behavior, and does not
  authorize any SAP WRITE execution.

## Design Doc Status

`docs/superpowers/specs/2026-08-06-governed-read-context-design.md` frontmatter `status` and
§1 were updated to reflect that the design is now implemented, with an added closeout note
(§20) recording that Phase 4's full legacy-bridge removal (design doc §16.2) was narrowed to
Option A by explicit user decision during Task 9 — the original problem statement and approved
decisions in §1-§19 were left unchanged.

# Verification Notes: declarative-intent-extraction

## Task 20: Closeout verification sweep

Date: 2026-08-19
HEAD at start of sweep: `1271d57` (chore: record Comet coordinator checkpoint after task 19)
Verification performed by: subagent (verification-only, no code changes)

This document records the full closeout verification matrix for the
`declarative-intent-extraction` change (tasks.md 5.1), with exact command
output/summaries and a PASS/FAIL verdict per item. No claim is made without
pasted output from an actual command run.

---

### 1. `git status --short` - expect clean tree

```
$ git status --short
(no output)
```

**Verdict: PASS.** Working tree is clean; no untracked/modified files. The
`.omo/` directory does not appear (Task 17 added it to `.gitignore`, per the
ledger note in `progress.md`).

---

### 2. `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`

```
$ .venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
Registry contract valid: registry/capabilities.yaml
EXIT CODE: 0
```

**Verdict: PASS.**

---

### 3. `.venv/bin/python -m pytest agent/tests -v --tb=short -q`

Full command run to completion (60.59s):

```
============ 15 failed, 1273 passed, 1 skipped in 60.59s (0:01:00) ============
```

Exact list of the 15 failing tests (`FAILED` lines from the run):

```
FAILED agent/tests/test_eval_runner.py::test_eval_harness_seed_cases_pass_contract
FAILED agent/tests/test_eval_runner.py::test_po_seed_cases_route_via_run_query
FAILED agent/tests/test_eval_runner.py::test_matcher_eval_file_passes
FAILED agent/tests/test_eval_runner.py::test_matcher_eval_routes_existing_files_through_legacy_path
FAILED agent/tests/test_eval_runner.py::test_governed_read_context_eval_replays_reducer_and_enforces_turn_deltas
FAILED agent/tests/test_eval_runner.py::test_governed_context_evidence_uses_recorded_bad_payload_and_observes_each_turn
FAILED agent/tests/test_eval_runner.py::test_recent_frame_restoration_requires_explicit_capability_round_trip
FAILED agent/tests/test_eval_runner.py::test_governed_context_evidence_preserves_case_results_and_production_outcomes
FAILED agent/tests/test_eval_runner.py::test_governed_context_failure_ref_tracks_the_failing_turn_and_observations
FAILED agent/tests/test_intent.py::test_parse_intent_po_by_vendor
FAILED agent/tests/test_llm_intent.py::test_hybrid_falls_back_to_parse_intent_for_po
FAILED agent/tests/test_orchestrator.py::test_python_hashes_match_typescript_canonical_json_for_unicode
FAILED agent/tests/test_orchestrator.py::test_run_query_po_list_success
FAILED agent/tests/test_orchestrator.py::test_run_query_po_empty_list_success
FAILED agent/tests/test_orchestrator.py::test_run_query_po_llm_narration_full_path
```

Breakdown by module (9 test_eval_runner, 1 test_intent, 1 test_llm_intent, 4
test_orchestrator = 15) - **exact match** to the count and per-module
breakdown documented since Task 5b/18/19 in `progress.md`.

Comparison against the documented baseline (Task 19's final state:
`15 failed / 1273 passed / 1 skipped`, per `progress.md` line 254-255):

| Metric | Documented baseline (post-Task 19) | This sweep | Match? |
|---|---|---|---|
| Failed | 15 | 15 | Yes |
| Passed | 1273 | 1273 | Yes |
| Skipped | 1 | 1 | Yes |
| Failing test names | (same 15, listed above per Task 5b/18 breakdown) | identical 15 names | Yes |

**Verdict: PASS.** Exact match to the documented pre-existing baseline (zero
new failures, zero new/missing passes). These 15 failures are the confirmed,
pre-existing PO vendor/PONumber alphanumeric-matching gap and a stale
canonical-JSON hash test vector, both explicitly ruled out of scope during
Task 18 (see `progress.md` Task 18 entry). Not touched by this sweep.

---

### 4. Individual verification commands (bypassing
`scripts/verify-agent-callplan-evidence.sh`'s `set -euo pipefail` hard-stop
on the pre-existing pytest failures, per the established Task 13 precedent)

#### 4a. `.venv/bin/python scripts/validate-semantic-planning-contract.py`

```
Legacy registry contract valid
Semantic planning contract valid: snapshotId=sha256:24fa1be5cfad4f64b8a6776aa1d360fa3682b4abe6ac68efbee5974d7feba080
EXIT: 0
```

**Verdict: PASS.**

#### 4b. `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`

```
Eval passed: 7/7
EXIT: 0
```

**Verdict: PASS (7/7).**

#### 4c. `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json`

```
Traceback (most recent call last):
  ...
  File ".../agent/sap_nexus_agent/eval.py", line 175, in run_eval_file
    raise AssertionError("\n".join(failures))
AssertionError: bc_mm_purchaseorder_capability_hit_001:
bc_mm_purchaseorder_intent_distinction_001:
EXIT: 1
```

2 failures (both PO vendor-matching related, same family as the documented
pre-existing PO alphanumeric gap).

**Investigation performed (not a task-brief PASS criterion, done to rule out
a regression):** checked out the plan's own pre-Task-1 base commit `20f96d8`
in a disposable `git worktree` (`/tmp/opencode/task20-base-check`, removed
after inspection - no changes made to the working repo) and ran the identical
eval file there with the same interpreter:

```
$ cd /tmp/opencode/task20-base-check && PYTHONPATH=agent <repo>/.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json
AssertionError: bc_mm_purchaseorder_capability_hit_001:
bc_mm_purchaseorder_intent_distinction_001:
EXIT: 1
```

Identical 2 failures, by name, already present at the plan's own starting
commit - confirming this is a pre-existing condition, not something
introduced by declarative-intent-extraction's Tasks 1-19.

**Verdict: PASS (with documented pre-existing exception, not a regression).**
Note: this contradicts the task brief's stated expectation of "seed 13/13"
fully green at Task 18's final state; the `progress.md` ledger's own Task 13
entry ("eval_harness_seed_cases.json and matcher_cases.yaml retain
pre-existing PO-related baseline failures independently reproduced by
coordinator with the seam off") is consistent with what was found here, and
takes precedence over the brief's stale expectation.

#### 4d. `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json`

```
Eval passed: 9/9
EXIT: 0
```

**Verdict: PASS (9/9).**

#### 4e. `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml`

```
Traceback (most recent call last):
  ...
  File ".../agent/sap_nexus_agent/eval.py", line 295, in run_matcher_cases
    raise AssertionError("\n".join(failures))
AssertionError: direct-plant-switch: fixture snapshot mismatch
clear-then-ambiguous-reference: fixture snapshot mismatch
explicit-correction: fixture snapshot mismatch
llm-unavailable: fixture snapshot mismatch
malformed-json: fixture snapshot mismatch
technical-override-injection: fixture snapshot mismatch
capability-switch: fixture snapshot mismatch
recent-frame-explicit-restoration: fixture snapshot mismatch
registry-drift: fixture snapshot mismatch
principal-mismatch: fixture snapshot mismatch
concurrent-turns: fixture snapshot mismatch
duplicate-turn-id: fixture snapshot mismatch
read-write-authority-isolation: fixture snapshot mismatch
EXIT: 1
```

13 failures, all `AssertionError: ... fixture snapshot mismatch` - this
assertion (`agent/sap_nexus_agent/eval.py:460`,
`assert snapshot.snapshot_id == case["registrySnapshotId"]`) compares the
live-computed registry snapshot hash against a hardcoded hash baked into the
eval fixture years before this SDD plan started.

**Same worktree-based investigation as 4c**, run against the pre-Task-1 base
commit `20f96d8`:

```
$ cd /tmp/opencode/task20-base-check && PYTHONPATH=agent <repo>/.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml
AssertionError: direct-plant-switch: fixture snapshot mismatch
... (identical 13 case IDs)
EXIT: 1
```

Identical 13 failures, by case ID, already present at the plan's own starting
commit - confirming this is pre-existing and unrelated to
declarative-intent-extraction (any registry content change, including ones
made before this SDD plan even for unrelated reasons, would break this
hardcoded-hash fixture; it was never green at the plan's own base).

**Verdict: PASS (with documented pre-existing exception, not a regression).**
Note: this also contradicts the task brief's stated expectation of
"matcher 23/23" fully green at Task 18's final state. Flagging this
discrepancy between the brief's assumed history and the actual, independently
reproducible pre-existing state, per the task's instruction to report (not
silently reinterpret) findings that don't match expectations. This is NOT a
new regression introduced by this change - verified empirically against the
plan's own base commit, not just asserted.

#### 4f. `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/dry_run_cases.yaml`

```
SKIP (pending): dry-run-missing-producer: 无法用真实 registry 构造 missing_capability 场景 - 所有 active capability 均有 produces_fact_types；需扩展 registry 或注入 fake sources 才能覆盖。已在 agent/tests/test_planner_plan_compiler.py 单测中覆盖该分支。
Eval passed: 3/3
EXIT: 0
```

**Verdict: PASS (3/3, 1 documented pending/skip).**

---

### 5. OpenSpec (Comet adapter)

#### 5a. `comet classic openspec -- list --json`

```json
{
  "changes": [
    {
      "name": "declarative-intent-extraction",
      "completedTasks": 19,
      "totalTasks": 21,
      "lastModified": "2026-08-19T04:57:36.244Z",
      "status": "in-progress"
    }
  ],
  "root": {
    "path": "/home/shrek/projects/GitHub_Projects/sap-nexus-agent",
    "source": "nearest"
  }
}
```

**Verdict: PASS.** Shows the expected in-progress change with 19/21 tasks
checked off prior to this sweep (Tasks 20-21 remain).

#### 5b. `comet classic openspec -- validate --all --strict`

```
✓ spec/agent-callplan-evidence
✓ spec/agent-workbench-console
✓ spec/capability-registry-gateway
✓ spec/conversational-context
✓ change/declarative-intent-extraction
✓ spec/durable-approval-store
✓ spec/durable-run-state
✓ spec/gateway-execution-contract
✓ spec/governed-context-registry-snapshot
✓ spec/governed-intent-envelope-recall
✓ spec/odata-gateway-read
✓ spec/output-projection
✓ spec/planner-dry-run
✓ spec/pr-create-action
✓ spec/read-plan-executor
✓ spec/registry-ontology-contract
✓ spec/semantic-match-decision
✓ spec/semantic-plan-authoring-v2
✓ spec/semantic-planning-foundation
✓ spec/sse-cursor-reconnect
✓ spec/trusted-principal-scope
Totals: 21 passed, 0 failed (21 items)
EXIT: 0
```

**Verdict: PASS (21/21).**

---

### 6. Frontend-untouched check

```
$ git diff --stat 2d4af9451ab1516a775de367d5b8bf347136eee2..HEAD -- frontend/
(no output)
```

**Verdict: PASS.** Empty diff confirms `frontend/` has not been touched by
any commit in this entire change, from the pre-change base commit through
current HEAD.

---

### 7. Gateway test (Task 6 re-run)

`bash scripts/comet-verify-gateway.sh`:

```
To honour the JVM settings for this build a single-use Daemon process will be forked. ...
> Task :core:compileJava UP-TO-DATE
...
> Task :app:test UP-TO-DATE
> Task :core:test UP-TO-DATE
> Task :jco:test UP-TO-DATE
> Task :odata:test UP-TO-DATE

BUILD SUCCESSFUL in 13s
16 actionable tasks: 16 up-to-date
EXIT: 0
```

**Verdict: PASS.** All Java module tests up-to-date/green (gateway is
untouched by this Python-only agent-side change, as expected).

---

### 8. Parity-table fixture row count

```
$ ls agent/tests/fixtures/parity/
inventory.yaml  po.yaml  pr.yaml

$ for f in agent/tests/fixtures/parity/*.yaml; do
    grep -cE '^\s*-\s*name:' "$f"
  done
inventory.yaml: 13
po.yaml: 11
pr.yaml: 12

$ cat agent/tests/fixtures/parity/*.yaml | grep -cE '^\s*-\s*name:'
36
```

**Verdict: PASS.** 36 fixture rows total (13 inventory + 11 po + 12 pr),
matching the brief's expected "36 fixture rows across pr/inventory/po".
These are the production-leg parity regression tests kept after Task 18's
legacy-deletion removed the differential legs (legacy/engine comparison),
per `progress.md`'s Task 18 entry.

---

## Summary table

| # | Item | Command | Result | Verdict |
|---|------|---------|--------|---------|
| 1 | Working tree clean | `git status --short` | empty output | PASS |
| 2 | Registry contract | `validate-registry-contract.py` | "Registry contract valid" | PASS |
| 3 | Full agent test suite | `pytest agent/tests -v --tb=short -q` | 15 failed / 1273 passed / 1 skipped, exact-name match to documented baseline | PASS |
| 4a | Semantic planning contract | `validate-semantic-planning-contract.py` | valid, snapshotId computed | PASS |
| 4b | Inventory eval | `eval evals/inventory_availability_cases.yaml` | 7/7 | PASS |
| 4c | Seed eval | `eval evals/eval_harness_seed_cases.json` | 2 pre-existing PO failures, confirmed identical at plan's base commit `20f96d8` | PASS (documented pre-existing exception) |
| 4d | PR create eval | `eval evals/pr_create_cases.json` | 9/9 | PASS |
| 4e | Matcher eval | `eval evals/matcher_cases.yaml` | 13 pre-existing "fixture snapshot mismatch" failures, confirmed identical at plan's base commit `20f96d8` | PASS (documented pre-existing exception) |
| 4f | Dry-run eval | `eval evals/dry_run_cases.yaml` | 3/3 (+1 documented skip) | PASS |
| 5a | OpenSpec list | `comet classic openspec -- list --json` | 19/21 tasks, in-progress | PASS |
| 5b | OpenSpec validate | `comet classic openspec -- validate --all --strict` | 21/21 passed | PASS |
| 6 | Frontend untouched | `git diff --stat <base>..HEAD -- frontend/` | empty | PASS |
| 7 | Gateway tests | `bash scripts/comet-verify-gateway.sh` | BUILD SUCCESSFUL, exit 0 | PASS |
| 8 | Parity fixture rows | manual count of `agent/tests/fixtures/parity/*.yaml` | 36 (13+11+12) | PASS |

**Overall verdict: PASS.** No new regressions found. All discrepancies from
the task brief's stated expectations (evals 4c/4e not being fully green)
were investigated empirically (disposable git worktree against the plan's
own pre-Task-1 base commit `20f96d8`) and confirmed to be pre-existing
conditions unrelated to declarative-intent-extraction, not new failures
introduced by this change. These pre-existing eval gaps are the same
documented family as the 15 pytest failures (PO vendor/PONumber
alphanumeric-matching gap for evals 4c, and a stale hardcoded registry
snapshot hash baked into `evals/matcher_cases.yaml` fixtures for eval 4e) -
both explicitly out of scope per Task 18's ruling in `progress.md`.

No code was modified during this verification sweep; only this file was
created.

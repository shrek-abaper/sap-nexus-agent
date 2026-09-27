# Outcome

A **paired evaluation gate** modeled on EvoOntology's gated versioning: the same
offline eval suites run twice — once against the **Parent** registry, once
against the **Candidate** registry — the six Eval SLIs from architecture §10.1
are computed per side, and the gate **fails on any negative SLI delta**. A
machine-readable paired report is written to `runtime/evals/results/`.

This closes the gap where a registry/prompt change can merge with every fixed
case passing while real capability-hit / parameter / clarification quality
silently regresses: pass/fail regression proves known assertions hold; the
paired gate proves quality did not move backward relative to the Parent.

# Scope

1. **`agent/sap_nexus_agent/eval.py` — `--metrics` mode.**
   Runs one eval file and prints JSON: per-case `{suite, caseId, decision,
   passed}` plus SLI counts `{<sli>: {passed, total}}`. Failures are recorded
   per case without aborting the run, so rates keep their denominators. The
   existing pass/fail invocation and `--context-evidence` mode are unchanged.
2. **`agent/sap_nexus_agent/paired_eval.py` — testable core.**
   - Materialize a registry version from a git ref into a temp root
     (`registry/capabilities.yaml`, `semantic-types.yaml`,
     `executor-bindings.yaml` via `git show <ref>:<path>`).
   - Spawn `python -m sap_nexus_agent.eval --metrics <suite>` for Parent
     (`SAP_NEXUS_AGENT_ROOT=<parent-root>`) and Candidate.
   - Aggregate SLI counts, compute rates and deltas, decide PASS/FAIL, build
     the paired report.
3. **`scripts/paired_eval_gate.py` — thin CLI wrapper.**
   `.venv/bin/python scripts/paired_eval_gate.py [--parent <git-ref>]
   [--candidate <git-ref>] [--output-dir <path>]`.
4. **Unit tests** for SLI classification/aggregation, delta gate, parent
   materialization, and the `--metrics` mode, under `agent/tests/`.

**Eval suites (the canonical evidence set):**

- `evals/inventory_availability_cases.yaml`
- `evals/eval_harness_seed_cases.json`
- `evals/pr_create_cases.json`
- `evals/matcher_cases.yaml`
- `evals/dry_run_cases.yaml`
- `evals/derived_parameter_cases.yaml`

# Non-goals

- No self-evolving runtime, no `browse_semantics`/`resolve_semantics` service,
  no automatic candidate publishing (architecture v1.2 keeps inference at
  compile time; ontology changes stay human-ratified).
- No live LLM calls. All suites are deterministic (rule intent + FakeGateway;
  governed-context cases use the `recorded_llm` cassette).
- No tolerance configuration or per-SLI thresholds: the rule is strictly
  "zero negative delta". No GitHub Actions / CI workflow changes.
- `narrativeGroundingRate` has no eval-runner-compatible fixture today
  (`evals/grounded_narrative_cases.json` uses a different schema); it is
  reported with denominator 0 and excluded from the delta comparison.
- No changes to existing eval assertions or existing case files.

# Acceptance examples

1. Clean working tree, `--parent HEAD` → gate **PASS**, every SLI delta is 0,
   report exists under `runtime/evals/results/`.
2. After a regression injection (e.g., delete a `triggerKeywords` entry from
   `registry/capabilities.yaml`) → gate **FAIL**, the printed summary and
   report identify `capabilityHitRate` with a negative delta and the affected
   cases; exit code is 1. Reverting restores PASS.
3. New unit tests pass; the existing eval invocation behaves exactly as
   before; full `agent/tests` suite stays green.

# Constraints and invariants

- Determinism: Parent and Candidate runs use identical code, suite files,
  FakeGateway fixtures, and (where used) recorded LLM responses. Only the
  registry version differs.
- Default sides: Parent = `HEAD`; Candidate = the working tree (so uncommitted
  registry edits are evaluated). Both sides may instead be git refs.
- SLIs with denominator 0 on either side are not compared; denominators
  differing between sides for any compared SLI is a FAIL.
- The report records side identity: git SHA (or `worktree`), per-registry-file
  sha256, and the suite-list hash. No secrets/tokens in any artifact.

# Decisions

- **D1 (2026-09-27):** SLI contribution is per-case, mapped from the expected
  decision: SELECT/success → `capabilityHitRate` + `parameterCompletionRate`
  (+ `businessCaliberAccuracy` when `expectedBusinessCaliber` is present);
  CLARIFY/clarification → `missingParameterClarificationRate`;
  REJECT/failure → `unsafeExecutionBlockRate`. A passed case contributes 1 to
  each mapped SLI. Rationale: existing fixtures already assert parameter
  values, expected params, and gateway call counts inside each case, so a
  parameter-level failure fails the case and correctly drops its mapped rates
  at the granularity the fixtures support.
- **D2 (2026-09-27):** Only the three `registry/*.yaml` files are
  version-varied; code, evals, and schemas are identical for both sides.

# Open questions

- Resolved 2026-09-27: shared understanding confirmed by the user's `/goal`
  directive (autonomous execution, no confirmation round-trip).

# Verification expectations

- `agent/tests`: new tests for metrics mode and paired-eval core; full agent
  pytest green.
- End-to-end: run the gate on a clean tree (PASS, zero deltas), then with an
  injected registry regression (FAIL with the right SLI named), then revert.
- `git status --short` before/after; only the scoped files change.

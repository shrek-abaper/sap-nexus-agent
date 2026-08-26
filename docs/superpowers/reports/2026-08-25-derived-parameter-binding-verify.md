# Verification Report: derived-parameter-binding

Verify phase, `verify_mode: full` (42 tasks · 7 delta-spec capabilities · 75 changed files, all
three thresholds exceeded). Second pass — the first pass failed and returned the change to build.

## Summary

| Dimension | Status |
|---|---|
| Completeness | 42/42 tasks checked; 5 descoped by user decision with destinations named |
| Correctness | 22 requirements / 75 scenarios audited; **45 COVERED · 22 PARTIAL · 8 UNCOVERED** |
| Coherence | Design followed, with **6 divergences recorded** in `design.md` § Implementation Divergence |

**Verdict: no CRITICAL or IMPORTANT issue remains open.** 10 findings were repaired in a build
round; 8 UNCOVERED scenarios are all accounted for (6 by the approved descope, 2 by an approved
design divergence).

## Fresh evidence

Every command below was run in the verify phase after the repair round. Nothing is carried over from
an earlier run, and nothing was piped through `tail`/`head` in a way that hides a failure.

| Command | Result |
|---|---|
| `validate-registry-contract.py registry/capabilities.yaml` | `Registry contract valid`; 15 `extraction` deprecation warnings, count unchanged |
| `pytest agent/tests/test_registry_contract.py -q` | **16 passed** |
| `pytest agent/tests -q` | **1547 passed, 1 skipped, 2 xfailed** (1500 at batch start) |
| `PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh` | exit **0** — 7/7 · 13/13 · 9/9 · 23/23 · 3/3 (+1 unresolved) · 3/3 (+2 unresolved) · openspec 22/22 |
| `npm --prefix frontend run verify` | **52 files, 525 tests passed** |
| `npm --prefix frontend run release-gate -- --profile all` | exit 0 — `L3_ACTION_GOVERNED · passed=true · cases=22/22` |
| `./gradlew build --offline` (whole Gateway) | **BUILD SUCCESSFUL** — added because this change modified Java, which the plan's six commands do not cover |

The 1 skipped is `test_llm_live.py`, env-gated. The 2 xfailed are the pre-existing `capabilityOutput`
placeholders (strict xfail, deliberately unwired).

The unresolved counts are **new in this change** and are the point of repair R2: pending eval cases
are now *counted*, not merely excluded from the pass count.

## Findings from the first verify pass, and their disposition

Coverage was audited scenario by scenario across all 7 delta-spec capabilities. Ten findings were
objectively repairable in scope, so per the Comet Step 1b rule they were fixed without asking
(`verify_failures: 1`, below the automatic limit).

| # | Finding | Class | Disposition |
|---|---|---|---|
| R1 | **Derivability did not mirror auto-pullability.** The derived view filters producers on `status: active` alone; the closure additionally requires a READ producer. An input whose only producer is an Action was reported derivable → dropped from `missing_parameters` → never asked; the closure then refused to pull it → never bound. **Neither asked nor bound.** A defect introduced by task 7.1 | IMPORTANT, correctness | Fixed — `is_auto_pullable_governance` extracted as one rule, imported by both callers. M38/M39 caught |
| R2 | Pending eval cases were not **counted** as unresolved, so the suite printed `3/3` and two unresolved cases were stderr-only | IMPORTANT, spec clause | Fixed — `EvalSummary.unresolved` + a CLI line. M42 caught |
| R3 | `UNKNOWN_FACT_TYPE` did not **name the capability and input** as the spec requires | spec clause | Fixed |
| R4 | "A READ capability's binding cannot commit or roll back" was enforced **only for `REST_JSON`** — no check for `JCO_RFC`/`ODATA`. The brief's own red line, half unchecked | governance | Fixed — `_validate_read_only_binding` for all binding types, two independent conditions. M40/M41 caught |
| R5 | The loader check hardcoded `4` where the spec requires asserting against registry content | spec clause | Fixed. M43 caught |
| R6 | `RESERVED_SOURCE_NOT_AUTHORED` had zero test coverage | coverage | Fixed via the public validator |
| R7 | No declaration-only lock for the **real** 4th capability (only for a fixture one), so invariant 6 rested on a one-off diff | invariant 6 | Fixed — lock over production Python, Java and TypeScript. M44/M45 caught |
| R8 | "however similar the names" was asserted with an *unrelated* type | coverage | Fixed — 7 lookalikes. M47 caught 3, correctly leaving 4 green |
| R9 | `needsReduction`/`ambiguous` never reached dry-run `gaps` | spec clause | Fixed. M49 caught |
| R10 | **The compiler bound what the deriver refused.** `plan_compiler_v2` referenced `cardinality` zero times, so a `cardinality: many` field was bound to a scalar input the deriver had diagnosed — violating the spec's "the input is not bound to any parameter source". Found by R9's own test | IMPORTANT, correctness | Fixed — the compiler defers to the deriver. M48/M50 caught |

Two vacuities in my own new tests were found by mutation and fixed rather than shipped: R7's positive
control substring-matched YAML, and `MM.Material.GetInfo` is a *prefix* of the mutated
`MM.Material.GetInfoXX`, so it passed the very mutation it existed to catch (now parsed); and R6's
first attempt used a guessed source shape that failed as `SCHEMA_INVALID` without ever reaching the
rule under test.

R10 also required rewriting a task-5.6 acceptance test that asserted the forbidden binding. It moved
onto `sapnexus:MaterialInfoFact`, which publishes four scalar fields with distinct semantic types —
strictly better coverage, confirmed by M50 still failing both 5.6 tests.

## The 8 UNCOVERED scenarios, each accounted for

| Scenario | Account |
|---|---|
| `semantic-plan-authoring-v2` — an automatically added read is disclosed | Descoped (5.4a) → `derived-parameter-runtime-disclosure` |
| `output-projection` — derived parameter provenance survives projection | Descoped (5.9); findings G1 + G4 |
| `agent-callplan-evidence` — upstream failure degrades to elicitation | Descoped (7.4); execution-time, invariant 2 |
| `declarative-intent-extraction` — empty upstream value falls back to asking | Descoped (7.4); same chain |
| `planner-dry-run` — unproducible requirement yields a capability gap | Descoped (7.6); structurally unreachable |
| `planner-dry-run` — missing-producer case executes rather than skips | Descoped (7.6); same |
| `declarative-intent-extraction` — conflict between values is recorded | **Design divergence, Option A** — `design.md` § 6 |
| `declarative-intent-extraction` — matching values record no conflict | Same |

None is reported as a known issue, a pre-existing failure, or unrelated to core functionality.

## Coherence: 6 recorded divergences

`design.md` § Implementation Divergence records each with its authorising decision: (1) the unmet
Goal of provenance reaching the narrative and approval surface; (2) `asOf`/`snapshotId` not declared
as Fact Type fields (C14); (3) three mechanisms the design did not anticipate (C13's generic
resolver, 5.4b's key propagation, G5's blank-field guard); (4) a derivable parameter escalating to
the planner; (5) `proposal.md`'s stale T0′ bullet against Decision 12; (6) conflict recording.

## Deviations accepted, and what remains open

Accepted with reason and impact scope recorded, per the user decisions taken during this phase:

- **The descope of 5.4a / 5.9 / 7.1 / 7.4 / 7.6** — destinations named in `tasks.md`, original task
  text retained verbatim. Impact: runtime disclosure of a derived value does not reach the UI in this
  change. Current behaviour is **fail-closed, not under-disclosed** — no action proposal is created,
  so the failure mode is an unapproved WRITE rather than an under-disclosed one.
- **Conflict recording designed away** (Option A). Impact: two delta-spec scenarios are permanently
  unsatisfiable by design; the precedence half is asserted by three separate tests.

Open items carried forward, none of them blocking and none of them a defect in this change:
**G3** (the callplan-evidence script makes live LLM calls and is intermittently red — pre-existing,
not reproducible on demand, remedy is deterministic eval narration), **G4/U2** (the projection layer
needs its own change; scoped in the plan), **U7** (the 3-segment table-row path stays hardcoded),
**U8** (`selectExecutor`'s `findFirst`), **U9** (mutation M23 — no pre-existing test discriminates
the topological sort), **U11** (15 `extraction` deprecation warnings, pinned so they cannot grow).

## Final assessment

**No critical issues. Ready for archive**, with the two accepted deviations above and the open items
carried forward. Batch L has not begun and no file in its scope was touched.

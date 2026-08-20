# Subagent-driven development — coordinator checkpoint

Change: `declarative-intent-hardening`
Workflow: Classic, phase `build`
build_mode: `subagent-driven-development` | tdd_mode: `tdd` | review_mode: `standard` | isolation: `current` (branch `main`)
Plan: `docs/superpowers/plans/2026-08-19-declarative-intent-hardening.md`
Ledger: `.superpowers/sdd/2026-08-19-declarative-intent-hardening/progress.md`

## Stage

**ALL 16 PLAN TASKS COMPLETE. Final lightweight review (`review_mode: standard`, exactly one allowed) dispatched, in flight.**

`tasks.md`: 16/16 `- [x]`, zero unchecked. Verified with `grep -c '^- \[x\]'` → 16 and `grep -n '^- \[ \]'` → no matches.

## BASE

- change base_ref: `c2828842`
- HEAD: `e1a7a6e` (`chore(declarative-intent): check off task 4.2 in plan + tasks.md — all 16 plan tasks complete`)
- series length: 40 commits from base

## Task 4.1 — CLOSED

- Verification-only, no source commit. Checkoff commit `6aff915`.
- Six gates green: registry CLI exit 0 (`regex matchers in use: 17`, 15 deprecation warnings == 15 `extraction:` blocks); full agent suite 1343 passed / 1 skipped / 2 xfailed / 0 failed; matcher_cases 23/23 by direct `run_eval_file(Path(...))`; `openspec validate --all --strict` 22 passed / 0 failed; `npm --prefix frontend run verify` green (51 files, 524 tests, `next build` ✓, exit 0) — first frontend run in this change; secrets scan clean.
- Commit series audited: 37 commits at that point, all attributable, no rider work.
- Honest caveat carried forward: 23/23 was verified by RUNNING, not pinned (`test_eval_runner.py` asserts only `total >= 5`).
- New deferred finding recorded (FINDING 4): both validator spellings modified together, nothing asserts they agree.

## Task 4.2 — CLOSED (audit-only; artifact `3caab7a`, checkoff `e1a7a6e`)

Verdict DONE_WITH_CONCERNS. Produced tracked `openspec/changes/declarative-intent-hardening/verification.md` (+414) per the coordinator pre-ruling that made plan Step 3 unconditional. `openspec validate --all --strict` re-run after the file existed: 22 passed / 0 failed, unchanged.

**The plan's "1:1" premise is DISPROVED**: 17 table rows vs 21 actual spec scenarios — GENUINE 8, WEAK 7, FALSE 2, UNMAPPED 4, MISSING 0. Plan Step 1 checkbox annotated in place so the artifact does not claim a correct table.

Coordinator independently re-verified rather than trusting the mapping table: row 10 FALSE (one `MatcherConfig`, zero capabilities, `test_named_kind_matching.py:80` — and the registry's disjoint `semanticType` ref sets mean no eval case can supply it either), row 11 FALSE (every `resolve_input_binding` call passes `set()` for `excluded_values`; the real pin is `test_extraction_engine.py:78`), row 13 WEAK (`require_justification=True` at exactly one call site, `validate_registry_contract.py:131`; capability sites default `False` at `:292`).

Commit series: 38 commits at audit time, strictly B1.1→…→B3.4→4.1, no interleaving, no rider work.

### Two adjudications that changed the record

- **RETRACTION of my own ledger FINDING 3.** "Design §3.7" DOES exist — `docs/superpowers/specs/2026-08-19-declarative-intent-hardening-design.md:172` = `### 3.7 Testing matrix`, and plan line 19 names that file as the design of record. I had checked the condensed sibling `openspec/changes/.../design.md` (unnumbered Decisions 1-6) and wrongly called the citation dangling. Every `§3.x` citation in tracked files resolves. Nothing to fix.
- **DOWNGRADE of the 4.2 agent's finding 2.** It claimed zero `valueShape` refs; false — `valueShape: plantCode` is referenced at `registry/semantic-types.yaml:9` and `:12`. The agent conflated matcher-level `valueShape` with input-level JSON Schema `pattern`. Not a defect.

### Confirmed real, deferred

`MM.PR.CreateDraft.plant` accepts AB12 via `pattern: '^[A-Z0-9]{4}$'` but its inline matcher `工厂\s*(\d{4}|[A-Z]\d{3})` cannot extract it (verified `re.search` → None). Design §3.2's consistency claim holds only for catalog-extracted inputs; §3.4 never mandated the matcher rewrite, so this is a residual gap, not a skipped step. Blast radius is fail-safe (unextracted → clarify, never a wrong value) and the Java fail-closed line still rejects blank required params — no §2 breach.

## Review round

Final lightweight review dispatched (the one allowed under `review_mode: standard`). Scoped to: §2 hard-boundary compliance first (especially whether `elicitIfMissing: false` opens a path for a blank required param to reach SAP), then correctness bugs no existing test would catch, then archive-safety. Explicitly told NOT to re-report the ~30 already-deferred findings, and required to substantiate or label SPECULATIVE.

## Next after the review

1. Coordinator triages the report: only a §2 hard-boundary breach or a real correctness bug blocks; everything else joins the deferred list.
2. Return to `/comet-build` for exit checks + `comet guard declarative-intent-hardening build --apply`.
   Do NOT load `finishing-a-development-branch`.
3. Closeout must surface to the user the deferred items that carry real risk — above all the migration-parity trap (explicit `binding:` silently drops six keys, so no capability can migrate off the alias safely yet).

## Current stage: out-of-plan gate fix (build phase)

All 16 plan tasks are checked; the final review and its single fix round are accepted. The only thing standing between build and verify is the guard's "Build passes" check, recorded honestly as `exit=1`.

Root cause found and measured: `scenario-runner.test.ts`'s "offline" gate makes ~9 live LLM HTTP calls per eval spawn (~40s of its ~83.5s, against a 90_000ms budget). Pre-existing — `narrator.py`, `llm_client.py` and `eval.py` are all unchanged base..HEAD.

User re-ruled with the corrected diagnosis: apply the fix now, in build. A fresh implementer is running with TDD RED/GREEN required and a strict scope (one `env` option on the `runProcess` spawn; the 90_000 budget is NOT to be touched).

### Acceptance gate for this fix — nothing is checked off or committed until all of these hold

1. Diff is exactly the `runProcess` env option; no python/registry/other-test files touched.
2. RED evidence is real, or the implementer has explicitly justified why no honest unit pin was warranted. A tautological or timing-based pin is rejected.
3. `npm --prefix frontend run verify` reports a REAL exit 0, with the offline test's actual duration.
4. Only then: `comet state record-check declarative-intent-hardening build --command "npm --prefix frontend run verify" --exit-code 0`, then re-run the guard.

If the implementer's GREEN run fails, the fix does NOT go in by force — return to the user with the real output.

# SDD Progress Ledger - sap-nexus-incremental-sse-reconnect (项4)

Plan: docs/superpowers/plans/2026-08-02-incremental-sse-reconnect.md
Design: docs/superpowers/specs/2026-08-02-incremental-sse-reconnect-design.md
Branch: feature/20260802/sap-nexus-incremental-sse-reconnect
BASE: e21262c
Build config: isolation=branch, build_mode=subagent-driven-development, tdd_mode=tdd, review_mode=standard
build_command: npm --prefix frontend run build
verify_command: npm --prefix frontend run verify

## Pre-Flight Findings
- **principal 鉴权基线漂移**：plan 测试代码写于项2（trusted principal）之前，假设 `createAgentRun({query,conversationId})` / `getAgentRunEvents(runId)` / `decideAgentRunApproval(runId,"reject")` / `confirmAgentRunBatch(runId)` / `getSession(conversationId)` 无 principal 参数。当前代码（项2 已合并）要求 principal（CLAUDE.md §2 安全硬边界）。
  - **Resolution（唯一，非设计变更）**：保留 principal 鉴权，plan 测试代码适配加 `principal: PLACEHOLDER_PRINCIPAL`（从 `./principal/types` 导入，test 文件 line 18 已导入）。`getAgentRunEvents(runId)` -> `getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)`。`executeRunnerInBackground`（Task 2）签名加 `principalId: string`，调 `getSession(conversationId, principalId)`。stream route（Task 4）保留 `injectPrincipal(request)`（默认返回 PLACEHOLDER_PRINCIPAL），poll 闭包用 `getAgentRunEvents(runId, principal)`。
- `buildRuntimeFailureEventsTail`（line 693）/`buildRuntimeFailureEvents`（line 699）均存在 ✅。`runStore.markExecuted`/`appendPendingOutcome`/`claim`/`release`/`load` 均存在 ✅。helpers `objectOrNull`/`textValue`/`toJsonValue`/`redactArtifact` 均存在 ✅。

## Tasks
- [x] Task 1: Emitter 转换 + rejection terminal 修复 (adapter.ts + adapter.test.ts)
- [x] Task 2: createAgentRun 后台执行 (adapter.ts + adapter.test.ts)
- [x] Task 3: Continuation 路径后台执行 (adapter.ts + adapter.test.ts)
- [x] Task 4: Stream route cursor + 轮询 + terminal 收敛 + 背压 (stream/route.ts + stream-route.test.ts)
- [x] Task 5: 客户端 reconnect (stream-helpers.ts + .test.ts + AgentConsole.tsx)
- [x] Task 6: 回归验证 + openspec validate

## Completed
- Task 1: complete (commits e21262c..94e0980, review clean: Spec ✅ + Quality Approved, 0 Critical/Important, 1 Minor deferred - test doesn't assert stage/ordering but matches brief's own test code). 5 functions -> emitter versions, §4.4 rejection run_failed fix, 16/16 tests + tsc clean. Minor: t-1-review.md.
- Task 2: complete (commits 5a369cb..71625d8, review clean: Spec ✅ + Quality Approved, 0 C/I, 3 Minor deferred). executeRunnerInBackground (principalId added) + createAgentRun immediate return + delete buildRuntimeFailureEvents + 8 test adaptations. 17/17 tests + verify clean. Minor: t-2-review.md (waitForRunSettled rejected-state unreachable; catch-release load-throws pre-existing; double-release fixed to single).
- Task 3: complete (commits 89c47fe..b42859a, review: Spec ✅ + Quality Approved, 0 Critical, 1 Important I1 non-blocker deferred, 2 Minor deferred). executeApprovalInBackground + executeBatchInBackground (fire-and-forget) + decide/confirm try-block replaced + waitForRunSettled minEventCount backward-compatible + 4 tests hardened. 18/18 × 5 no flaky + tsc + build clean. **I1 (Important, non-blocker, plan trade-off):** fire-and-forget moves markExecuted to background; concurrent duplicate (before markExecuted) throws "already decided" not no-op. Bounded-safe (decision guard precedes claim, no double SAP exec). Reviewer recommends doc/characterization test -> defer to final review. Minor: t-3-review.md (M1 terminal lease not released - brief verbatim design, lease TTL safe; M2 appendPendingOutcome not called for re-awaiting continuation - pre-existing).

## Final Whole-Branch Review
- Status: COMPLETE (opus). Verdict: **Ready-to-merge**, 0 must-fix.
- Architecture sound (emitter -> fire-and-forget -> stream polling -> client reconnect). Security boundaries preserved (Human Approval, principal auth, SSE injectPrincipal). 88/88 + tsc + build + openspec 15/15 re-verified.
- All 12 cumulative Minor/deferred findings triage accept-as-is/nice-to-have. Task 3 I1 (concurrent duplicate "already decided") accepted as bounded-safe fire-and-forget trade-off.
- 3 new nice-to-have (none blocking): stream catch-block close() defensive try-catch; 404 reconnect max-retry; full-file replay per poll performance.
- final-review.md

## Minor findings (deferred to final review)
- Task 3 I1 (Important, non-blocker, plan fire-and-forget trade-off): concurrent duplicate decide/confirm throws "already decided" not no-op. Bounded-safe. Reviewer recommends doc/characterization test. t-3-review.md
- Task 3 M1 (Minor, brief verbatim design): terminal outcomes lease not released (only re-awaiting). Lease TTL safe.
- Task 3 M2 (Minor, pre-existing): appendPendingOutcome not called for re-awaiting continuation in decide/confirm.
- Task 4: complete (commits 5e6dcdb..08b0379, review: Spec ✅ + Quality Approved, 0 C/I, 3 Minor deferred). route.ts ReadableStream polling (cursor/terminal/backpressure/404/400) + stream-route.test.ts 5 tests. **Backpressure load-bearing fix**: brief's verbatim closed on isTerminal even if backpressure broke loop before terminal enqueued; added `backpressured` flag (close only when !backpressured && isTerminal). principal preserved (injectPrincipal). success->clarification test adaptation. 5/5 stream-route + 84/84 full suite + tsc + build clean. Minor: t-4-review.md (M1 cancel race after await; M2 unused test imports; M3 Number() accepts empty/hex cursors - all inherited from brief).
- Task 5: complete (commits 466a7c2..fc23491, review: Spec ✅ + Quality Approved, 0 C/I, 2 Minor deferred). stream-helpers.ts (buildStreamUrl/lastEventSequence/RECONNECT_DELAY=500) + test 4/4 + AgentConsole streamAgentRun reconnect (cursor + lastSequence + onerror ?cursor=N + intentionallyClosed) + decideApproval cursor. 88/88 full + typecheck clean. reconnect-safety all pass (no storm, no leak, dedup correct). Minor: t-5-review.md (M1 no backoff per-spec YAGNI; M2 lastSequence overwrite not Math.max - verbatim per-spec, SSE monotonic).

---

# SDD Progress Ledger - sap-nexus-output-projection-registry (Runbook 17)

Plan: docs/superpowers/plans/2026-08-04-sap-nexus-output-projection-registry.md
Design: docs/superpowers/specs/2026-08-04-sap-nexus-output-projection-registry-design.md
Branch: feature/20260804/sap-nexus-output-projection-registry
BASE: efcbe61
Build config: isolation=branch, build_mode=subagent-driven-development, tdd_mode=tdd, review_mode=thorough

## Pre-Flight Findings

- No plan conflicts found. Task 3 replay ordering was clarified before execution: an already-SUCCEEDED ledger entry may rebuild projection data from a complete cache record, then must return without attempting `SUCCEEDED -> READY`.
- Checkoff precondition repaired after Task 1: repeated generic `Commit`/failure step labels were made task-specific; all plan checkbox texts are unique and Comet targeted checkoff passes.

## Tasks

- [x] Task 1: 冻结 projection 类型契约
- [x] Task 2: 实现版本化 OutputProjectionRegistry
- [x] Task 3: 扩展 PlanExecutor 保留并恢复成功节点数据
- [x] Task 4: 实现 FactBuilderRegistry 与 ProjectionInputAssembler
- [x] Task 5: 实现确定性 hash 与 MaterialSupplySnapshot projection
- [x] Task 6: 完成端到端 Projection Eval 与隔离证明
- [x] Task 7: 全量相关验证与 OpenSpec 任务收口
- [x] Task 8: 修复 final whole-branch review findings

## Completed

- Task 1: complete (commits efcbe61..aea5172, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Projection type contracts + 1/1 focused test + typecheck clean.
- Task 2: complete (commits 3d2662b..127d115, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Exact version registry + structured fail-closed + duplicate rejection, 4/4 tests clean.
- Task 3: complete (commits dc10caa..291f2c2, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Fresh/cache/restart projection data retention, 27/27 executor tests + typecheck clean.
- Task 4: complete (commits 010a450..b8147fd, final review: Spec compliant + Quality Approved, 0 Critical/Important, 1 Minor deferred). Fact builders + assembler + nullable trace degradation + strict freshness/calendar validation + PO item identity; focused 24/24, frontend 221/221, typecheck/build, diff check, OpenSpec strict 20/20.
- Task 5: complete (commits e48926e..bb49278, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Deterministic hash + MaterialSupplySnapshot completeness/freshness/lineage/conflict policy; focused 15/15, frontend 232/232, typecheck/build, diff check, OpenSpec strict 20/20.
- Task 6: complete (commits 54b3d27..4ef7764, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Real executor-to-projection component Eval, six-case bad-path matrix, and compile-time raw/model-input isolation; regression 152/152, typecheck and diff check clean.
- Task 7: complete (verification-only at 7eb7267, review: Spec compliant + Quality Approved, 0 Critical/Important, 2 documentation Minor resolved in coordinator checkoff). Frontend verify 28/28 files and 240/240 tests plus typecheck/build; Classic OpenSpec strict 20/20; evidence audit 40/40; committed-range boundary clean.
- Task 8: complete (commit 2ff280f, fresh re-review: 7/7 original findings resolved, 0 unresolved Important/Minor, 0 new Critical/Important/Minor). Six RED/GREEN cycles; focused 72/72; frontend verify 28/28 files and 251/251 tests plus typecheck/build; Classic OpenSpec strict 20/20.

## Final Whole-Branch Review

- Initial review: `0 Critical / 5 Important / 2 Minor`; report `.superpowers/sdd/final-review.md`.
- Fix round 1: all seven findings addressed in `2ff280f`, including the carried Task 4 argument-limit Minor.
- Fresh re-review: ready for Verify; `7/7` resolved, no unresolved or new findings; report `.superpowers/sdd/final-rereview-1.md`.

---

# SDD Progress Ledger - sap-nexus-governed-read-context

Plan: docs/superpowers/plans/2026-08-06-governed-read-context.md
Design: docs/superpowers/specs/2026-08-06-governed-read-context-design.md
Native change: docs/comet/changes/sap-nexus-governed-read-context
Branch: main
BASE: 304d647
Build config: isolation=current-branch-per-project-rule, build_mode=subagent-driven-development, tdd_mode=tdd, review_mode=standard

## Pre-Flight Findings

- Task-scoped local commits explicitly authorized on 2026-08-06; no push, amend, branch switch, or unrelated staging authorized.
- Python baseline before Task 1: `959 passed, 1 skipped`.
- No remaining plan conflicts after adding the two-phase `resolve_read_turn -> CAS -> continue_resolved_read` protocol and limiting Registry plant patterns to READ capabilities.
- User ruling on 2026-08-07 (Task 9 Step 4 scope): Task 9's "remove the legacy
  bridge" is narrowed to Option A only — restrict `READ_CONTEXT_MODE` to drop
  the recognized `"legacy"` value and add the Step 2 contract test against the
  governed `resolve_read_turn`/`continue_resolved_read` path (already
  structurally clean of `last_context`). `agent/sap_nexus_agent/intent.py`'s
  `resolve_with_context` auto-dispatch, the `--context` CLI sticky
  CLARIFY->SELECT continuation feature (`cli.py`, documented in
  `docs/runbooks/README.md` and
  `docs/runbooks/12-conversational-context-and-multi-value-batch.md`), and
  `agent/tests/test_conversation_context.py` are explicitly OUT of scope for
  this change and MUST NOT be modified or deleted.

## Tasks

- [x] Task 1: Versioned Python READ context contracts and legacy migration
- [x] Task 2: Deterministic candidate extraction and semantic validation
- [x] Task 3: Pure ContextReducer and exact failure sequence
- [x] Task 4: Fail-closed decision gate and shadow orchestration
- [x] Task 5: Registry and Gateway semantic pattern validation
- [x] Task 6: Durable Session v2, lease, CAS, and turn idempotency
- [x] Task 7: Authoritative Frame v2 and unified pending interactions
- [x] Task 8: Multi-turn Eval fixtures and release hard gates
- [x] Task 9: Legacy bridge removal, full verification, and Native archive

## Completed

- Task 1: complete (commits `304d647..4dbefdb`, review clean after one fix round: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Added immutable READ context contracts, optional ConversationContext v2 compatibility, and strict fail-closed legacy migration. RED collection failure; focused `19 passed`; full Agent `973 passed, 1 skipped`.
- Task 2: complete (commits `4dbefdb..ae1f45d`, review clean after one fix round: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Added READ-only advisory catalog, immutable candidate extraction, generic Registry-metadata labels, semantic exclusion, and centralized auditable governance discards. Focused `93 passed`; Agent `991 passed, 1 skipped`.
- Task 3: complete (commits `ae1f45d..5fb4570`, review clean after four fix
  rounds: Spec compliant + Quality Approved, 0 Critical/Important, 1 Minor
  deferred). Added pure deterministic ContextReducer, immutable recent-frame
  history, executable multi-turn fixtures, semantic trust-boundary validation,
  explicit/pending/deterministic evidence arbitration, safe snapshot rebind, and
  cross-descriptor invariants. Focused `21 passed`; Agent `1016 passed, 1 skipped`.
- Task 4: complete (commits `5fb4570..c6e2467`, review clean after five fix
  rounds: Spec compliant + Quality Approved, 0 Critical/Important). Added the
  fail-closed Frame-to-decision gate, trusted combined authority service,
  observational shadow mode, typed redacted evidence, semantic contract and
  duplicate-ID validation, and distinct bounded-ambiguity/multi-goal routing.
  Focused `150 passed`; Agent `1078 passed, 1 skipped`; Eval and OpenSpec clean.
- Task 5: complete (commits `c6e2467..86e9833`, review clean: Spec compliant +
  Quality Approved, 0 Critical/Important, 1 Minor deferred). Added optional
  Registry input patterns, load-time regex validation, and full-string Gateway
  validation for READ Plant values only. Gateway core/app and OpenSpec strict pass.
- Task 6: complete (commits `86e9833..8b37579`, review clean after two fix
  rounds: Spec compliant + Quality Approved, 0 Critical/Important, 1 Minor
  deferred). Added Session v2 mirrors, strict legacy migration, fenced renewable
  conversation leases, exact CAS, recoverable turn-ledger journal, and durable
  duplicate-turn handling. Focused `64/64`; typecheck/build pass; one unrelated
  full-verify failure was independently reproduced at the task base.
- Task 7: complete (commits `8b37579..4c920f2`, review clean after four fix
  rounds: Spec compliant + Quality Approved with Minor Findings, 0
  Critical/Important, 2 Minors deferred). Made Frame v2 authoritative for READ,
  enforced resolve/CAS/continue ordering, unified bound pending interactions,
  added current-authority continuation and batch preflight, and preserved
  non-READ/Human Approval routing. Agent `1130 passed, 1 skipped`; Eval and
  OpenSpec clean; frontend serial verify had only the independently known
  composition baseline failure.
- Task 8: complete (commits `4c920f2..32f8b63`, review clean after four fix
  rounds: Spec compliant + Quality Approved, 0 Critical/Important/Minor open).
  Added 13 versioned governed-read multi-turn fixtures replayed through
  production `resolve_read_turn`/`continue_resolved_read` and the real
  hybrid-fallback/technical-override paths, exact slot-set assertions, and
  non-compensable release-gate metrics/hard gates. Closed a self-referential
  "applicable" no-op in three zero-rate gates and then an incomplete per-case
  backstop, landing on an aggregate exact-total check (9/10/20 across all 13
  context cases) that fails if any single case's evidence silently drops.
  Python focused `24/24`; frontend release-gate suite `25/25`; typecheck/build
  clean; `release-gate --profile all` `L3_ACTION_GOVERNED`, `22/22`,
  `liveSmoke=not_run`.
- Task 9: complete (commit `cf63a7e`, review clean after one fix round: Spec
  compliant + Quality Approved, 0 Critical/Important/Minor open). Per the
  user-confirmed Option A ruling, narrowed the legacy-bridge removal to
  `_read_context_mode()` dropping the recognized `"legacy"` value only;
  `intent.py`'s `resolve_with_context` auto-dispatch, the CLI `--context`
  flag, and `test_conversation_context.py` are explicitly retained,
  out-of-scope, non-governed legacy behavior (documented in design-doc §20 and
  the verify report). Added a governed-path contract test with a reachability
  sanity check plus a direct `last_context is None` invariant assertion across
  a full 3-turn continuation. Agent `1137 passed, 1 skipped`; callplan
  evidence, Gradle `:core:test :app:test`, and OpenSpec `20/20` all pass;
  frontend typecheck clean (one pre-existing, independently-reproduced
  `adapter-integration.test.ts` failure on unmodified `main`, unrelated to
  this change); `release-gate --profile all` `L3_ACTION_GOVERNED`, `22/22`,
  `liveSmoke=not_run`.

## Minor Findings

- Task 3 fix round 1: `agent/tests/test_context_reducer.py` uses a tautological
  tuple-length assertion for the cross-descriptor pending invariant; defer to the
  final whole-branch review after the load-bearing confirmation finding is fixed.
- Task 4 final internal audit: whole-branch issuer/nested-DTO defensive tests may
  be broadened, but final task review found no actual authority or output leak.
- Task 5: report notes existing Gradle deprecation/JVM-sharing warnings without
  preserving their exact text/source; defer evidence-hygiene triage to final review.
- Task 6 initial review: protocol ordering test should assert both CAS operations
  and `runner < result CAS < event`; defer this non-load-bearing test hardening to
  final whole-branch review.
- Task 7 final review: add a positive live-batch test where `preflight-batch`
  succeeds and matching current authority, rather than exercising only the
  fail-closed preflight-error branch.
- Task 7 final review: add direct production child close-event coverage after a
  conversation heartbeat abort; current tests prove signal propagation and the
  production runner calls `child.kill()` but do not await a real child close.

## Fix Rounds

- Task 3: fix round 1/5 (4 addressed, 1 open - standalone `CONFIRMATION` is
  emitted as `EXPLICIT_CORRECTION` / `EXPLICIT`; commit `7ec369d`).
- Task 3: fix round 2/5 (1 addressed, 1 new open - mixed correction and
  confirmation values in the same top evidence tier are not conflicted; commit
  `d7430d7`).
- Task 3: fix round 3/5 (1 addressed, 1 new open - explicit-tier conflict is
  mislabeled as deterministic syntax in issues/evidence; commit `7b9f6ca`).
- Task 3: fix round 4/5 (1 addressed, 0 open - explicit and deterministic
  conflicts now retain truthful tier-specific issues/evidence; commit `5fb4570`).
- Task 4: fix round 1/5 (2 addressed, 4 open - shadow orchestration upgrades
  dry-run visibility and conflates bounded ambiguity with multi-goal routing;
  commit `b83b68c`).
- Task 4: fix round 2/5 (2 addressed, 2 open - positive shadow paths still
  rely on test-only execution visibility, and multi-goal escalation still
  requires two unique capability hints; commit `8fea3ae`).
- Task 4: fix round 3/5 (3 addressed, 2 new open - execution visibility is
  passed as an unbound raw ID set, and duplicate Registry/binding IDs are
  resolved last-wins; commit `8a0986b`).
- Task 4: fix round 4/5 (1 addressed, 2 open - projection proof can be bypassed
  by `None`, and the cross-module issuer signs caller-supplied authority inputs;
  commit `69cc4d5`).
- Task 4: fix round 5/5 (4 addressed, 0 open - mandatory combined authority,
  semantic-contract validation, and zero-side-effect shadow approved; commit
  `c6e2467`).
- Task 6: fix round 1/5 (1 addressed, 2 open - cross-file turn-ledger failure
  can become replayable after an intervening turn, and known lease loss can
  still reach composition Gateway; commit `c8e335a`).
- Task 6: fix round 2/5 (2 addressed, 0 open - recoverable journal closes
  Session/ledger crash windows and post-run fencing blocks composition/Gateway;
  commit `8b37579`).
- Task 7: fix round 1/5 (0 fully addressed, 5 original findings remain plus
  in-scope continuation/pending regressions; commit `aac2950`). User ruling on
  2026-08-07: cross-process Node lease/CAS atomicity remains outside the confirmed
  local/single-worker JSON baseline; do not claim multi-worker safety.
- Task 7: fix round 2/5 (one-shot and batch authority addressed; non-READ routing,
  READ mid-flight fencing, pending decoder parity, and stale-batch recovery open;
  commit `fe8cd14`).
- Task 7: fix round 3/5 (normal READ abort, decoder parity, and initial non-READ
  routing addressed; planner confirmation and current batch-authority recovery
  open; commit `4938d8d`).
- Task 7: fix round 4/5 (planner confirmation and read-only current Registry batch
  preflight addressed; 0 Critical/Important open; commit `4c920f2`).
- Task 8: fix round 1/4 (real production `resolve_read_turn`/`continue_resolved_read`
  replay, exact slot-set assertions, and non-empty initial Frame fixture added;
  0 Critical/Important open; commit `e8bd23f`).
- Task 8: fix round 2/4 (durable CAS-loser/lease-busy evidence separated from
  the CAS winner, per-case failure tracking, and production hybrid-fallback/
  technical-override paths exercised; 1 new Important open - a self-referential
  `applicable` argument made three zero-rate release gates a no-op; commit
  `634d47c`).
- Task 8: fix round 3/4 (added a 4-case per-case evidence backstop for the
  three broken gates; re-review found it covered only 4 of 13 `context-*`
  cases that populate the same aggregate metrics, leaving the remaining
  evidence unprotected; commit `e0ecb30`).
- Task 8: fix round 4/4 (replaced the per-case backstop with an aggregate
  exact-total check across all 13 context cases - `contextConflictCases=9`,
  `nonReadyFrames=10`, `callPlanSlotChecks=20`, independently verified against
  three separate release-gate runs and the live fixture list; 0
  Critical/Important open; commit `32f8b63`).
- Task 9: fix round 1/1 (initial dispatch BLOCKED at Step 1 - the brief's
  literal legacy-dispatch removal would break an active, unlisted caller
  backing the shipped `--context` CLI feature; escalated to the user, who
  ruled Option A - narrow the removal to `_read_context_mode()` only. Review
  of the narrowed implementation found the new contract test's fixture
  structurally could not reach the real `resolve_with_context` call path;
  fixed with a reachability sanity check plus a direct `last_context`
  invariant assertion, RED/GREEN verified; commit `cf63a7e`).

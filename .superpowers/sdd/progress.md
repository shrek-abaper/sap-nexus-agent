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
- [ ] Task 4: 实现 FactBuilderRegistry 与 ProjectionInputAssembler
- [ ] Task 5: 实现确定性 hash 与 MaterialSupplySnapshot projection
- [ ] Task 6: 完成端到端 Projection Eval 与隔离证明
- [ ] Task 7: 全量相关验证与 OpenSpec 任务收口

## Completed

- Task 1: complete (commits efcbe61..aea5172, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Projection type contracts + 1/1 focused test + typecheck clean.
- Task 2: complete (commits 3d2662b..127d115, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Exact version registry + structured fail-closed + duplicate rejection, 4/4 tests clean.
- Task 3: complete (commits dc10caa..291f2c2, review clean: Spec compliant + Quality Approved, 0 Critical/Important/Minor). Fresh/cache/restart projection data retention, 27/27 executor tests + typecheck clean.

## Current Blocker

- Task 4 review round 1: 3 Important findings. Decimal-string quantity normalization and deterministic PO tie-breaking are unambiguous fixes. Trace correlation needs a design choice because the frozen builder accepts only `NodeFactRecord`, while that record currently carries no agent-level trace.
- User selected Option A. Written design/spec patch committed as c1e302d and strict OpenSpec validation passed 20/20; waiting for written-spec review confirmation before plan update and fixer dispatch.
- Written spec confirmed. Existing plan updated with Task 4 review-fix Steps 7-11; dispatching fresh fixer for all three Important findings (review round 1/2).
- Extra round 3 committed `53f2681` and passed focused 47/47, frontend 206/206, typecheck/build, diff check, and OpenSpec strict 20/20. Final fresh re-review still found 2 Important issues: strict invalid-calendar rejection and `purchaseOrderItem` evidence/lineage. Review budget 3/3 exhausted; Task 4 is BLOCKED pending explicit user direction. Report: `.superpowers/sdd/task-4-rereview-3.md`.
- User selected continuation option 1 and authorized final round 4. Plan Steps 17-21 cover strict invalid-calendar rejection and `purchaseOrderItem` evidence identity; dispatching one fresh fixer, then one fresh final Task 4 reviewer.

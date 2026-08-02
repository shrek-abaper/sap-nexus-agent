# 验证报告: sap-nexus-incremental-sse-reconnect (P0B 项4)

> **Change:** `sap-nexus-incremental-sse-reconnect`
> **阶段:** verify -> archive
> **verify_mode:** full（scale: Tasks 20 > 3, Changed files 91 > 8, Delta specs 1）
> **日期:** 2026-08-02
> **分支:** `feature/20260802/sap-nexus-incremental-sse-reconnect`（from `e21262c`）

## 结论: **PASS** - 0 CRITICAL, 0 IMPORTANT, 0 WARNING（无 spec drift）

---

## 1. 验证命令（新鲜证据）

| 命令 | 结果 |
|---|---|
| `npm --prefix frontend run verify`（typecheck + test + build） | **EXIT 0** - 88/88 测试通过, tsc 无错, next build 成功（所有 route 编译） |
| `openspec validate --all --strict` | **15/15 passed, 0 failed** |
| `openspec list --json` | completedTasks 20/20, status `complete` |
| `bash scripts/verify-agent-callplan-evidence.sh` | Eval 6/6 + 3/3 passed, openspec validate 15/15 |
| `git status --short` | 干净（仅 ledger/.comet 流程状态文件；无源码未提交） |

所有命令在 verify 阶段新鲜运行（verification-before-completion Iron Law）。

## 2. Spec Delta 一致性（sse-cursor-reconnect/spec.md - ADDED 4 Requirements）

| Spec Requirement | Design § | 实现（Task） | 一致 |
|---|---|---|---|
| **Incremental SSE delivery** - 增量发布每个事件，非缓冲；每事件携带 `sequence` | §1 | Task 1 emitter（emitEventsFromOutcome）+ Task 2 createAgentRun 后台（void executeRunnerInBackground）+ Task 4 stream 轮询 | ✅ |
| **Event cursor for reconnect** - cursor = sequence；重连收到 `sequence > cursor` 事件 | §2 | Task 4 stream route `?cursor=N` 过滤 `sequence > cursor`；Task 5 客户端 lastSequence | ✅ |
| **Reconnect replay completeness** - 重连补发 cursor 后全部事件，升序，不丢失 | §3 | Task 4 `getAgentRunEvents`（load() 返回 sequence 升序）+ 过滤；per-event fsync（项1）保证不丢 | ✅ |
| **Terminal state closes stream** - run_completed/run_failed 后关闭；重连补发 terminal 后关闭 | §4 | Task 4 terminal close（`!backpressured && isTerminal`）；Task 1 §4.4 rejection run_failed 修复；Task 4.2 terminal 后重连关闭 | ✅ |

**Spec 场景测试覆盖:**
- "events stream incrementally" - Task 2 测试 "returns runId before runner"（events.length===1 run_started, runnerResolved===false）
- "reconnect resumes from cursor" - Task 4 测试 "filters events by cursor (sequence > cursor)"
- "cursor at terminal state" - Task 4 测试 "closes immediately when cursor >= terminal sequence"
- "no event loss on reconnect" / "event order preserved" - Task 4 replay 过滤 + load() 升序排序
- "terminal event delivered then stream closes" - Task 4 测试 "replays all events + closes"

## 3. 实现偏差（语义一致，已接受）

| 偏差 | Design doc | 实现 | 判定 |
|---|---|---|---|
| **背压信号** | §5: `controller.write(chunk)` 返回 false -> 暂停 | Task 4: `controller.desiredSize <= 0` break + `backpressured` flag | 接受 - 语义等价（均检测背压）；`backpressured` flag 是 load-bearing correctness 修复（brief verbatim 在 terminal 实际 enqueue 前关闭） |
| **Principal 鉴权** | spec/design 未含（写于项2 前） | 保留: `injectPrincipal(request)` + `getAgentRunEvents(runId, principal)`（项2 base-line） | 接受 - 安全硬边界（CLAUDE.md §2）；spec/design 对 principal 无约束；实现保留 |
| **测试 outcome status** | §7: success -> run_completed | Task 2/4 测试用 `clarification`（success 无 callPlan -> run_failed via emitTerminalOutcome，Task 1 继承逻辑） | 接受 - 测试数据选择；spec 未定义 success-without-callPlan；clarification 产生 run_completed 如测试断言 |
| **并发重复 idempotency（Task 3 I1）** | spec/design 未含 | fire-and-forget 把 markExecuted 移到 background；并发重复抛 "already decided" 非 no-op | 接受 - bounded-safe（decision guard 在 claim 前，无双 SAP 执行，无 corruption）；fire-and-forget emergent trade-off；final review 接受 |

**无 spec drift 需 Option A 偏差记录**（不同于项3 Check 6）。所有偏差语义一致或为安全保留的 base-line 适配。

## 4. Final Whole-Branch Review Triage

Final reviewer（opus）: **Ready-to-merge, 0 must-fix.**

| Finding | 严重度 | 处理 |
|---|---|---|
| Task 1: 测试未断言 stage/ordering | Minor | 接受（匹配 brief 自身测试代码） |
| Task 2: waitForRunSettled rejected-state 不可达；catch-release load-throws；double-release 修复 | Minor | 接受（pre-existing / 改进） |
| Task 3 I1: 并发重复 "already decided" | Important（非阻塞） | 接受（bounded-safe fire-and-forget trade-off；doc/characterization test nice-to-have） |
| Task 3 M1: terminal lease 未 release | Minor | 接受（brief verbatim 设计，lease TTL 安全） |
| Task 3 M2: re-awaiting continuation 未调 appendPendingOutcome | Minor | 接受（pre-existing） |
| Task 4 M1: cancel race after await | Minor | 接受（inherited from brief） |
| Task 4 M2: 未用测试 imports | Minor | 接受（inherited from brief, noUnusedLocals 未启用） |
| Task 4 M3: Number() 接受 empty/hex cursors | Minor | 接受（inherited from brief, 边缘情况） |
| Task 5 M1: 无 backoff | Minor | 接受（per-spec YAGNI） |
| Task 5 M2: lastSequence 覆盖非 Math.max | Minor | 接受（verbatim, SSE 单调递增） |
| Final: stream catch-block close() defensive try-catch | nice-to-have | 延后 |
| Final: 404 reconnect max-retry | nice-to-have | 延后 |
| Final: full-file replay per poll 性能 | nice-to-have | 延后（优化，spec 允许） |

所有 Minor/nice-to-have findings 接受或延后；无阻塞 merge。

## 5. 安全边界检查（CLAUDE.md §2）

- **WRITE capabilities MUST NOT execute until Human Approval confirmed**: 保留 - approval flow（decideAgentRunApproval）签名未变；continuation fire-and-forget 仅在 appendDecision（Human Approval 记录）后；无 WRITE 路径绕过。✅
- **Gateway accepts capabilityId only**: N/A（前端改动，无 Gateway/RFC）。✅
- **Principal auth（项2）**: 全程保留 - stream route `injectPrincipal`，`getAgentRunEvents(runId, principal)`，`createAgentRun`/`decide`/`confirm` 要求 principal；测试用 PLACEHOLDER_PRINCIPAL。SSE stream principal 注入正确。✅
- **无 credentials/tokens 提交**: git status 无密钥。✅

## 6. Task 完成

| Task | 状态 | Commit | Review |
|---|---|---|---|
| 1 Emitter + rejection terminal | ✅ | 94e0980 | Spec✅ Approved（1 Minor） |
| 2 createAgentRun background | ✅ | 71625d8 | Spec✅ Approved（3 Minor） |
| 3 Continuation background | ✅ | b42859a | Spec✅ Approved（1 I1 非阻塞, 2 Minor） |
| 4 Stream route cursor+poll+backpressure | ✅ | 08b0379 | Spec✅ Approved（3 Minor） |
| 5 Client reconnect | ✅ | fc23491 | Spec✅ Approved（2 Minor） |
| 6 Regression verify | ✅ | f4d155e | npm verify + openspec 15/15 + callplan |

openspec tasks.md: 20/20 complete。Plan: 6/6 tasks + 38/38 steps checked。

## 7. 结论

**PASS** - verify_mode=full。所有新鲜验证命令全绿（npm verify EXIT 0 / 88 测试, openspec 15/15, callplan 6/6+3/3）。Spec delta（4 ADDED Requirements）与 design doc 及实现一致。无 spec drift。所有 Minor/nice-to-have findings triage 接受/延后。安全边界保留。Final whole-branch review: Ready-to-merge, 0 must-fix。

可进入 verify->archive guard + merge to main + archive。

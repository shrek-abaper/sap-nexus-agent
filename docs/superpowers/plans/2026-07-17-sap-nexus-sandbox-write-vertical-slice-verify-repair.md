---
change: sap-nexus-sandbox-write-vertical-slice
design-doc: docs/superpowers/specs/2026-07-16-sap-nexus-sandbox-write-vertical-slice-design.md
base-ref: 44c6e8bc88a1e7455129889589bf38fd52de4c63
archived-with: 2026-07-17-sap-nexus-sandbox-write-vertical-slice
---

# SAP Nexus WRITE Verify-Fail Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 WRITE Human Approval 自动批准与 trace 不可回放两项 CRITICAL，使 Workbench 只有在用户明确批准后才执行 PR Action，并让 WRITE trace 完整记录脱敏结果证据。

**Architecture:** Agent 首次 Action 请求停在 `pending`，Workbench 服务端 run store 保存 exact CallPlan/ApprovalRecord/validation；浏览器 approval API 只提交 decision，批准 continuation 才执行 Gateway approve/execute。Gateway 从最终 `ActionResult` 生成脱敏 `resultSummary`，HTTP 响应与 trace 共用同一结果真相，READ 路径保持兼容。

**Tech Stack:** Python 3.11 + pytest、Next.js 15 + TypeScript + Vitest、Java 17 + Spring Boot + JUnit 5、OpenSpec/Comet。

## Global Constraints

- 不得再次执行 SAP WRITE；所有 repair 验证只能使用 mock/fake Gateway、单元测试和既有 live evidence。
- `run_query()` 对 Action 只能创建 pending approval，不得调用 `approve()`、`gateway.approve()` 或 `gateway.execute()`。
- approval endpoint 只接受 `approve|reject` decision；capability、参数、approvalId、snapshot hash 必须来自服务端 run store。
- continuation 必须校验 CallPlan 参数与 ApprovalRecord snapshot hash 一致，失败时不调用 Gateway。
- WRITE trace 记录 `prNumber`、`commitStatus`、SAP RETURN；SAP credential、destination、token、`.env` 不得进入 trace。
- READ capability 的响应、执行顺序和 trace 通用字段保持兼容。
- 只修改本 repair 直接涉及的代码、测试和契约；不做相邻重构。

## File Structure

| Path | Responsibility |
|---|---|
| `agent/sap_nexus_agent/orchestrator.py` | 首次 Action pending 与 approve/reject continuation |
| `agent/sap_nexus_agent/approval.py` | ApprovalRecord JSON 重建、快照校验和状态转换 |
| `agent/sap_nexus_agent/call_plan.py` | CallPlan JSON 重建供受控 continuation 使用 |
| `agent/sap_nexus_agent/cli.py` | 从 stdin 接收服务端保存的 continuation payload |
| `agent/sap_nexus_agent/workbench_output.py` | 输出 pending ApprovalRecord 与 continuation 结果 |
| `frontend/src/runtime/agent-runtime-adapter.ts` | run store、approval decision、Python continuation、事件追加 |
| `frontend/app/api/agent-runs/[runId]/approval/route.ts` | Workbench approve/reject API |
| `frontend/src/modules/human-approval/HumanApprovalPanel.tsx` | pending 参数摘要与批准/拒绝按钮 |
| `frontend/src/modules/agent-console/AgentConsole.tsx` | approval POST、同 run SSE 续拉和连接收尾 |
| `frontend/src/modules/agent-console/ChatStream.tsx` | 将 approval callback 传给 HITL 卡片 |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/trace/TraceRecord.java` | 通用 trace + 脱敏 resultSummary |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java` | 从 ActionResult 写同源 WRITE trace |
| `registry/capabilities.yaml` | PR 输出映射统一为 EXPORTS.NUMBER |

archived-with: 2026-07-17-sap-nexus-sandbox-write-vertical-slice
---

### Task 1: Agent external approval boundary

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Modify: `agent/sap_nexus_agent/approval.py`
- Modify: `agent/sap_nexus_agent/call_plan.py`
- Modify: `agent/sap_nexus_agent/workbench_output.py`
- Test: `agent/tests/test_orchestrator_write.py`
- Test: `agent/tests/test_workbench_output.py`

**Interfaces:**
- Produces: `AgentOutcome.approval_record: ApprovalRecord | None`
- Produces: `continue_action(call_plan, validation, approval_record, gateway, *, decision) -> AgentOutcome`
- Produces: `ApprovalRecord.from_dict(payload)` and `CallPlan.from_dict(payload)`
- Decision values: literal strings `approve` and `reject`

- [x] **Step 1: RED — 首次 Action 不得批准或 execute**

Replace the former synchronous-success expectation with:

```python
outcome = run_query(COMPLETE_PR_QUERY, gateway)

assert outcome.status == "awaiting_approval"
assert outcome.approval_record is not None
assert outcome.approval_record.status is ApprovalState.pending
assert gateway.approve_calls == []
assert gateway.execute_calls == []
```

Run:

```bash
.venv/bin/python -m pytest agent/tests/test_orchestrator_write.py -q
```

Expected: FAIL because current `run_query()` returns success/failure after automatically approving and executing.

- [x] **Step 2: GREEN — 首次 Action 只返回 pending**

Add `approval_record` to `AgentOutcome`. In the Action branch, create the pending record and return:

```python
return AgentOutcome(
    status="awaiting_approval",
    message="采购申请参数已就绪，等待人工审批。",
    response_text="请确认采购申请参数后批准或拒绝。",
    call_plan=call_plan,
    validation_result=validation,
    gateway_trace_id=validation.trace_id,
    approval_record=pending,
)
```

Keep Function execution exactly where it is. Remove `approve` and `mark_executed` imports from the initial path only; they will be used by `continue_action`.

- [x] **Step 3: RED — approve/reject continuation 使用 exact snapshot**

Add focused tests:

```python
approved = continue_action(
    pending.call_plan,
    pending.validation_result,
    pending.approval_record,
    gateway,
    decision="approve",
)
assert approved.status == "success"
assert gateway.approve_calls[0][1].status is ApprovalState.approved
assert gateway.execute_calls[0][1] == pending.approval_record.parameters

rejected = continue_action(
    pending.call_plan,
    pending.validation_result,
    pending.approval_record,
    gateway,
    decision="reject",
)
assert rejected.status == "rejected"
assert gateway.approve_calls == []
assert gateway.execute_calls == []
```

Add a mismatch test by changing one CallPlan parameter while keeping the original ApprovalRecord; assert `APPROVAL_VERSION_MISMATCH` and zero Gateway calls.

Run the focused test and confirm the function is missing.

- [x] **Step 4: GREEN — implement continuation**

Add the failure helper and implement only this state flow:

```python
def _approval_failure(
    call_plan: CallPlan,
    validation: ValidationResult,
    approval_record: ApprovalRecord,
    error_type: str,
    message: str,
) -> AgentOutcome:
    return AgentOutcome(
        status="failure",
        message=message,
        response_text=message,
        call_plan=call_plan,
        validation_result=validation,
        gateway_trace_id=validation.trace_id,
        error_type=error_type,
        approval_record=approval_record,
    )


def continue_action(
    call_plan: CallPlan,
    validation: ValidationResult,
    approval_record: ApprovalRecord,
    gateway: GatewayClientProtocol,
    *,
    decision: str,
) -> AgentOutcome:
    if call_plan.kind != "Action" or approval_record.status is not ApprovalState.pending:
        return _approval_failure(
            call_plan, validation, approval_record,
            "APPROVAL_REQUIRED", "审批记录不是可执行的 pending Action。",
        )
    if call_plan.capability_id != approval_record.capability_id:
        return _approval_failure(
            call_plan, validation, approval_record,
            "APPROVAL_VERSION_MISMATCH", "审批 capability 与 CallPlan 不一致。",
        )
    if compute_parameter_hash(call_plan.parameters) != approval_record.parameter_snapshot_hash:
        return _approval_failure(
            call_plan, validation, approval_record,
            "APPROVAL_VERSION_MISMATCH", "审批参数快照与 CallPlan 不一致。",
        )
    if decision == "reject":
        rejected = reject(approval_record)
        return AgentOutcome(
            status="rejected",
            message="用户已拒绝采购申请。",
            response_text="采购申请已拒绝，未执行 SAP 写入。",
            call_plan=call_plan,
            validation_result=validation,
            gateway_trace_id=validation.trace_id,
            approval_record=rejected,
        )
    if decision != "approve":
        return _approval_failure(
            call_plan, validation, approval_record,
            "INVALID_APPROVAL_DECISION", "审批决策只能是 approve 或 reject。",
        )

    approved = approve(approval_record)
    gateway.approve(call_plan.capability_id, approved)
    execution = gateway.execute(
        call_plan.capability_id,
        call_plan.parameters,
        approval_id=approved.approval_id,
        parameter_snapshot_hash=approved.parameter_snapshot_hash,
    )
    if not execution.success:
        messages = [_message_text(message) for message in execution.return_messages]
        return AgentOutcome(
            status="failure",
            message="Gateway execute failed",
            response_text=narrate_failure(execution.error_type, messages),
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            gateway_trace_id=execution.trace_id,
            error_type=execution.error_type,
            approval_record=approved,
        )
    executed = mark_executed(approved)
    return _finalize_pr_create(
        call_plan, validation, execution, approval_record=executed,
    )
```

Do not reparse the user's free text in continuation.

- [x] **Step 5: Serialize server-owned continuation context**

Add `from_dict` constructors with exact camelCase mapping and enum parsing. Add `approvalRecord` to `outcome_to_workbench_dict`. Test round-trip of CallPlan, ApprovalRecord and Workbench output.

- [x] **Step 6: Verify Task 1**

```bash
.venv/bin/python -m pytest agent/tests/test_orchestrator_write.py agent/tests/test_approval.py agent/tests/test_workbench_output.py -q
```

Expected: all focused tests pass; initial Action test proves zero approve/execute calls.

### Task 2: CLI continuation over stdin

**Files:**
- Modify: `agent/sap_nexus_agent/cli.py`
- Test: `agent/tests/test_cli.py` or create `agent/tests/test_cli_approval.py`

**Interfaces:**
- Consumes stdin JSON: `{decision, callPlan, validationResult, approvalRecord}`
- CLI flag: `--continue-action`
- Produces Workbench JSON on stdout

- [x] **Step 1: RED — continuation payload is read from stdin, not argv**

Patch stdin with a complete pending payload, invoke `main(["--continue-action", "--gateway-url", "http://gateway.test", "--json"])`, and assert the gateway double receives approved execute. Add a test proving malformed/missing stdin returns a non-zero code without Gateway calls.

- [x] **Step 2: GREEN — minimal CLI branch**

Add a mutually exclusive `--continue-action` flag. When set, read one JSON document from `sys.stdin`, reconstruct server-owned objects with the Task 1 `from_dict` methods, call `continue_action`, and print `outcome_to_workbench_dict`. Do not accept approval parameters as command-line flags.

- [x] **Step 3: Verify Task 2**

```bash
.venv/bin/python -m pytest agent/tests/test_cli_approval.py -q
```

Expected: approve/reject and invalid payload tests pass without real Gateway/SAP calls.

### Task 3: Workbench server-side pending context and approval API

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/run-event-schema.ts`
- Modify: `frontend/src/runtime/run-state-machine.ts`
- Create: `frontend/app/api/agent-runs/[runId]/approval/route.ts`
- Test: `frontend/tests/runtime/agent-runtime-adapter.test.ts`
- Test: `frontend/tests/runtime/run-state-machine.test.ts`
- Create: `frontend/tests/runtime/approval-route.test.ts`

**Interfaces:**
- Produces: `decideAgentRunApproval(runId: string, decision: "approve" | "reject")`
- Extends `AgentRunnerInput` with optional server-owned `continuation`
- Extends `AgentRunRecord` with `pendingOutcome?: WorkbenchOutcome` and `decision?: "approve" | "reject"`
- API: `POST /api/agent-runs/{runId}/approval` body `{decision}`

- [x] **Step 1: RED — initial Action emits awaiting events and stores context**

Stub the runner to return `status="awaiting_approval"` with callPlan, validationResult and approvalRecord. Assert events end with:

```typescript
expect(events.slice(-2).map((event) => [event.type, event.state, event.hitlState])).toEqual([
  ["approval_state_changed", "awaiting_approval", "approval_required"],
  ["approval_state_changed", "awaiting_approval", "awaiting_human_approval"]
]);
```

Assert no `gateway_execute_started`, `run_completed` or `run_failed` event exists.

- [x] **Step 2: RED — approve/reject and duplicate decisions**

Call `decideAgentRunApproval` after creating a pending run. Assert the runner's second invocation receives the stored callPlan/validationResult/approvalRecord, not fields from the browser. Reject must append a rejected event without execution. A second decision must reject with a conflict error and must not invoke the runner again.

- [x] **Step 3: GREEN — implement run-store transition**

Implement `decideAgentRunApproval` with these checks:

```typescript
if (!record.pendingOutcome || record.decision) throw new ApprovalConflictError();
if (decision !== "approve" && decision !== "reject") throw new InvalidApprovalDecisionError();
record.decision = decision;
const outcome = await runner({
  query: record.query,
  gatewayUrl: gatewayUrl(),
  intentMode: intentMode(),
  continuation: {
    decision,
    callPlan: record.pendingOutcome.callPlan,
    validationResult: record.pendingOutcome.validationResult,
    approvalRecord: record.pendingOutcome.approvalRecord
  }
});
appendApprovalEvents(record, outcome);
```

For reject, the Python continuation records `rejected`; no Gateway execute event is emitted. For approve, append `approved`, execute/result, and terminal events using monotonically increasing sequence numbers.

- [x] **Step 4: GREEN — stdin transport**

Extend `spawnAndCapture` with optional `stdinPayload`. For continuation, invoke Python with `--continue-action --json` and write exactly one JSON document to `child.stdin`, then close stdin. Do not add approval payload to `args` or logs.

- [x] **Step 5: RED/GREEN — approval route**

Route behavior:

```typescript
const payload = await request.json();
const keys = Object.keys(payload);
if (keys.some((key) => key !== "decision")) return 400;
await decideAgentRunApproval(runId, payload.decision);
return NextResponse.json({runId});
```

Assert valid approve/reject = 200, extra `parameters`/`capabilityId`/hash = 400, unknown run = 404, repeated decision = 409.

- [x] **Step 6: Verify Task 3**

```bash
npm --prefix frontend test -- --run frontend/tests/runtime/agent-runtime-adapter.test.ts frontend/tests/runtime/run-state-machine.test.ts frontend/tests/runtime/approval-route.test.ts
```

If Vitest treats paths relative to `frontend`, run the same command with `tests/runtime/agent-runtime-adapter.test.ts tests/runtime/run-state-machine.test.ts tests/runtime/approval-route.test.ts`. Expected: focused runtime/API tests pass.

### Task 4: Workbench HITL approval controls

**Files:**
- Modify: `frontend/src/modules/human-approval/HumanApprovalPanel.tsx`
- Modify: `frontend/src/modules/agent-console/ChatStream.tsx`
- Modify: `frontend/src/modules/agent-console/AgentConsole.tsx`
- Modify: `frontend/src/modules/agent-console/chat-types.ts`
- Modify: `frontend/app/globals.css`
- Test: `frontend/tests/agent-console/chat-bubble-state.test.ts`

**Interfaces:**
- `HumanApprovalPanel` props include `state`, redacted approval artifact, `onDecision`, `disabled`
- `ChatStream` receives `onApprovalDecision(serverRunId, decision)`

- [x] **Step 1: RED — pure UI state identifies actionable approval**

Add/extend a pure view-model test proving only `awaiting_human_approval` exposes actions; approved/rejected/completed states do not. Keep DOM test dependencies unchanged.

- [x] **Step 2: GREEN — render approval card and actions**

Render the HITL panel in the main answer body when awaiting approval, not only inside collapsed evidence. Show capability, material, plant, quantity/unit, delivery date, purchasing group, approvalId and expiry from the redacted approval artifact. Buttons call `onDecision("approve")` / `onDecision("reject")`; disable both while POST is in flight.

- [x] **Step 3: GREEN — same-run continuation UX**

In `AgentConsole`, when SSE receives `state="awaiting_approval"`, close the stream intentionally and set `isRunning=false` without assigning a transport error. On button click:

1. Set the turn running/decision-pending.
2. POST only `{decision}` to the server runId approval route.
3. Reopen `/stream` for the same server runId.
4. Apply only unseen sequence numbers to avoid duplicating initial events.
5. Stop on completed, failed or rejected.

- [x] **Step 4: Verify Task 4**

```bash
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run tests/agent-console/chat-bubble-state.test.ts tests/runtime/run-state-machine.test.ts
```

Expected: typecheck and focused tests pass; no browser or Gateway live call required.

### Task 5: Replay-complete Gateway WRITE trace

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/trace/TraceRecord.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/trace/TraceWriterTest.java`
- Test: `services/gateway/app/src/test/java/com/sapnexus/gateway/api/CapabilityWriteExecutionApiTest.java`

**Interfaces:**
- Adds `Map<String, Object> resultSummary` to `TraceRecord`
- Keeps existing `TraceRecord.of(String, String, String, Map<String, Object>, boolean, long, ErrorType)` overload and delegates with `Map.of()`
- Adds Action overload accepting the exact `ActionResult`

- [x] **Step 1: RED — trace writer replays WRITE results**

Create a `TraceRecord` for a successful Action and assert JSON contains:

```java
assertThat(content).contains("\"prNumber\":\"10137471\"");
assertThat(content).contains("\"commitStatus\":\"committed\"");
assertThat(content).contains("\"message\":\"Purchase requisition created\"");
```

Add business-error and secret-redaction cases. Validate/read factory calls must serialize `"resultSummary":{}`.

Run:

```bash
cd services/gateway
/tmp/gradle-8.8/bin/gradle --no-daemon :core:test --tests "com.sapnexus.gateway.trace.TraceWriterTest"
```

Expected: FAIL because `TraceRecord` lacks resultSummary.

- [x] **Step 2: GREEN — typed result summary with recursive sanitization**

Add `resultSummary` to the record. Preserve the existing factory signature. Add a factory that accepts ActionResult and builds only:

```java
Map.of(
    "prNumber", actionResult.prNumber(),
    "commitStatus", actionResult.commitStatus().name(),
    "returnMessages", actionResult.returnMessages()
)
```

Sanitize nested maps, records/lists and strings; remove unsafe keys rather than persisting raw destination/config values. Do not change parameter-summary behavior for iterable request values.

- [x] **Step 3: RED — Controller trace and HTTP response are same-source**

Provide a real temporary TraceWriter from `ObjectProvider` in `CapabilityWriteExecutionApiTest`. After approved success, assert both HTTP body and trace contain PR `10137471` and committed. Add an approval rejection assertion with `commitStatus=none` and an SAP error assertion with RETURN plus rolled_back.

- [x] **Step 4: GREEN — write trace from final ActionResult**

In Controller, construct one `ActionResult actionResult = ActionResult.fromExecutionResult(result)`. Pass it to the Action trace factory, then return that same object. READ still calls the existing trace factory and returns ExecutionResult.

- [x] **Step 5: Verify Task 5**

```bash
cd services/gateway
/tmp/gradle-8.8/bin/gradle --no-daemon :core:test --tests "com.sapnexus.gateway.trace.TraceWriterTest"
/tmp/gradle-8.8/bin/gradle --no-daemon :app:test --tests "com.sapnexus.gateway.api.CapabilityWriteExecutionApiTest"
```

Expected: focused core/app tests pass with no JCo/SAP call.

### Task 5A: Gateway approval authority, immutable snapshot, and single execution

**Files:**
- Modify: `agent/sap_nexus_agent/approval.py`
- Modify: `agent/sap_nexus_agent/gateway_client.py`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/*`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ActionResult.java`
- Modify: `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java`
- Test: corresponding Agent/Core/App/JCo focused suites

- [x] **Step 1: RED/GREEN — cross-language canonical snapshot hash**

Lock compact sorted UTF-8 JSON with a shared known SHA-256 vector. Gateway recomputes both stored ApprovalRecord parameters and actual execute parameters; a caller-supplied hash is only an additional cross-check.

- [x] **Step 2: RED/GREEN — trusted approval registration**

Require `X-SAP-Nexus-Approval-Token`, strict `approved` state, matching capability, TTL `1..600` seconds, and a self-consistent record hash. Verify the Agent sends the token only as a header.

- [x] **Step 3: RED/GREEN — atomic execute claim**

Add `claimForExecution` with atomic `approved -> executing`; only the winner may dispatch. Prove with store concurrency and controller-level two-request tests that dispatch count is exactly one.

- [x] **Step 4: RED/GREEN — truthful transaction outcome**

Do not infer commit state from ErrorType. Record pre-SAP failure as `none`, success as `committed`, rollback success as `rolled_back`, and rollback failure as `rollback_failed`. WRITE early failures must use replayable ActionResult; READ remains unchanged.

- [x] **Step 5: Verify Task 5A**

Run Agent approval/orchestrator tests, Gateway approval/core/app/JCo focused tests, and Workbench continuation tests. All tests use mocks only and must not execute SAP WRITE.

### Task 6: Contract drift, documentation, and full verification

**Files:**
- Modify: `registry/capabilities.yaml`
- Modify: `registry/executor-bindings.yaml` if allowed output names require `NUMBER`
- Modify: `agent/tests/test_pr_create_draft_capability.py`
- Modify: stale `PRITEMEXP` comments/tests directly tied to output mapping
- Modify: `docs/runbooks/11-sandbox-write-vertical-slice.md`
- Modify: `docs/runbooks/README.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Modify: `openspec/changes/sap-nexus-sandbox-write-vertical-slice/tasks.md`
- Modify: `docs/superpowers/reports/2026-07-17-sap-nexus-sandbox-write-vertical-slice-verify.md`

**Interfaces:**
- Registry output mapping: `prNumber: EXPORTS.NUMBER`
- Compatibility fallback remains executor-internal: `PRITEMEXP.PREQ_NO`

- [x] **Step 1: RED/GREEN — registry source-of-truth**

Change the real-registry test to assert `EXPORTS.NUMBER`; confirm RED, then update registry/binding and directly related fixtures. Keep the executor fallback test for empty export NUMBER.

- [x] **Step 2: Update durable docs without claiming PASS early**

Record the external approval continuation and replay-complete trace in runbook/roadmap. Keep the current verification report result FAIL until all commands and review pass. Explicitly state that no second SAP WRITE was performed.

- [x] **Step 3: Run focused suites and full deterministic verification**

```bash
.venv/bin/python -m pytest agent/tests/ -q
cd services/gateway && /tmp/gradle-8.8/bin/gradle --no-daemon test
npm --prefix frontend run verify
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
git diff --check
```

Expected: Agent/Gateway/frontend/eval/OpenSpec all pass. PostHog DNS flush noise does not override target command exit codes.

- [x] **Step 4: Thorough review and repair**

Use `requesting-code-review` on `44c6e8b...HEAD` plus current uncommitted repair diff, limited to correctness, WRITE safety, snapshot integrity, trace redaction and READ compatibility. Fix all CRITICAL/IMPORTANT findings and rerun affected tests.

- [x] **Step 5: Update verification report to PASS only with fresh evidence**

Replace the FAIL assessment with command outputs, requirement mapping, code-review disposition and explicit `SAP WRITE: not rerun`. Mark tasks 10.1-10.9 complete only after their evidence exists.

- [x] **Step 6: Commit repair for branch closeout**

After all verification passes:

```bash
git add agent frontend services/gateway registry openspec/changes/sap-nexus-sandbox-write-vertical-slice docs
git commit -m "fix(write): enforce external approval and replayable traces"
```

Before committing, inspect staged paths and exclude `.env`, runtime traces, `.superpowers/`, and `.comet/subagent-progress.md`.

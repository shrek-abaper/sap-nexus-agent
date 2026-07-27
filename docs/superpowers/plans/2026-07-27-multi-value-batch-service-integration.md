---
change: multi-value-batch-service-integration
design-doc: docs/superpowers/specs/2026-07-27-multi-value-batch-service-integration-design.md
base-ref: c5a7e72fa746c39112573c5399d5c19c7b2cbad2
---

# 多值批量确认服务层集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `awaiting_batch_confirm` 端到端可用——workbench 序列化 `combinations`，前端 `pendingOutcome` 持有并回传 `BatchContinuation`，runner 分派到已实现的 `continue_batch`，覆盖 CLI + workbench/SSE 两条路径。

**Architecture:** 全类比现有 `continue_action` 审批流：`awaiting_approval` → 序列化 `approvalRecord` → 前端持有 → `ApprovalContinuation` 回传 → `continue_action`。本 change 将 `awaiting_batch_confirm` → 序列化 `combinations` → 前端持有 → `BatchContinuation` 回传 → `continue_batch`（orchestrator.py:276 已实现，READ-only 守卫已保证）。`continue_batch` 不改，仅接上调用方。

**Tech Stack:** Python 3（argparse + stdin JSON）、TypeScript / Next.js Route Handlers / vitest、SSE 事件 schema。

## Global Constraints

- `continue_batch` 已实现（`agent/sap_nexus_agent/orchestrator.py:276`），本 change 不得修改其逻辑，仅接上调用方（CLI / runner）。
- READ-only 守卫：`continue_batch` 对 Action capability 抛 `ValueError`（已有），batch continuation 仅走 READ 路径。
- continuation 类型判别：`BatchContinuation` 必须携带 `type: "batch"`；`ApprovalContinuation` 加可选 `type?: "approval"`（向后兼容，不破坏现有 approval 测试）。runner 用 `continuation.type === "batch"` 分派。
- 前端持有 `combinations`（≤20 组合，小 dict），无服务端 BatchRecord，与 `approvalRecord` 前端持有一致。
- 不改 orchestrator/selector/narrator 核心逻辑；不改 capability 契约；不改 Action 审批流。
- 每个任务完成后：`tasks.md` 勾选 → git commit（不得积攒）。

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `agent/sap_nexus_agent/workbench_output.py` | `outcome_to_workbench_dict` 序列化 `combinations` | Modify (line 44 后插入) |
| `agent/sap_nexus_agent/cli.py` | `--continue-batch` 标志 + handler | Modify |
| `frontend/src/runtime/agent-runtime-adapter.ts` | `WorkbenchOutcome.combinations` + `BatchContinuation` + `confirmAgentRunBatch` + runner 分派 + SSE 事件 | Modify |
| `frontend/src/runtime/run-event-schema.ts` | `AgentRunState` + `AgentRunEventType` 扩展 | Modify |
| `frontend/app/api/agent-runs/[runId]/batch/route.ts` | batch 确认 HTTP 端点 | Create |
| `agent/tests/test_workbench_output.py` | combinations 序列化测试 | Modify (追加) |
| `agent/tests/test_cli_batch.py` | `--continue-batch` CLI 测试 | Create |
| `frontend/tests/runtime/agent-runtime-adapter.test.ts` | BatchContinuation 路由 + pendingOutcome 测试 | Modify (追加) |
| `frontend/tests/runtime/batch-route.test.ts` | batch route 端到端测试 | Create |

---

### Task 1: workbench 序列化 combinations

**Files:**
- Modify: `agent/sap_nexus_agent/workbench_output.py:44`（`approvalRecord` 行之后插入 `combinations`）
- Test: `agent/tests/test_workbench_output.py`（追加测试）

**Interfaces:**
- Consumes: `AgentOutcome.combinations: list[dict[str, str]] | None`（orchestrator.py:82，已存在）
- Produces: workbench dict 新增 `"combinations": list[dict[str,str]] | None` 键，供前端 `WorkbenchOutcome.combinations` 消费

- [x] **Step 1: 写失败测试——awaiting_batch_confirm 序列化 combinations**

追加到 `agent/tests/test_workbench_output.py` 末尾：

```python
def test_awaiting_batch_confirm_serializes_combinations():
    from sap_nexus_agent.call_plan import create_call_plan

    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA2", "plant": "5200"},
        kind="Function",
    )
    outcome = AgentOutcome(
        status="awaiting_batch_confirm",
        response_text="将查询 2 个组合，请确认。",
        call_plan=call_plan,
        combinations=[
            {"material": "DEMOA2", "plant": "5200"},
            {"material": "DEMOA2", "plant": "1000"},
        ],
    )

    result = outcome_to_workbench_dict(outcome)

    assert result["status"] == "awaiting_batch_confirm"
    assert result["combinations"] == [
        {"material": "DEMOA2", "plant": "5200"},
        {"material": "DEMOA2", "plant": "1000"},
    ]
    assert result["callPlan"] is not None
    assert result["callPlan"]["capabilityId"] == "MM.Inventory.GetAvailability"


def test_non_batch_outcome_combinations_is_none():
    outcome = AgentOutcome(
        status="success",
        response_text="库存为 100 EA",
    )

    result = outcome_to_workbench_dict(outcome)

    assert result["combinations"] is None
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_workbench_output.py::test_awaiting_batch_confirm_serializes_combinations tests/test_workbench_output.py::test_non_batch_outcome_combinations_is_none -v`
Expected: FAIL — `KeyError: 'combinations'`（序列化尚未加该键）

- [x] **Step 3: 实现——outcome_to_workbench_dict 序列化 combinations**

在 `agent/sap_nexus_agent/workbench_output.py` 的 `outcome_to_workbench_dict` 中，`approvalRecord` 行（line 44）之后插入一行（类比 `approvalRecord` 的 `to_dict() if ... else None` 模式）：

```python
        "approvalRecord": outcome.approval_record.to_dict() if outcome.approval_record else None,
        # Multi-value batch (Design Doc §4.1): combinations awaiting user
        # confirm. Populated only for status="awaiting_batch_confirm"; None
        # for every other path. The frontend holds these in pendingOutcome
        # and returns them via BatchContinuation -> continue_batch.
        "combinations": [dict(c) for c in outcome.combinations] if outcome.combinations else None,
```

- [x] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_workbench_output.py::test_awaiting_batch_confirm_serializes_combinations tests/test_workbench_output.py::test_non_batch_outcome_combinations_is_none -v`
Expected: PASS（2 passed）

- [x] **Step 5: 回归现有 workbench_output 测试**

Run: `cd agent && python -m pytest tests/test_workbench_output.py -v`
Expected: PASS（全部既有测试 + 2 新测试通过，无回归）

- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/workbench_output.py agent/tests/test_workbench_output.py
git commit -m "feat(workbench): serialize combinations for awaiting_batch_confirm outcome"
```

---

### Task 2: 前端 BatchContinuation + pendingOutcome + runner 分派 + SSE 事件

本 task 覆盖 tasks.md §2 全部子项（2.1-2.5），并前置扩展 `run-event-schema.ts`（adapter 的 SSE 事件依赖新 state/event type）。

**Files:**
- Modify: `frontend/src/runtime/run-event-schema.ts:3-37`（`AgentRunEventType` + `AgentRunState` 扩展）
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts:44-88`（类型）、`:136-194`（createAgentRun）、`:205-237`（新增 confirmAgentRunBatch）、`:247-419`（buildEventsFromOutcome batch 分支）、`:526-605`（新增 appendBatchEvents）、`:640-692`（runner 分派）
- Test: `frontend/tests/runtime/agent-runtime-adapter.test.ts`（追加 batch 测试）

**Interfaces:**
- Consumes: workbench dict 的 `"combinations"` 键（Task 1 产出）
- Produces:
  - `WorkbenchOutcome.combinations?: Record<string,string>[] | null`
  - `BatchContinuation` 类型（`{ type: "batch"; callPlan: Record<string,unknown>; combinations: Record<string,string>[] }`）
  - `AgentRunnerInput.continuation?: ApprovalContinuation | BatchContinuation`
  - export `confirmAgentRunBatch(runId: string): Promise<void>`
  - `AgentRunState` 新增 `"awaiting_batch_confirm"`；`AgentRunEventType` 新增 `"batch_confirm_requested"`

- [x] **Step 1: 扩展 run-event-schema.ts（加 state + event type）**

在 `frontend/src/runtime/run-event-schema.ts` 中：

`AgentRunEventType` 联合类型末尾（`"match_decision_created"` 之后）加：

```typescript
  | "match_decision_created"
  | "batch_confirm_requested";
```

`AgentRunState` 联合类型中 `"awaiting_approval"` 之后加：

```typescript
  | "awaiting_approval"
  | "awaiting_batch_confirm"
```

- [x] **Step 2: 写失败测试——awaiting_batch_confirm pendingOutcome 持有 + confirmAgentRunBatch 分派**

追加到 `frontend/tests/runtime/agent-runtime-adapter.test.ts` 末尾（类比现有 approval continuation 测试，line 172-241）：

```typescript
  it("holds an awaiting_batch_confirm outcome pending user confirmation", async () => {
    const pendingOutcome = {
      status: "awaiting_batch_confirm",
      responseText: "将查询 2 个组合，请确认。",
      callPlan: {
        agentTraceId: "agent-batch",
        capabilityId: "MM.Inventory.GetAvailability",
        kind: "Function",
        parameters: { material: "DEMOA2", plant: "5200" },
        validationPolicy: "validate_before_execute",
        createdBy: "agent",
        requiresApproval: false
      },
      combinations: [
        { material: "DEMOA2", plant: "5200" },
        { material: "DEMOA2", plant: "1000" }
      ]
    };
    const runner = vi.fn().mockResolvedValueOnce(pendingOutcome);
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存" });

    const events = await getAgentRunEvents(run.runId);
    expect(events.some((e) => e.state === "awaiting_batch_confirm")).toBe(true);
    expect(events.some((e) => e.type === "batch_confirm_requested")).toBe(true);
  });

  it("routes a BatchContinuation to continue_batch exactly once after confirmation", async () => {
    const pendingOutcome = {
      status: "awaiting_batch_confirm",
      callPlan: {
        agentTraceId: "agent-batch",
        capabilityId: "MM.Inventory.GetAvailability",
        kind: "Function",
        parameters: { material: "DEMOA2", plant: "5200" },
        validationPolicy: "validate_before_execute",
        createdBy: "agent",
        requiresApproval: false
      },
      combinations: [
        { material: "DEMOA2", plant: "5200" },
        { material: "DEMOA2", plant: "1000" }
      ]
    };
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "success",
        responseText: "物料 DEMOA2：在工厂 5200 为 176 EA；在工厂 1000 为 0 EA。"
      });
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存" });
    await confirmAgentRunBatch(run.runId);

    expect(runner).toHaveBeenCalledTimes(2);
    const batchCall = runner.mock.calls[1][0];
    expect(batchCall.continuation).toEqual({
      type: "batch",
      callPlan: pendingOutcome.callPlan,
      combinations: pendingOutcome.combinations
    });
    const events = await getAgentRunEvents(run.runId);
    expect(events.some((e) => e.type === "run_completed")).toBe(true);
  });
```

注意：测试文件顶部已有的 import 需补上 `confirmAgentRunBatch` 和 `getAgentRunEvents`（若未导入）。检查现有 import 块（line 1-7 区域），追加：

```typescript
import {
  createAgentRun,
  confirmAgentRunBatch,
  getAgentRunEvents,
  resetAgentRunsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";
```

- [x] **Step 3: 运行测试验证失败**

Run: `npm --prefix frontend test -- --run tests/runtime/agent-runtime-adapter.test.ts`
Expected: FAIL — `confirmAgentRunBatch is not a function` / `batch_confirm_requested` 事件未发出 / 类型错误

- [x] **Step 4: 扩展类型定义——WorkbenchOutcome.combinations + BatchContinuation + 联合 continuation**

在 `frontend/src/runtime/agent-runtime-adapter.ts` 中：

(a) `ApprovalContinuation`（line 44-49）加可选 `type` 字段（向后兼容，现有 approval 测试无需改动）：

```typescript
type ApprovalContinuation = {
  type?: "approval";
  decision: ApprovalDecision;
  callPlan: Record<string, unknown>;
  validationResult: Record<string, unknown>;
  approvalRecord: Record<string, unknown>;
};
```

(b) 在 `ApprovalContinuation` 定义之后新增 `BatchContinuation`：

```typescript
type BatchContinuation = {
  type: "batch";
  callPlan: Record<string, unknown>;
  combinations: Record<string, string>[];
};
```

(c) `AgentRunnerInput.continuation`（line 51-57）改为联合类型：

```typescript
type AgentRunnerInput = {
  query: string;
  gatewayUrl: string;
  intentMode: string;
  continuation?: ApprovalContinuation | BatchContinuation;
  context?: ConversationContext;
};
```

(d) `WorkbenchOutcome`（line 59-88）在 `approvalRecord` 字段之后加 `combinations`：

```typescript
  approvalRecord?: Record<string, unknown> | null;
  // Multi-value batch (Design Doc §4.2): combinations awaiting user confirm.
  // Populated only for status="awaiting_batch_confirm". The adapter holds
  // these in pendingOutcome and returns them via BatchContinuation.
  combinations?: Record<string, string>[] | null;
```

- [x] **Step 5: 实现——createAgentRun 持有 awaiting_batch_confirm pendingOutcome**

在 `createAgentRun`（line 174-176）扩展 pendingOutcome 持有条件：

```typescript
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      record.pendingOutcome = outcome;
    }
```

- [x] **Step 6: 实现——新增 confirmAgentRunBatch（类比 decideAgentRunApproval）**

在 `decideAgentRunApproval` 函数（line 205-237）之后新增：

```typescript
export async function confirmAgentRunBatch(runId: string): Promise<void> {
  const record = runs.get(runId);
  if (!record) {
    throw new Error("Agent run not found");
  }
  if (!record.pendingOutcome) {
    throw new Error("Agent run is not awaiting batch confirmation");
  }
  if (record.decision) {
    throw new Error("Agent run was already decided");
  }

  const callPlan = objectOrNull(record.pendingOutcome.callPlan);
  const combinations = record.pendingOutcome.combinations ?? null;
  if (!callPlan || !combinations) {
    throw new Error("Agent run batch context is incomplete");
  }

  record.decision = "approve";
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { type: "batch", callPlan, combinations }
    });
    appendBatchEvents(record, outcome, new Date().toISOString());
  } catch (error) {
    appendRuntimeFailure(record, error, new Date().toISOString());
  }
}
```

说明：复用 `record.decision = "approve"` 标记"已处理"，使 `createAgentRun` 的 Q2 pending 阻塞检查（line 153 `!lastRun.decision`）对 batch 同样生效——batch pending 时阻塞新查询，确认后解除。

- [x] **Step 7: 实现——runner 分派 BatchContinuation 到 --continue-batch**

在 `runLocalPythonAgent`（line 646-655）中，将 `if (input.continuation)` 分支改为按 `type` 分派：

```typescript
  if (input.continuation) {
    const isBatch = input.continuation.type === "batch";
    args = [
      "-m",
      "sap_nexus_agent.cli",
      isBatch ? "--continue-batch" : "--continue-action",
      "--gateway-url",
      input.gatewayUrl,
      "--json"
    ];
    stdinPayload = JSON.stringify(input.continuation);
  } else if (input.context) {
```

- [x] **Step 8: 实现——buildEventsFromOutcome 发 awaiting_batch_confirm 事件**

在 `buildEventsFromOutcome` 中，`awaiting_approval` 分支（line 332-352）之后、`if (execution)` 之前插入 batch 分支：

```typescript
  if (outcome.status === "awaiting_batch_confirm") {
    const combinations = outcome.combinations ?? null;
    push(events, runId, timestamp, {
      type: "batch_confirm_requested",
      state: "awaiting_batch_confirm",
      capabilityId,
      agentTraceId,
      artifact: combinations
        ? redactArtifact({
            label: "BatchCombinations",
            kind: "callplan",
            payload: toJsonValue({ combinations, callPlan })
          })
        : undefined
    });
    return events;
  }
```

- [x] **Step 9: 实现——新增 appendBatchEvents（类比 appendApprovalEvents）**

在 `appendApprovalEvents` 函数（line 526-605）之后新增：

```typescript
function appendBatchEvents(record: AgentRunRecord, outcome: WorkbenchOutcome, timestamp: string) {
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId);

  if (outcome.responseText) {
    push(record.events, record.runId, timestamp, {
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: toJsonValue({ text: outcome.responseText })
      })
    });
  }
  if (outcome.status === "success") {
    push(record.events, record.runId, timestamp, {
      type: "run_completed",
      state: "completed",
      capabilityId,
      agentTraceId,
      gatewayTraceId
    });
  } else {
    pushFailure(record.events, record.runId, timestamp, "executing", outcome);
  }
}
```

- [x] **Step 10: 运行测试验证通过**

Run: `npm --prefix frontend test -- --run tests/runtime/agent-runtime-adapter.test.ts`
Expected: PASS（新增 2 个 batch 测试 + 全部既有 approval 测试通过）

- [x] **Step 11: 前端全量验证（typecheck + test + lint）**

Run: `npm --prefix frontend run verify`
Expected: PASS（无 type error，无回归）

- [x] **Step 12: Commit**

```bash
git add frontend/src/runtime/run-event-schema.ts frontend/src/runtime/agent-runtime-adapter.ts frontend/tests/runtime/agent-runtime-adapter.test.ts
git commit -m "feat(runtime): BatchContinuation + confirmAgentRunBatch + awaiting_batch_confirm SSE"
```

---

### Task 3: CLI --continue-batch

**Files:**
- Modify: `agent/sap_nexus_agent/cli.py:13`（import）、`:24-59`（argparse + handler）
- Test: `agent/tests/test_cli_batch.py`（Create）

**Interfaces:**
- Consumes: `continue_batch(call_plan, combinations, gateway, *, decision=None)`（orchestrator.py:276，已实现）、`CallPlan.from_dict`（call_plan.py:18，已存在）
- Produces: `python -m sap_nexus_agent.cli --continue-batch --json`，stdin 读取 `{callPlan, combinations}` JSON，stdout 输出 workbench dict

- [x] **Step 1: 写失败测试——--continue-batch 调 continue_batch 返回批量结果**

创建 `agent/tests/test_cli_batch.py`（类比 `agent/tests/test_cli_approval.py`）：

```python
from __future__ import annotations

import io
import json
import sys

from sap_nexus_agent import cli
from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult


class StubBatchGateway:
    def __init__(self):
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, dict(parameters)))
        return ValidationResult(
            trace_id="trace-validate",
            capability_id=capability_id,
            success=True,
            error_type="NONE",
            messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None, parameter_snapshot_hash=None):
        self.execute_calls.append((capability_id, dict(parameters)))
        plant = parameters.get("plant", "")
        return ExecutionResult.from_dict({
            "traceId": "trace-execute",
            "capabilityId": capability_id,
            "success": True,
            "executor": {"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
            "returnMessages": [],
            "data": {
                "material": parameters.get("material", ""),
                "plant": plant,
                "availableQuantity": 176 if plant == "5200" else 0,
                "unit": "EA",
            },
            "durationMs": 12,
            "errorType": "NONE",
        })


def _batch_payload():
    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA2", "plant": "5200"},
        kind="Function",
    )
    return {
        "callPlan": call_plan.to_dict(),
        "combinations": [
            {"material": "DEMOA2", "plant": "5200"},
            {"material": "DEMOA2", "plant": "1000"},
        ],
    }


def test_cli_continues_batch_from_stdin(monkeypatch, capsys):
    gateway = StubBatchGateway()
    monkeypatch.setattr(cli, "GatewayClient", lambda _url: gateway)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_batch_payload())))

    result = cli.main([
        "--continue-batch",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "success"
    assert len(gateway.execute_calls) == 2
    assert payload["responseText"] != ""


def test_cli_rejects_missing_batch_payload(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    result = cli.main([
        "--continue-batch",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    assert result != 0
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd agent && python -m pytest tests/test_cli_batch.py -v`
Expected: FAIL — `SystemExit: 2` / `unrecognized arguments: --continue-batch`（argparse 尚未注册）

- [x] **Step 3: 实现——cli.py 加 --continue-batch**

在 `agent/sap_nexus_agent/cli.py` 中：

(a) line 13 import 补 `continue_batch`：

```python
from sap_nexus_agent.orchestrator import continue_action, continue_batch, run_query
```

(b) 在 `--continue-action` argparse 参数（line 24-28）之后新增 `--continue-batch`：

```python
    parser.add_argument(
        "--continue-batch",
        action="store_true",
        help="Read a batch continuation payload (callPlan + combinations) from stdin",
    )
```

(c) 在 `--continue-action` handler 分支（line 37-59 `if args.continue_action:` 块）之后、`if args.context:` 之前，新增 `--continue-batch` handler 分支：

```python
    if args.continue_batch:
        try:
            payload = json.load(sys.stdin)
            outcome = continue_batch(
                CallPlan.from_dict(dict(payload["callPlan"])),
                [dict(c) for c in payload["combinations"]],
                gateway,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "INVALID_BATCH_PAYLOAD",
                    "message": "Invalid batch continuation payload.",
                }))
            return 2
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status == "success" else 1
```

- [x] **Step 4: 运行测试验证通过**

Run: `cd agent && python -m pytest tests/test_cli_batch.py -v`
Expected: PASS（2 passed）

- [x] **Step 5: 回归现有 CLI 测试**

Run: `cd agent && python -m pytest tests/test_cli_approval.py tests/test_cli_context.py -v`
Expected: PASS（无回归；`--continue-action` 与 `--context` 路径不受影响）

- [x] **Step 6: Commit**

```bash
git add agent/sap_nexus_agent/cli.py agent/tests/test_cli_batch.py
git commit -m "feat(cli): add --continue-batch flag for confirmed multi-value batch"
```

---

### Task 4: API batch route / SSE

**Files:**
- Create: `frontend/app/api/agent-runs/[runId]/batch/route.ts`（类比 `frontend/app/api/agent-runs/[runId]/approval/route.ts`）
- Test: `frontend/tests/runtime/batch-route.test.ts`（Create，类比 `frontend/tests/runtime/approval-route.test.ts`）
- Note: `AgentRunState`/`AgentRunEventType` 已在 Task 2 扩展；SSE 事件已在 Task 2 的 `buildEventsFromOutcome` 中发出。本 task 仅补 HTTP 端点。

**Interfaces:**
- Consumes: `confirmAgentRunBatch(runId: string): Promise<void>`（Task 2 产出，已 export）
- Produces: `POST /api/agent-runs/[runId]/batch`，body 为空对象 `{}`（batch 无 decision，仅确认），调 `confirmAgentRunBatch`，返回 `{ runId }`

- [x] **Step 1: 写失败测试——batch route 端到端**

创建 `frontend/tests/runtime/batch-route.test.ts`（类比 `frontend/tests/runtime/approval-route.test.ts`）：

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "../../app/api/agent-runs/[runId]/batch/route";
import {
  createAgentRun,
  resetAgentRunsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";

const pendingBatchOutcome = {
  status: "awaiting_batch_confirm",
  responseText: "将查询 2 个组合，请确认。",
  callPlan: {
    agentTraceId: "agent-batch",
    capabilityId: "MM.Inventory.GetAvailability",
    kind: "Function",
    parameters: { material: "DEMOA2", plant: "5200" },
    validationPolicy: "validate_before_execute",
    createdBy: "agent",
    requiresApproval: false
  },
  combinations: [
    { material: "DEMOA2", plant: "5200" },
    { material: "DEMOA2", plant: "1000" }
  ]
};

function request(body: unknown) {
  return new Request("http://localhost/api/agent-runs/run/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

describe("agent run batch route", () => {
  beforeEach(() => resetAgentRunsForTests());
  afterEach(() => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
  });

  it("confirms a pending server-owned batch and returns runId", async () => {
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingBatchOutcome)
      .mockResolvedValueOnce({
        status: "success",
        responseText: "物料 DEMOA2：在工厂 5200 为 176 EA；在工厂 1000 为 0 EA。"
      });
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存" });

    const response = await POST(request({}), {
      params: Promise.resolve({ runId: run.runId })
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ runId: run.runId });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("maps missing runs to 404", async () => {
    const missing = await POST(request({}), {
      params: Promise.resolve({ runId: "missing" })
    });
    expect(missing.status).toBe(404);
  });

  it("maps duplicate confirmations to 409", async () => {
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingBatchOutcome)
      .mockResolvedValueOnce({ status: "success", responseText: "完成" });
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存" });
    await POST(request({}), { params: Promise.resolve({ runId: run.runId }) });

    const duplicate = await POST(request({}), {
      params: Promise.resolve({ runId: run.runId })
    });
    expect(duplicate.status).toBe(409);
  });
});
```

- [x] **Step 2: 运行测试验证失败**

Run: `npm --prefix frontend test -- --run tests/runtime/batch-route.test.ts`
Expected: FAIL — 模块 `../../app/api/agent-runs/[runId]/batch/route` 不存在

- [x] **Step 3: 实现——创建 batch route handler**

创建 `frontend/app/api/agent-runs/[runId]/batch/route.ts`（类比 `approval/route.ts`，但 body 为空、调 `confirmAgentRunBatch`）：

```typescript
import { NextResponse } from "next/server";
import { confirmAgentRunBatch } from "../../../../../src/runtime/agent-runtime-adapter";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return invalidRequest("Request body must be valid JSON.");
  }
  if (payload && (typeof payload !== "object" || Array.isArray(payload))) {
    return invalidRequest("Batch confirmation accepts an empty JSON object only.");
  }

  const { runId } = await params;
  try {
    await confirmAgentRunBatch(runId);
    return NextResponse.json({ runId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Batch confirmation failed";
    if (message.includes("not found")) {
      return NextResponse.json({ errorType: "RUN_NOT_FOUND", message }, { status: 404 });
    }
    if (message.includes("already decided") || message.includes("not awaiting batch")) {
      return NextResponse.json({ errorType: "BATCH_CONFLICT", message }, { status: 409 });
    }
    return NextResponse.json({ errorType: "INVALID_BATCH_REQUEST", message }, { status: 400 });
  }
}

function invalidRequest(message: string) {
  return NextResponse.json({ errorType: "INVALID_BATCH_REQUEST", message }, { status: 400 });
}
```

- [x] **Step 4: 运行测试验证通过**

Run: `npm --prefix frontend test -- --run tests/runtime/batch-route.test.ts`
Expected: PASS（3 passed）

- [x] **Step 5: 前端全量验证**

Run: `npm --prefix frontend run verify`
Expected: PASS（typecheck + 全部测试 + lint 无回归）

- [x] **Step 6: Commit**

```bash
git add frontend/app/api/agent-runs/[runId]/batch/route.ts frontend/tests/runtime/batch-route.test.ts
git commit -m "feat(api): add POST /api/agent-runs/[runId]/batch confirmation route"
```

---

### Task 5: 端到端验证

**Files:**
- 无源码变更；仅运行验证命令并勾选 `tasks.md`

**Interfaces:**
- Consumes: Task 1-4 全部产出
- Produces: 所有验证命令通过 + `tasks.md` 全部勾选 + openspec 校验通过

- [x] **Step 1: openspec 校验**

Run: `openspec validate --all --strict`
Expected: PASS（delta spec 的 2 个新 Scenario 合规）

- [x] **Step 2: Python 回归**

Run: `cd agent && python -m pytest tests/test_workbench_output.py tests/test_cli_batch.py tests/test_cli_approval.py tests/test_cli_context.py tests/test_orchestrator.py tests/test_conversation_context.py -v`
Expected: PASS（workbench 序列化 + cli batch + cli approval + cli context + orchestrator continue_batch + conversation_context awaiting_batch_confirm lastContext=None 全部通过）

- [x] **Step 3: 前端回归**

Run: `npm --prefix frontend run verify`
Expected: PASS（agent-runtime-adapter batch 测试 + batch-route 测试 + 全部既有测试通过）

- [x] **Step 4: callplan evidence 验证**

Run: `scripts/verify-agent-callplan-evidence.sh`
Expected: PASS

- [x] **Step 5: e2e 链路确认（手动串联各层测试证据）**

逐项确认端到端链路各环节已被自动化测试覆盖（无需新写测试，汇总已有证据）：

1. **Turn N — 多值 -> awaiting_batch_confirm + combinations 序列化**：
   - `test_workbench_output.py::test_awaiting_batch_confirm_serializes_combinations` 证明 workbench dict 含 `combinations` + `callPlan`。
   - `agent-runtime-adapter.test.ts` "holds an awaiting_batch_confirm outcome pending user confirmation" 证明前端 `pendingOutcome` 持有 + SSE 发 `batch_confirm_requested` 事件。
2. **Turn N+1 — 确认 -> continue_batch -> 批量聚合**：
   - `agent-runtime-adapter.test.ts` "routes a BatchContinuation to continue_batch exactly once after confirmation" 证明 runner 收到 `{type:"batch", callPlan, combinations}` 并发出 `run_completed`。
   - `test_cli_batch.py::test_cli_continues_batch_from_stdin` 证明 CLI `--continue-batch` 调 `continue_batch` 执行 2 个组合并返回聚合 `responseText`。
   - `batch-route.test.ts` "confirms a pending server-owned batch" 证明 `POST /api/agent-runs/[runId]/batch` 触发 `confirmAgentRunBatch` 并返回 200。

确认：以上 5 项测试全部 PASS 即等价于 e2e 链路打通（Python 序列化 → 前端持有 → runner 分派 → CLI/API 确认 → continue_batch 聚合）。

- [x] **Step 6: 勾选 tasks.md 并 commit**

将 `openspec/changes/multi-value-batch-service-integration/tasks.md` 中 §1-§5 所有未勾选项勾选，然后：

```bash
git add openspec/changes/multi-value-batch-service-integration/tasks.md
git commit -m "chore(llm-intent): check off all tasks for multi-value-batch-service-integration"
```

---

## Self-Review

**1. Spec coverage** — 对照 delta spec（`specs/agent-callplan-evidence/spec.md`）的 Scenario：
- `awaiting_batch_confirm serializes combinations to workbench` → Task 1（序列化）+ Task 2 Step 8（SSE 事件）覆盖。
- `continue_batch service entry executes confirmed batch` → Task 2 Step 6-7（confirmAgentRunBatch + runner 分派）+ Task 3（CLI --continue-batch）+ Task 4（API route）覆盖。
- 既有 Scenario（multi-value split / executes and aggregates / partial failure / cap / clears last_context）已在先前 change 的 Task 6-8 完成，本 change 不回归。

**2. Placeholder scan** — 全部 step 含完整代码，无 TBD/TODO/"add error handling"/"similar to Task N"。

**3. Type consistency** —
- `BatchContinuation.type: "batch"` 在 Task 2 定义、Step 6 构造、Step 7 判别、Task 3 stdin payload（CLI 端不依赖 type，按 `--continue-batch` 标志分派）一致。
- `WorkbenchOutcome.combinations: Record<string,string>[] | null` 在 Task 1 Python 序列化（`list[dict[str,str]]`）、Task 2 TS 类型、测试 payload 一致。
- `confirmAgentRunBatch` 在 Task 2 export、Task 4 import 调用，签名一致。
- `AgentRunState` `"awaiting_batch_confirm"` 在 run-event-schema（Task 2 Step 1）、buildEventsFromOutcome（Step 8）、测试断言（Step 2）一致。
- `AgentRunEventType` `"batch_confirm_requested"` 同上。

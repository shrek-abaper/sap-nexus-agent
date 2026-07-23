import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createAgentRun,
  decideAgentRunApproval,
  getAgentRunEvents,
  resetAgentRunsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";

describe("agent runtime adapter", () => {
  beforeEach(() => {
    resetAgentRunsForTests();
  });

  afterEach(() => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
  });

  it("creates a read-only run from live runner output instead of deterministic fake events", async () => {
    const runner = vi.fn(async () => ({
      status: "success",
      responseText: "物料 MAT-LIVE 在工厂 1000 的可用库存为 7 EA。",
      callPlan: {
        agentTraceId: "agent-live-trace",
        capabilityId: "MM.Inventory.GetAvailability",
        kind: "Function",
        parameters: { material: "MAT-LIVE", plant: "1000", unit: "EA" },
        validationPolicy: "validate_before_execute",
        createdBy: "agent",
        requiresApproval: false
      },
      validationResult: {
        traceId: "gw-validate-live",
        capabilityId: "MM.Inventory.GetAvailability",
        success: true,
        errorType: "NONE",
        messages: []
      },
      executionResult: {
        traceId: "gw-execute-live",
        capabilityId: "MM.Inventory.GetAvailability",
        success: true,
        executor: { type: "JCO_RFC", rfcName: "BAPI_MATERIAL_AVAILABILITY" },
        returnMessages: [],
        data: { material: "MAT-LIVE", plant: "1000", availableQuantity: 7, unit: "EA" },
        durationMs: 25,
        errorType: "NONE"
      },
      fact: {
        factId: "fact-live",
        agentTraceId: "agent-live-trace",
        traceId: "agent-live-trace",
        gatewayTraceId: "gw-execute-live",
        domain: "MM",
        businessObject: "InventoryStock",
        predicate: "availableQuantity",
        value: 7,
        unit: "EA",
        deterministic: true,
        confidence: 1,
        source: { capabilityId: "MM.Inventory.GetAvailability", executorType: "JCO_RFC" },
        evidence: [{ field: "availableQuantity", value: 7, sourceField: "AV_QTY_PLT" }],
        material: "MAT-LIVE",
        plant: "1000"
      },
      gatewayTraceId: "gw-execute-live"
    }));
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "MAT-LIVE 在 1000 还有多少可用库存？" });
    const events = await getAgentRunEvents(run.runId);

    expect(runner).toHaveBeenCalledWith({
      query: "MAT-LIVE 在 1000 还有多少可用库存？",
      gatewayUrl: "http://127.0.0.1:8080",
      intentMode: "hybrid"
    });
    expect(events.map((event) => event.sequence)).toEqual(events.map((_, index) => index + 1));
    expect(events.map((event) => event.type)).toEqual([
      "run_started",
      "intent_parsed",
      "capability_selected",
      "callplan_created",
      "approval_state_changed",
      "gateway_validate_started",
      "gateway_validate_completed",
      "gateway_execute_started",
      "gateway_execute_completed",
      "reasoning_fact_created",
      "narrative_created",
      "trace_linked",
      "run_completed"
    ]);
    expect(events.some((event) => event.hitlState === "approval_not_required")).toBe(true);
    expect(JSON.stringify(events)).toContain("\"availableQuantity\":7");
    expect(JSON.stringify(events)).not.toContain("\"availableQuantity\":12");
    expect(JSON.stringify(events)).not.toContain("agent-demo-trace");
    expect(JSON.stringify(events)).not.toContain("gateway-demo-trace");
    expect(JSON.stringify(events)).not.toContain("SAP_PASSWORD");
  });

  it("rejects raw RFC override attempts before invoking the runner", async () => {
    const runner = vi.fn(async () => ({ status: "success" }));
    setAgentRunnerForTests(runner);

    await expect(
      createAgentRun({
        query: "查库存",
        rfcName: "BAPI_MATERIAL_AVAILABILITY"
      })
    ).rejects.toThrow("Raw RFC execution is not allowed");
    expect(runner).not.toHaveBeenCalled();
  });

  it("keeps a complete Action pending until external human approval", async () => {
    const runner = vi.fn(async () => ({
      status: "awaiting_approval",
      responseText: "请确认采购申请参数后批准或拒绝。",
      callPlan: {
        agentTraceId: "agent-pr",
        capabilityId: "MM.PR.CreateDraft",
        kind: "Action",
        parameters: {
          material: "M001",
          plant: "1000",
          quantity: "10",
          unit: "EA",
          delivery_date: "2026-08-01",
          purchasing_group: "601"
        },
        validationPolicy: "validate_before_execute",
        createdBy: "agent",
        requiresApproval: true
      },
      validationResult: {
        traceId: "gw-validate-pr",
        capabilityId: "MM.PR.CreateDraft",
        success: true,
        errorType: "NONE",
        messages: []
      },
      approvalRecord: {
        approvalId: "appr-pr",
        capabilityId: "MM.PR.CreateDraft",
        parameterSnapshotHash: "sha256:approved",
        parameters: { material: "M001", plant: "1000" },
        approver: "user",
        approvedAt: "2026-07-17T10:00:00Z",
        expiresAt: "2026-07-17T10:10:00Z",
        status: "pending"
      },
      gatewayTraceId: "gw-validate-pr"
    }));
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "创建采购申请" });
    const events = await getAgentRunEvents(run.runId);

    expect(events.some((event) => event.type === "gateway_execute_started")).toBe(false);
    expect(events.some((event) => event.type === "run_failed")).toBe(false);
    expect(events.some((event) => event.type === "run_completed")).toBe(false);
    expect(events.slice(-2).map((event) => [event.type, event.state, event.hitlState])).toEqual([
      ["approval_state_changed", "awaiting_approval", "approval_required"],
      ["approval_state_changed", "awaiting_approval", "awaiting_human_approval"]
    ]);
  });

  it("continues the server-owned pending context exactly once after approval", async () => {
    const pendingOutcome = {
      status: "awaiting_approval",
      callPlan: {
        agentTraceId: "agent-pr",
        capabilityId: "MM.PR.CreateDraft",
        kind: "Action",
        parameters: { material: "M001", plant: "1000" },
        validationPolicy: "validate_before_execute",
        createdBy: "agent",
        requiresApproval: true
      },
      validationResult: {
        traceId: "gw-validate-pr",
        capabilityId: "MM.PR.CreateDraft",
        success: true,
        errorType: "NONE",
        messages: []
      },
      approvalRecord: {
        approvalId: "appr-pr",
        capabilityId: "MM.PR.CreateDraft",
        parameterSnapshotHash: "sha256:approved",
        parameters: { material: "M001", plant: "1000" },
        approver: "user",
        approvedAt: "2026-07-17T10:00:00Z",
        expiresAt: "2026-07-17T10:10:00Z",
        status: "pending"
      }
    };
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "success",
        responseText: "采购申请创建成功，PR 号：10137471",
        callPlan: pendingOutcome.callPlan,
        validationResult: pendingOutcome.validationResult,
        executionResult: {
          traceId: "gw-execute-pr",
          capabilityId: "MM.PR.CreateDraft",
          success: true,
          returnMessages: [],
          data: { prNumber: "10137471", commitStatus: "committed" },
          durationMs: 10,
          errorType: "NONE"
        },
        approvalRecord: { ...pendingOutcome.approvalRecord, status: "executed" }
      });
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "创建采购申请" });
    await decideAgentRunApproval(run.runId, "approve");

    expect(runner).toHaveBeenNthCalledWith(2, {
      query: "创建采购申请",
      gatewayUrl: "http://127.0.0.1:8080",
      intentMode: "hybrid",
      continuation: {
        decision: "approve",
        callPlan: pendingOutcome.callPlan,
        validationResult: pendingOutcome.validationResult,
        approvalRecord: pendingOutcome.approvalRecord
      }
    });
    const events = await getAgentRunEvents(run.runId);
    expect(events.some((event) => event.type === "gateway_execute_completed")).toBe(true);
    expect(events.at(-1)?.state).toBe("completed");

    await expect(decideAgentRunApproval(run.runId, "approve")).rejects.toThrow("already decided");
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("rejects a pending Action without emitting Gateway execute events", async () => {
    const pendingOutcome = {
      status: "awaiting_approval",
      callPlan: {
        agentTraceId: "agent-pr",
        capabilityId: "MM.PR.CreateDraft",
        kind: "Action",
        parameters: { material: "M001", plant: "1000" },
        validationPolicy: "validate_before_execute",
        createdBy: "agent",
        requiresApproval: true
      },
      validationResult: {
        traceId: "gw-validate-pr",
        capabilityId: "MM.PR.CreateDraft",
        success: true,
        errorType: "NONE",
        messages: []
      },
      approvalRecord: {
        approvalId: "appr-pr",
        capabilityId: "MM.PR.CreateDraft",
        parameterSnapshotHash: "sha256:approved",
        parameters: { material: "M001", plant: "1000" },
        approver: "user",
        approvedAt: "2026-07-17T10:00:00Z",
        expiresAt: "2026-07-17T10:10:00Z",
        status: "pending"
      }
    };
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "rejected",
        responseText: "采购申请已拒绝，未执行 SAP 写入。",
        callPlan: pendingOutcome.callPlan,
        validationResult: pendingOutcome.validationResult,
        approvalRecord: { ...pendingOutcome.approvalRecord, status: "rejected" }
      });
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "创建采购申请" });
    await decideAgentRunApproval(run.runId, "reject");
    const events = await getAgentRunEvents(run.runId);

    expect(events.some((event) => event.type === "gateway_execute_started")).toBe(false);
    expect(events.at(-1)?.hitlState).toBe("rejected");
  });

  it("does not mark a failed pending continuation as approved", async () => {
    const pendingOutcome = {
      status: "awaiting_approval",
      callPlan: {
        agentTraceId: "agent-pr",
        capabilityId: "MM.PR.CreateDraft",
        kind: "Action",
        parameters: { material: "M001", plant: "1000" }
      },
      validationResult: {
        traceId: "gw-validate-pr",
        capabilityId: "MM.PR.CreateDraft",
        success: true,
        errorType: "NONE",
        messages: []
      },
      approvalRecord: {
        approvalId: "appr-pr",
        capabilityId: "MM.PR.CreateDraft",
        parameterSnapshotHash: "sha256:approved",
        parameters: { material: "M001", plant: "1000" },
        approver: "user",
        approvedAt: "2026-07-17T10:00:00Z",
        expiresAt: "2026-07-17T10:10:00Z",
        status: "pending"
      }
    };
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "failure",
        responseText: "审批参数快照与 CallPlan 不一致。",
        errorType: "APPROVAL_VERSION_MISMATCH",
        callPlan: pendingOutcome.callPlan,
        validationResult: pendingOutcome.validationResult,
        approvalRecord: pendingOutcome.approvalRecord
      });
    setAgentRunnerForTests(runner);

    const run = await createAgentRun({ query: "创建采购申请" });
    await decideAgentRunApproval(run.runId, "approve");
    const events = await getAgentRunEvents(run.runId);

    expect(events.some((event) => event.hitlState === "approved")).toBe(false);
    expect(events.at(-1)?.type).toBe("run_failed");
  });

  it("keeps run events readable after route modules are loaded separately", async () => {
    const firstModule = await import("../../src/runtime/agent-runtime-adapter");
    firstModule.resetAgentRunsForTests();
    firstModule.setAgentRunnerForTests(
      vi.fn(async () => ({
        status: "clarification",
        responseText: "请补充工厂编码。"
      }))
    );

    const run = await firstModule.createAgentRun({ query: "查库存" });

    vi.resetModules();
    const secondModule = await import("../../src/runtime/agent-runtime-adapter");
    const events = await secondModule.getAgentRunEvents(run.runId);

    expect(events.map((event) => event.type)).toEqual([
      "run_started",
      "intent_parsed",
      "narrative_created",
      "run_completed"
    ]);
    secondModule.resetAgentRunsForTests();
    secondModule.setAgentRunnerForTests(null);
  });
});

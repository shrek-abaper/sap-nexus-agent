import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createAgentRun,
  confirmAgentRunBatch,
  decideAgentRunApproval,
  getAgentRunEvents,
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";
import { PLACEHOLDER_PRINCIPAL } from "../../src/runtime/principal/types";

describe("agent runtime adapter", () => {
  beforeEach(() => {
    resetAgentRunsForTests();
    resetAgentSessionsForTests();
  });

  afterEach(() => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
    resetAgentSessionsForTests();
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

    const run = await createAgentRun({ query: "MAT-LIVE 在 1000 还有多少可用库存？", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);

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
        rfcName: "BAPI_MATERIAL_AVAILABILITY",
        principal: PLACEHOLDER_PRINCIPAL
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

    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);

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

    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await decideAgentRunApproval(run.runId, "approve", PLACEHOLDER_PRINCIPAL);

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
    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);
    expect(events.some((event) => event.type === "gateway_execute_completed")).toBe(true);
    expect(events.at(-1)?.state).toBe("completed");

    await expect(decideAgentRunApproval(run.runId, "approve", PLACEHOLDER_PRINCIPAL)).rejects.toThrow("already decided");
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

    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await decideAgentRunApproval(run.runId, "reject", PLACEHOLDER_PRINCIPAL);
    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);

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

    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await decideAgentRunApproval(run.runId, "approve", PLACEHOLDER_PRINCIPAL);
    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);

    expect(events.some((event) => event.hitlState === "approved")).toBe(false);
    expect(events.at(-1)?.type).toBe("run_failed");
  });

  it("keeps run events readable after route modules are loaded separately", async () => {
    const firstModule = await import("../../src/runtime/agent-runtime-adapter");
    firstModule.resetAgentRunsForTests();
    firstModule.resetAgentSessionsForTests();
    firstModule.setAgentRunnerForTests(
      vi.fn(async () => ({
        status: "clarification",
        responseText: "请补充工厂编码。"
      }))
    );

    const run = await firstModule.createAgentRun({ query: "查库存", principal: PLACEHOLDER_PRINCIPAL });

    vi.resetModules();
    const secondModule = await import("../../src/runtime/agent-runtime-adapter");
    const events = await secondModule.getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);

    expect(events.map((event) => event.type)).toEqual([
      "run_started",
      "intent_parsed",
      "narrative_created",
      "run_completed"
    ]);
    secondModule.resetAgentRunsForTests();
    secondModule.resetAgentSessionsForTests();
    secondModule.setAgentRunnerForTests(null);
  });

  it("passes conversation context to runner when conversationId is provided", async () => {
    const runner = vi.fn(async (_input: any) => ({
      status: "clarification",
      responseText: "请提供工厂。",
      missingParameters: ["plant"],
      matchDecision: {
        decisionType: "CLARIFY",
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA2" },
        missingParameters: ["plant"]
      },
      lastContext: {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA2" },
        missingParameters: ["plant"],
        decisionType: "CLARIFY" as const
      }
    }));
    setAgentRunnerForTests(runner);

    // First run: fresh session, no prior lastContext -> context undefined
    await createAgentRun({ query: "查库存 DEMOA2", conversationId: "conv-1", principal: PLACEHOLDER_PRINCIPAL });
    // Second run: same conversationId, should inherit lastContext from first outcome
    await createAgentRun({ query: "1000", conversationId: "conv-1", principal: PLACEHOLDER_PRINCIPAL });

    expect(runner.mock.calls[0][0].context).toBeUndefined();
    const secondCall = runner.mock.calls[1][0];
    expect(secondCall.context).toBeDefined();
    expect(secondCall.context.lastContext.capabilityId).toBe("MM.Inventory.GetAvailability");
    expect(secondCall.context.lastContext.decisionType).toBe("CLARIFY");
    expect(secondCall.context.lastContext.missingParameters).toEqual(["plant"]);
    expect(secondCall.context.lastContext.parameters).toEqual({ material: "DEMOA2" });
  });

  it("rejects new query when approval is pending on the same conversation", async () => {
    const runner = vi.fn(async () => ({
      status: "awaiting_approval",
      responseText: "等待审批",
      callPlan: { capabilityId: "MM.PR.CreateDraft", kind: "Action", parameters: {} },
      validationResult: { success: true, traceId: "t", capabilityId: "MM.PR.CreateDraft" },
      approvalRecord: { approvalId: "a1", capabilityId: "MM.PR.CreateDraft", status: "pending" },
      matchDecision: { decisionType: "SELECT", capabilityId: "MM.PR.CreateDraft" },
      lastContext: null
    }));
    setAgentRunnerForTests(runner);

    await createAgentRun({ query: "建PR 物料X", conversationId: "conv-2", principal: PLACEHOLDER_PRINCIPAL });
    // Second call same conversationId: approval pending, must reject without invoking runner
    await expect(
      createAgentRun({ query: "再查一个", conversationId: "conv-2", principal: PLACEHOLDER_PRINCIPAL })
    ).rejects.toThrow(/审批/);
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("allows new query on same conversation after pending approval is decided", async () => {
    // Concern 1: decideAgentRunApproval (approve/reject) must clear the Q2
    // pending-approval block so the next query on the same conversation is
    // not rejected. The run record is the source of truth: once
    // record.decision is set, the conversation may accept new input.
    const pendingOutcome = {
      status: "awaiting_approval",
      responseText: "等待审批",
      callPlan: { capabilityId: "MM.PR.CreateDraft", kind: "Action", parameters: { material: "X" } },
      validationResult: { success: true, traceId: "t1", capabilityId: "MM.PR.CreateDraft" },
      approvalRecord: { approvalId: "a1", capabilityId: "MM.PR.CreateDraft", status: "pending" },
      lastContext: null
    };
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "success",
        responseText: "采购申请已创建。",
        callPlan: pendingOutcome.callPlan,
        executionResult: { traceId: "t2", capabilityId: "MM.PR.CreateDraft", success: true },
        approvalRecord: { ...pendingOutcome.approvalRecord, status: "executed" },
        lastContext: null
      })
      .mockResolvedValueOnce({ status: "success", responseText: "完成", lastContext: null });
    setAgentRunnerForTests(runner);

    const run1 = await createAgentRun({ query: "建PR 物料X", conversationId: "conv-decided", principal: PLACEHOLDER_PRINCIPAL });
    await decideAgentRunApproval(run1.runId, "approve", PLACEHOLDER_PRINCIPAL);

    // After approval is decided, a new query on the same conversation must
    // NOT be rejected by Q2 and must invoke the runner.
    const run2 = await createAgentRun({ query: "再查一个", conversationId: "conv-decided", principal: PLACEHOLDER_PRINCIPAL });
    expect(run2.runId).not.toBe(run1.runId);
    expect(runner).toHaveBeenCalledTimes(3);
  });

  it("clears session lastContext when outcome returns null lastContext", async () => {
    const runner = vi.fn(async (_input: any) => {
      const count = runner.mock.calls.length;
      if (count === 1) {
        return {
          status: "clarification",
          responseText: "请提供工厂。",
          lastContext: {
            capabilityId: "MM.Inventory.GetAvailability",
            parameters: { material: "X" },
            missingParameters: ["plant"],
            decisionType: "CLARIFY" as const
          }
        };
      }
      if (count === 2) {
        return { status: "failure", responseText: "无匹配能力。", lastContext: null };
      }
      return { status: "success", responseText: "完成", lastContext: null };
    });
    setAgentRunnerForTests(runner);

    await createAgentRun({ query: "查库存", conversationId: "conv-clear", principal: PLACEHOLDER_PRINCIPAL });
    await createAgentRun({ query: "再查", conversationId: "conv-clear", principal: PLACEHOLDER_PRINCIPAL });
    await createAgentRun({ query: "第三次", conversationId: "conv-clear", principal: PLACEHOLDER_PRINCIPAL });

    // Second call inherited lastContext from first run
    expect(runner.mock.calls[1][0].context?.lastContext?.capabilityId).toBe("MM.Inventory.GetAvailability");
    // Third call: second run returned null lastContext, session cleared -> no context
    expect(runner.mock.calls[2][0].context).toBeUndefined();
  });

  it("caps conversation history to last 6 entries (3 turns) in context", async () => {
    // Concern 3: Python llm_intent.py uses `context.history[-6:]` (近 3 轮 =
    // 6 条 Turn). Frontend buildContext must align to slice(-6) so both
    // sides feed the LLM the same window.
    const runner = vi.fn(async (_input: any) => ({
      status: "clarification",
      responseText: "请补充。",
      lastContext: {
        capabilityId: "C",
        parameters: {},
        missingParameters: ["x"],
        decisionType: "CLARIFY" as const
      }
    }));
    setAgentRunnerForTests(runner);

    for (let i = 0; i < 5; i++) {
      await createAgentRun({ query: `q${i}`, conversationId: "conv-hist", principal: PLACEHOLDER_PRINCIPAL });
    }

    // 5th run's context is built from session history after 4 completed runs
    // (8 entries). slice(-6) yields the last 3 turns = [q1, asst, q2, asst, q3, asst].
    const lastCall = runner.mock.calls[4][0];
    expect(lastCall.context.history).toHaveLength(6);
    expect(
      lastCall.context.history.map((t: { role: string; content: string }) => ({ role: t.role, content: t.content }))
    ).toEqual([
      { role: "user", content: "q1" },
      { role: "assistant", content: "请补充。" },
      { role: "user", content: "q2" },
      { role: "assistant", content: "请补充。" },
      { role: "user", content: "q3" },
      { role: "assistant", content: "请补充。" }
    ]);
  });

  it("resetAgentSessionsForTests clears session state", async () => {
    const runner = vi.fn(async (_input: any) => ({
      status: "clarification",
      responseText: "请补充。",
      lastContext: {
        capabilityId: "C",
        parameters: {},
        missingParameters: ["x"],
        decisionType: "CLARIFY" as const
      }
    }));
    setAgentRunnerForTests(runner);
    await createAgentRun({ query: "q0", conversationId: "conv-reset", principal: PLACEHOLDER_PRINCIPAL });
    resetAgentSessionsForTests();
    await createAgentRun({ query: "q1", conversationId: "conv-reset", principal: PLACEHOLDER_PRINCIPAL });

    expect(runner.mock.calls[1][0].context).toBeUndefined();
  });

  it("does not pass context when conversationId is absent", async () => {
    const runner = vi.fn(async (_input: any) => ({ status: "success", responseText: "done" }));
    setAgentRunnerForTests(runner);
    await createAgentRun({ query: "查库存", principal: PLACEHOLDER_PRINCIPAL });

    expect(runner.mock.calls[0][0].context).toBeUndefined();
  });

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

    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存", principal: PLACEHOLDER_PRINCIPAL });

    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);
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

    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存", principal: PLACEHOLDER_PRINCIPAL });
    await confirmAgentRunBatch(run.runId, PLACEHOLDER_PRINCIPAL);

    expect(runner).toHaveBeenCalledTimes(2);
    const batchCall = runner.mock.calls[1][0];
    expect(batchCall.continuation).toEqual({
      type: "batch",
      callPlan: pendingOutcome.callPlan,
      combinations: pendingOutcome.combinations
    });
    const events = await getAgentRunEvents(run.runId, PLACEHOLDER_PRINCIPAL);
    expect(events.some((e) => e.type === "run_completed")).toBe(true);
  });
});

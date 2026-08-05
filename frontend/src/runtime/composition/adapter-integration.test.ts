import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  createAgentRun,
  decideAgentRunApproval,
  getAgentRunEvents,
  setAgentRunnerForTests,
  setCompositionGatewayForTests,
  setDurableStoresForTests,
  setPlanActionGatewayForTests,
} from "../agent-runtime-adapter";
import type { ActionGateway, ActionGatewayRequest } from "../action-governance/action-governance";
import { JsonlConversationStore } from "../durable/jsonl-conversation-store";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { WorkbenchOutcome } from "../durable/types";
import { FakeGateway } from "../plan-executor/fake-gateway";
import { PLACEHOLDER_PRINCIPAL } from "../principal/types";

const SNAPSHOT_ID = "snapshot-adapter-l2";

function escalation(withAction = false): WorkbenchOutcome {
  const bindings = [
    { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "MAT-1" } },
    { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "P1" } },
  ];
  return {
    status: "match_decision",
    responseText: "multi-read plan authored",
    matchDecision: {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: { registrySnapshotId: SNAPSHOT_ID },
    },
    dryRun: {
      gaps: [],
      governanceFlags: [],
      planGraph: {
        planGraphVersion: 2,
        planId: "plan-adapter-l2",
        goalId: "goal-adapter-l2",
        executionMode: "advisory",
        snapshotId: SNAPSHOT_ID,
        nodes: [
          {
            nodeId: "node.inventory",
            capabilityId: "MM.Inventory.GetAvailability",
            parameterBindings: bindings,
            producesFactTypes: ["InventoryAvailability"],
            governance: { requiresApproval: false },
          },
          {
            nodeId: "node.purchase-orders",
            capabilityId: "MM.PurchaseOrder.GetList",
            parameterBindings: bindings,
            producesFactTypes: ["PurchaseOrder"],
            governance: { requiresApproval: false },
          },
          ...(withAction ? [{
            nodeId: "node.action",
            capabilityId: "MM.PR.CreateDraft",
            parameterBindings: [
              ...bindings,
              { parameterName: "quantity", source: { kind: "literal", semanticType: "Quantity", value: "10" } },
              { parameterName: "unit", source: { kind: "literal", semanticType: "Unit", value: "EA" } },
              { parameterName: "delivery_date", source: { kind: "literal", semanticType: "Date", value: "2026-08-15" } },
              { parameterName: "purchasing_group", source: { kind: "literal", semanticType: "PurchasingGroup", value: "601" } },
            ],
            producesFactTypes: [],
            governance: { requiresApproval: true },
          }] : []),
        ],
        edges: [],
        topologicalOrder: ["node.inventory", "node.purchase-orders", ...(withAction ? ["node.action"] : [])],
        goalOutputs: [],
        readPartition: ["node.inventory", "node.purchase-orders"],
        actionPartition: withAction ? ["node.action"] : [],
        projectionRef: [],
        ruleSetRefs: [],
      },
    },
  };
}

async function waitForTerminal(runId: string): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < 5_000) {
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    if (events.at(-1)?.type === "run_completed" || events.at(-1)?.type === "run_failed"
      || events.at(-1)?.state === "awaiting_approval") return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("composition run did not settle");
}

class FakeActionGateway implements ActionGateway {
  approveCalls = 0;
  executeCalls = 0;
  async approve(): Promise<void> { this.approveCalls += 1; }
  async execute(_request: ActionGatewayRequest) {
    this.executeCalls += 1;
    return { success: true, traceId: "gateway-action", data: { prNumber: "10000001" } };
  }
}

describe("agent runtime composition integration", () => {
  let dir: string;
  let gateway: FakeGateway;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "adapter-composition-"));
    setDurableStoresForTests(new JsonlRunStore(dir), new JsonlConversationStore(dir));
    setAgentRunnerForTests(async () => escalation());
    gateway = new FakeGateway();
    const dataAsOf = "2026-08-05T01:00:00.000Z";
    gateway.setExecuteResult("MM.Inventory.GetAvailability", {
      success: true,
      traceId: "gateway-inventory",
      data: { availableQuantity: 7, unit: "EA", material: "MAT-1", plant: "P1", dataAsOf },
    });
    gateway.setExecuteResult("MM.PurchaseOrder.GetList", {
      success: true,
      traceId: "gateway-po",
      data: {
        purchaseOrders: [{
          purchaseOrder: "4500001",
          purchaseOrderItem: "10",
          orderQuantity: 5,
          purchaseOrderUnit: "EA",
          material: "MAT-1",
          plant: "P1",
        }],
        dataAsOf,
      },
    });
    setCompositionGatewayForTests(gateway);
  });

  afterEach(() => {
    setAgentRunnerForTests(null);
    setCompositionGatewayForTests(null);
    setPlanActionGatewayForTests(null);
    rmSync(dir, { recursive: true, force: true });
  });

  it("persists the production L2 chain and reads it without re-executing", async () => {
    const { runId } = await createAgentRun({
      query: "summarize inventory and purchase-order supply",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    const first = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(first.map((event) => event.type)).toEqual(expect.arrayContaining([
      "plan_compiled",
      "projection_completed",
      "recommendation_completed",
      "narrative_completed",
      "run_completed",
    ]));
    expect(gateway.executeCalls).toHaveLength(2);

    expect(await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)).toEqual(first);
    expect(gateway.executeCalls).toHaveLength(2);
  });

  it("keeps the L3 Action pending until exact approval and executes duplicate continuation once", async () => {
    const actionGateway = new FakeActionGateway();
    setPlanActionGatewayForTests(actionGateway);
    setAgentRunnerForTests(async () => escalation(true));
    const { runId } = await createAgentRun({
      query: "summarize supply and propose a PR for the shortage",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    const pendingEvents = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(pendingEvents.at(-1)?.state).toBe("awaiting_approval");
    expect(actionGateway.executeCalls).toBe(0);
    const approvalEvent = pendingEvents.slice().reverse()
      .find((event) => event.type === "approval_updated");
    const approvalPayload = approvalEvent?.artifact?.payload as Record<string, unknown>;
    const approvalData = approvalPayload?.data as Record<string, unknown>;
    const approvalId = String(approvalData.approvalId);

    await decideAgentRunApproval(runId, approvalId, "approve", PLACEHOLDER_PRINCIPAL);
    await waitForTerminal(runId);
    await decideAgentRunApproval(runId, approvalId, "approve", PLACEHOLDER_PRINCIPAL);

    expect(actionGateway.approveCalls).toBe(1);
    expect(actionGateway.executeCalls).toBe(1);
    expect((await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)).at(-1)?.type)
      .toBe("run_completed");
  });
});

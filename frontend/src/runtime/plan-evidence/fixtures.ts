import type { AgentRunSnapshot } from "../run-event-schema";
import {
  projectPlanEvidenceEvents,
  type PlanEvidenceBundle,
  type PlanEvidenceObject,
} from "./event-projector";

const snapshotId = "snapshot-fixture-1";

function object(
  ref: string,
  kind: PlanEvidenceObject["kind"],
  payload: PlanEvidenceObject["payload"],
  evidenceRefs: string[] = [],
): PlanEvidenceObject {
  return { ref, kind, snapshotId, payload, evidenceRefs };
}

function snapshot(runId: string, objects: PlanEvidenceObject[]): AgentRunSnapshot {
  const bundle: PlanEvidenceBundle = {
    runId,
    traceId: `trace-${runId}`,
    snapshotId,
    startSequence: 1,
    objects,
  };
  return {
    runId,
    state: "completed",
    hitlState: "approval_not_required",
    events: projectPlanEvidenceEvents(bundle),
    replayIntegrity: { status: "consistent" },
  };
}

const multiReadObjects = (): PlanEvidenceObject[] => [
  object("intent-supply", "intent", { goal: "物料库存与采购订单供给概览" }),
  object("capability-inventory", "capability", { capabilityId: "MM.Inventory.GetAvailability" }),
  object("capability-po", "capability", { capabilityId: "MM.PurchaseOrder.GetList" }),
  object("plan-supply", "plan", {
    nodes: ["inventory", "purchase-orders"],
    edges: [],
    topologicalOrder: ["inventory", "purchase-orders"],
    readPartition: ["inventory", "purchase-orders"],
    actionPartition: [],
  }, ["node-inventory", "node-po"]),
  object("node-inventory", "node", {
    nodeId: "inventory",
    state: "SUCCEEDED",
    attempt: 1,
    resultRef: "fact-inventory",
    safeCallPlan: { capabilityId: "MM.Inventory.GetAvailability", parameters: { material: "DEMOA1", plant: "1000" } },
    safeResult: { factTypeId: "InventoryAvailability", status: "succeeded" },
    traceSummary: { traceId: "trace-run-multi-read", span: "inventory" },
  }, ["fact-inventory"]),
  object("node-po", "node", {
    nodeId: "purchase-orders",
    state: "SUCCEEDED",
    attempt: 1,
    resultRef: "fact-po",
    safeCallPlan: { capabilityId: "MM.PurchaseOrder.GetList", parameters: { material: "DEMOA1", plant: "1000" } },
    safeResult: { factTypeId: "PurchaseOrderSupply", status: "succeeded" },
    traceSummary: { traceId: "trace-run-multi-read", span: "purchase-orders" },
  }, ["fact-po"]),
  object("fact-inventory", "fact", { factTypeId: "InventoryAvailability", availableQuantity: 7, unit: "EA", traceRef: "trace-run-multi-read" }),
  object("fact-po", "fact", { factTypeId: "PurchaseOrderSupply", orderQuantity: 5, unit: "EA", traceRef: "trace-run-multi-read" }),
  object("projection-supply", "projection", {
    projectionId: "MaterialSupplySnapshot@1",
    completeness: "complete",
    freshness: "fresh",
    lineage: ["fact-inventory", "fact-po"],
    limitations: [],
  }, ["fact-inventory", "fact-po"]),
  object("recommendation-supply", "recommendation", {
    status: "NO_ACTION",
    rules: ["material-supply-v1"],
    limitations: [],
  }, ["projection-supply"]),
  object("narrative-supply", "narrative", {
    summary: "库存与采购订单供给证据已汇总。",
    claims: [{
      claimId: "claim-supply-1",
      text: "当前视图包含库存与采购订单两类供给事实。",
      evidenceRefs: ["fact-inventory", "fact-po"],
    }],
    limitations: [],
  }, ["fact-inventory", "fact-po", "projection-supply", "recommendation-supply"]),
];

const partialObjects = (): PlanEvidenceObject[] => [
  ...multiReadObjects().filter((entry) => !["node-po", "fact-po", "projection-supply", "recommendation-supply", "narrative-supply"].includes(entry.ref)),
  object("node-po", "node", {
    nodeId: "purchase-orders",
    state: "TIMED_OUT",
    attempt: 1,
    resultRef: null,
    safeCallPlan: { capabilityId: "MM.PurchaseOrder.GetList", parameters: { material: "DEMOA1", plant: "1000" } },
    safeResult: { status: "timed_out" },
    traceSummary: { traceId: "trace-run-partial", span: "purchase-orders" },
  }),
  object("projection-supply", "projection", {
    projectionId: "MaterialSupplySnapshot@1",
    completeness: "partial",
    freshness: "mixed",
    lineage: ["fact-inventory"],
    missingFacts: ["PurchaseOrderSupply"],
    limitations: [{ kind: "missing_optional", detail: "采购订单节点超时，供给快照不完整" }],
  }, ["fact-inventory"]),
  object("recommendation-supply", "recommendation", {
    status: "INSUFFICIENT_INPUT",
    limitations: [{ code: "INSUFFICIENT_INPUT", detail: "采购订单节点超时，供给快照不完整", sourceRefs: ["node-po"] }],
  }, ["projection-supply"]),
  object("narrative-supply", "narrative", {
    summary: "仅获得库存事实，采购订单供给未知。",
    claims: [{ claimId: "claim-partial-1", text: "库存节点已完成。", evidenceRefs: ["fact-inventory"] }],
    limitations: [{ code: "missing_purchase_orders", detail: "采购订单节点超时，供给快照不完整", evidenceRefs: ["node-po"] }],
  }, ["fact-inventory", "projection-supply"]),
];

const proposalObjects = (): PlanEvidenceObject[] => [
  ...multiReadObjects(),
  object("proposal-pr", "proposal", {
    status: "pending_approval",
    capabilityId: "MM.PR.CreateDraft",
    parameters: { material: "DEMOA1", plant: "1000", quantity: "3", unit: "EA" },
    parameterSources: {
      material: [{ kind: "fact", ref: "fact-inventory", field: "material" }],
      plant: [{ kind: "fact", ref: "fact-inventory", field: "plant" }],
      quantity: [{ kind: "rule", ref: "material-supply-v1" }],
      unit: [{ kind: "fact", ref: "fact-inventory", field: "unit" }],
    },
    factsUsed: ["fact-inventory", "fact-po"],
    ruleSetRefs: ["material-supply-v1"],
    proposalHash: "proposal-hash-1",
  }, ["fact-inventory", "fact-po", "recommendation-supply"]),
];

function pendingApprovalSnapshot(): AgentRunSnapshot {
  const value = snapshot("run-pending-approval", [
    ...proposalObjects(),
    object("approval-fixture-1", "approval", {
      approvalId: "approval-fixture-1",
      planId: "plan-supply",
      actionNodeId: "action-pr",
      snapshotId,
      status: "pending",
      capabilityId: "MM.PR.CreateDraft",
      capabilityVersion: "2.1.0",
      principalId: "local-user-0001",
      confirmingPrincipalId: null,
      parameterSnapshotHash: "sha256:parameters",
      factSetHash: "sha256:facts",
      projectionHash: "sha256:projection",
      ruleSetHash: "sha256:rules",
      proposalHash: "proposal-hash-1",
      subjectHash: "sha256:subject",
      parameters: { material: "DEMOA1", plant: "1000", quantity: "3", unit: "EA" },
      separationOfDutyResult: "not_applicable",
      expiresAt: "2026-08-05T08:10:00.000Z",
      revokedAt: null,
    }, ["proposal-pr", "projection-supply", "fact-inventory", "fact-po"]),
  ]);
  return {
    ...value,
    state: "awaiting_approval",
    hitlState: "awaiting_human_approval",
  };
}

const singleCapability: AgentRunSnapshot = {
  runId: "run-single",
  state: "completed",
  hitlState: "approval_not_required",
  replayIntegrity: { status: "consistent" },
  events: [
    {
      runId: "run-single",
      sequence: 1,
      timestamp: "2026-08-05T00:00:00.000Z",
      type: "intent_parsed",
      state: "intent_parsed",
      artifact: { label: "IntentParseResult", kind: "intent", payload: { query: "查询库存" } },
    },
    {
      runId: "run-single",
      sequence: 2,
      timestamp: "2026-08-05T00:00:01.000Z",
      type: "capability_selected",
      state: "capability_selected",
      artifact: { label: "CapabilityCard", kind: "capability", payload: { capabilityId: "MM.Inventory.GetAvailability" } },
    },
    {
      runId: "run-single",
      sequence: 3,
      timestamp: "2026-08-05T00:00:02.000Z",
      type: "gateway_execute_completed",
      state: "executing",
      artifact: { label: "ExecutionResult", kind: "execution-result", payload: { status: "succeeded", rowCount: 1 } },
    },
    {
      runId: "run-single",
      sequence: 4,
      timestamp: "2026-08-05T00:00:03.000Z",
      type: "reasoning_fact_created",
      state: "fact_created",
      artifact: { label: "ReasoningFact", kind: "reasoning-fact", payload: { availableQuantity: 7, unit: "EA" } },
    },
    {
      runId: "run-single",
      traceId: "trace-run-single",
      sequence: 5,
      timestamp: "2026-08-05T00:00:04.000Z",
      type: "trace_linked",
      state: "trace_linked",
      artifact: { label: "Trace Summary", kind: "trace", payload: { traceId: "trace-run-single", status: "linked" } },
    },
  ],
};

export const planEvidenceFixtures = {
  singleCapability,
  multiRead: snapshot("run-multi-read", multiReadObjects()),
  partialFailure: snapshot("run-partial", partialObjects()),
  readToWriteProposal: snapshot("run-proposal", proposalObjects()),
  readToWritePendingApproval: pendingApprovalSnapshot(),
};

// frontend/src/runtime/plan-executor/plan-graph-v2-parser.ts
import type { PlanGraphV2, PlanNodeV2, PlanEdgeV2 } from "./types";

export function parsePlanGraphV2(value: unknown): PlanGraphV2 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const rec = value as Record<string, unknown>;
  if (rec.planGraphVersion !== 2) return null;
  if (!Array.isArray(rec.readPartition)) return null;
  if (!Array.isArray(rec.nodes)) return null;
  if (!Array.isArray(rec.edges)) return null;

  const nodes = rec.nodes.map(parseNode).filter((n): n is PlanNodeV2 => n !== null);
  const edges = rec.edges.map(parseEdge).filter((e): e is PlanEdgeV2 => e !== null);

  const planId = typeof rec.planId === "string" ? rec.planId : "";
  const goalId = typeof rec.goalId === "string" ? rec.goalId : "";
  const executionMode = typeof rec.executionMode === "string" ? rec.executionMode : "";
  const snapshotId = typeof rec.snapshotId === "string" ? rec.snapshotId : "";

  if (!planId && !goalId && nodes.length === 0) return null;

  return {
    planGraphVersion: 2,
    planId,
    goalId,
    executionMode,
    snapshotId,
    nodes,
    edges,
    topologicalOrder: Array.isArray(rec.topologicalOrder) ? rec.topologicalOrder as string[] : [],
    goalOutputs: Array.isArray(rec.goalOutputs) ? rec.goalOutputs as { factTypeId: string; producerNodeId: string }[] : [],
    readPartition: rec.readPartition as string[],
    actionPartition: Array.isArray(rec.actionPartition) ? rec.actionPartition as string[] : [],
    projectionRef: Array.isArray(rec.projectionRef) ? rec.projectionRef : [],
    ruleSetRefs: Array.isArray(rec.ruleSetRefs) ? rec.ruleSetRefs : [],
  };
}

function parseNode(raw: unknown): PlanNodeV2 | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const nodeId = typeof rec.nodeId === "string" ? rec.nodeId : "";
  const capabilityId = typeof rec.capabilityId === "string" ? rec.capabilityId : "";
  if (!nodeId || !capabilityId) return null;
  const bindings = Array.isArray(rec.parameterBindings) ? rec.parameterBindings : [];
  const governance = rec.governance ?? {};
  return {
    nodeId,
    capabilityId,
    parameterBindings: bindings as PlanNodeV2["parameterBindings"],
    producesFactTypes: Array.isArray(rec.producesFactTypes) ? rec.producesFactTypes as string[] : [],
    governance: { requiresApproval: Boolean((governance as Record<string, unknown>)?.requiresApproval) },
  };
}

function parseEdge(raw: unknown): PlanEdgeV2 | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const edgeId = typeof rec.edgeId === "string" ? rec.edgeId : "";
  const kind = rec.kind === "data" || rec.kind === "dependency" ? rec.kind : null;
  const fromNodeId = typeof rec.fromNodeId === "string" ? rec.fromNodeId : "";
  const toNodeId = typeof rec.toNodeId === "string" ? rec.toNodeId : "";
  if (!edgeId || !kind || !fromNodeId || !toNodeId) return null;
  return { edgeId, kind, fromNodeId, toNodeId, factTypeId: typeof rec.factTypeId === "string" ? rec.factTypeId : undefined };
}

export function validatePlanGraphV2(
  graph: PlanGraphV2,
  expectedSnapshotId: string
): { valid: boolean; error?: string } {
  if (!graph.snapshotId) {
    return { valid: false, error: "plan_graph missing snapshotId" };
  }
  if (graph.snapshotId !== expectedSnapshotId) {
    return { valid: false, error: `snapshot drift: plan_graph=${graph.snapshotId} != expected=${expectedSnapshotId}` };
  }
  if (graph.readPartition.length === 0) {
    return { valid: false, error: "readPartition is empty" };
  }
  for (const nodeId of graph.readPartition) {
    const node = graph.nodes.find((n) => n.nodeId === nodeId);
    if (!node) {
      return { valid: false, error: `readPartition node ${nodeId} not found in nodes` };
    }
  }
  return { valid: true };
}

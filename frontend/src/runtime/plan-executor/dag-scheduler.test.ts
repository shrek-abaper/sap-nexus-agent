// frontend/src/runtime/plan-executor/dag-scheduler.test.ts
import { describe, expect, it } from "vitest";
import type { PlanGraphV2, NodeLedgerEntry } from "./types";
import { NodeState } from "./types";
import { getDependencies, selectReadyNodes, getMaxConcurrency } from "./dag-scheduler";

function node(nodeId: string, capabilityId: string): PlanGraphV2["nodes"][0] {
  return { nodeId, capabilityId, parameterBindings: [], producesFactTypes: [], governance: { requiresApproval: false } };
}

const graph: PlanGraphV2 = {
  planGraphVersion: 2,
  planId: "p1",
  goalId: "g1",
  executionMode: "advisory",
  snapshotId: "snap-1",
  nodes: [node("A", "Cap.A"), node("B", "Cap.B"), node("C", "Cap.C")],
  edges: [
    { edgeId: "e1", kind: "dependency", fromNodeId: "A", toNodeId: "B" },
    { edgeId: "e2", kind: "dependency", fromNodeId: "A", toNodeId: "C" },
  ],
  topologicalOrder: ["A", "B", "C"],
  goalOutputs: [],
  readPartition: ["A", "B", "C"],
  actionPartition: [],
  projectionRef: [],
  ruleSetRefs: [],
};

function ledgerEntry(state: NodeState): NodeLedgerEntry {
  return { state, attempt: 0, inputHash: "", resultRef: null, traceSpan: null, updatedAt: "" };
}

describe("dag scheduler", () => {
  it("getDependencies returns prerequisite nodeIds for a dependent node", () => {
    expect(getDependencies(graph, "B")).toEqual(["A"]);
    expect(getDependencies(graph, "C")).toEqual(["A"]);
  });

  it("getDependencies returns empty for a node with no prerequisites", () => {
    expect(getDependencies(graph, "A")).toEqual([]);
  });

  it("selectReadyNodes returns nodes whose deps are all SUCCEEDED", () => {
    const ledger = { A: ledgerEntry(NodeState.SUCCEEDED) };
    expect(selectReadyNodes(graph, ledger).sort()).toEqual(["B", "C"]);
  });

  it("selectReadyNodes returns node with no deps", () => {
    const ledger = {};
    expect(selectReadyNodes(graph, ledger)).toEqual(["A"]);
  });

  it("selectReadyNodes excludes BLOCKED nodes (deps not SUCCEEDED)", () => {
    const ledger = { A: ledgerEntry(NodeState.READY) };
    const ready = selectReadyNodes(graph, ledger);
    expect(ready).toEqual(["A"]);
    expect(ready).not.toContain("B");
    expect(ready).not.toContain("C");
  });

  it("selectReadyNodes excludes already SUCCEEDED/FAILED/CANCELLED nodes", () => {
    const ledger = {
      A: ledgerEntry(NodeState.SUCCEEDED),
      B: ledgerEntry(NodeState.SUCCEEDED),
      C: ledgerEntry(NodeState.FAILED),
    };
    expect(selectReadyNodes(graph, ledger)).toEqual([]);
  });

  it("selectReadyNodes respects max concurrency cap", () => {
    const bigGraph: PlanGraphV2 = {
      ...graph,
      nodes: ["A", "B", "C", "D", "E", "F"].map((id) => node(id, `Cap.${id}`)),
      edges: [],
      topologicalOrder: ["A", "B", "C", "D", "E", "F"],
      readPartition: ["A", "B", "C", "D", "E", "F"],
    };
    const ledger = {};
    // 6 ready nodes, cap 4 -> only 4 returned
    expect(selectReadyNodes(bigGraph, ledger, 4)).toHaveLength(4);
  });

  it("getMaxConcurrency reads env var, defaults to 4", () => {
    const orig = process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY;
    delete process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY;
    expect(getMaxConcurrency()).toBe(4);
    process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY = "8";
    expect(getMaxConcurrency()).toBe(8);
    process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY = orig;
  });
});

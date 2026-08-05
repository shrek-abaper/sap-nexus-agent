import { describe, expect, it } from "vitest";
import { canonicalJson, sha256Hex } from "../durable/canonical-json";
import { computeOutputHash, normalizeFacts } from "./hash";
import type { ReasoningFact } from "./types";

function fact(overrides: Partial<ReasoningFact> = {}): ReasoningFact {
  return {
    factId: "fact-a",
    agentTraceId: "run-1",
    traceId: "trace-1",
    gatewayTraceId: "gateway-1",
    domain: "MM",
    businessObject: "InventoryStock",
    predicate: "availableQuantity",
    value: 7,
    unit: "EA",
    deterministic: true,
    confidence: 1,
    source: {
      nodeId: "node.inventory",
      capabilityId: "MM.Inventory.GetAvailability",
      factType: "InventoryAvailability",
    },
    evidence: [{ material: "MAT-1", plant: "P1" }],
    material: "MAT-1",
    plant: "P1",
    asOf: "2026-08-04T00:00:00Z",
    ...overrides,
  };
}

describe("projection output hash", () => {
  it("is order independent and changes with fact content, version, or snapshot", () => {
    const factA = fact();
    const factB = fact({
      factId: "fact-b",
      businessObject: "PurchaseOrderItem",
      predicate: "orderQuantity",
      value: 2,
      source: {
        nodeId: "node.po",
        capabilityId: "MM.PurchaseOrder.GetList",
        factType: "PurchaseOrder",
      },
    });

    expect(computeOutputHash([factB, factA], "1.0.0", "snap-1"))
      .toBe(computeOutputHash([factA, factB], "1.0.0", "snap-1"));
    expect(computeOutputHash([factA], "1.0.0", "snap-1"))
      .not.toBe(computeOutputHash([{ ...factA, value: 8 }], "1.0.0", "snap-1"));
    expect(computeOutputHash([factA], "1.0.0", "snap-1"))
      .not.toBe(computeOutputHash([factA], "1.0.1", "snap-1"));
    expect(computeOutputHash([factA], "1.0.0", "snap-1"))
      .not.toBe(computeOutputHash([factA], "1.0.0", "snap-2"));
  });

  it("normalizes facts with a code-unit comparator", () => {
    const lower = fact({ factId: "lower", businessObject: "a" });
    const upper = fact({ factId: "upper", businessObject: "Z" });

    expect(normalizeFacts([lower, upper])).toEqual([upper, lower]);
    expect(computeOutputHash([lower, upper], "1.0.0", "snap-1")).toBe(
      sha256Hex(canonicalJson([upper, lower]) + "1.0.0" + "snap-1"),
    );
  });
});

import { describe, expect, it } from "vitest";
import type { TraceableNodeFactRecord } from "./types";
import {
  FactBuilderRegistry,
  createMaterialSupplyFactBuilderRegistry,
} from "./fact-builder";

function record(
  overrides: Partial<TraceableNodeFactRecord> = {},
): TraceableNodeFactRecord {
  return {
    nodeId: "node.inventory",
    agentTraceId: "run-1",
    capabilityId: "MM.Inventory.GetAvailability",
    parameters: { material: "MAT-1", plant: "PLANT-1" },
    producesFactTypes: ["InventoryAvailability"],
    gatewayTraceId: "gw-inventory",
    executeData: {
      availableQuantity: 7,
      unit: "EA",
      dataAsOf: "2026-08-04T00:00:00Z",
    },
    nodeExecutedAt: "2026-08-04T00:00:01Z",
    ...overrides,
  };
}

describe("FactBuilderRegistry", () => {
  it("resolves registered builders and returns null for unknown capabilities", () => {
    const registry = createMaterialSupplyFactBuilderRegistry();

    expect(registry.resolve("MM.Inventory.GetAvailability")?.freshnessField).toBe("dataAsOf");
    expect(registry.resolve("MM.PurchaseOrder.GetList")?.freshnessField).toBe("dataAsOf");
    expect(registry.resolve("MM.Unknown.Read")).toBeNull();
  });

  it("rejects duplicate capability registration", () => {
    const registry = new FactBuilderRegistry();
    const builder = {
      capabilityId: "MM.Inventory.GetAvailability",
      build: () => [],
    };
    registry.register(builder);

    expect(() => registry.register(builder)).toThrowError(
      "fact builder already registered: MM.Inventory.GetAvailability",
    );
  });
});

describe("material supply fact builders", () => {
  it("builds inventory only from the capability whitelist when quantity is numeric", () => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve(
      "MM.Inventory.GetAvailability",
    );
    const facts = builder?.build(record({
      executeData: {
        availableQuantity: 7,
        unit: "EA",
        dataAsOf: "2026-08-04T00:00:00Z",
        rawPayload: "must-not-leak",
      },
    }));

    expect(facts).toEqual([
      expect.objectContaining({
        factId: "node.inventory:availableQuantity:0",
        agentTraceId: "run-1",
        traceId: "run-1",
        gatewayTraceId: "gw-inventory",
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
        material: "MAT-1",
        plant: "PLANT-1",
        asOf: "2026-08-04T00:00:00Z",
      }),
    ]);
    expect(JSON.stringify(facts)).not.toContain("must-not-leak");
    expect(builder?.build(record({ executeData: { availableQuantity: "7" } }))).toEqual([]);
  });

  it("flattens nested and flat purchase orders in deterministic business-key order", () => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve("MM.PurchaseOrder.GetList");
    const facts = builder?.build(record({
      nodeId: "node.po",
      capabilityId: "MM.PurchaseOrder.GetList",
      producesFactTypes: ["PurchaseOrder"],
      gatewayTraceId: "gw-po",
      executeData: {
        purchaseOrders: [
          {
            purchaseOrder: "4500002",
            supplier: "SUP-2",
            items: [
              { material: "MAT-2", plant: "P2", orderQuantity: 3, purchaseOrderUnit: "EA" },
              { material: "MAT-1", plant: "P1", orderQuantity: 4, purchaseOrderUnit: "KG" },
            ],
          },
          {
            purchaseOrder: "4500001",
            material: "MAT-0",
            plant: "P0",
            orderQuantity: 2,
            purchaseOrderUnit: "EA",
          },
        ],
        dataAsOf: "2026-08-04T00:00:00Z",
        rawPayload: "must-not-leak",
      },
    }));

    expect(facts?.map((fact) => fact.evidence[0]?.purchaseOrder)).toEqual([
      "4500001",
      "4500002",
      "4500002",
    ]);
    expect(facts?.map((fact) => fact.material)).toEqual(["MAT-0", "MAT-1", "MAT-2"]);
    expect(facts?.map((fact) => fact.factId)).toEqual([
      "node.po:purchaseOrderItem:0",
      "node.po:purchaseOrderItem:1",
      "node.po:purchaseOrderItem:2",
    ]);
    expect(JSON.stringify(facts)).not.toContain("must-not-leak");
  });

  it("normalizes finite decimal-string quantities without changing whitelisted evidence", () => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve("MM.PurchaseOrder.GetList");
    const facts = builder?.build(record({
      nodeId: "node.po",
      capabilityId: "MM.PurchaseOrder.GetList",
      producesFactTypes: ["PurchaseOrder"],
      executeData: {
        purchaseOrders: [
          { purchaseOrder: "4500001", purchaseOrderItem: "10", orderQuantity: "1.000" },
          { purchaseOrder: "4500001", purchaseOrderItem: "20", orderQuantity: Number.NaN },
          { purchaseOrder: "4500001", purchaseOrderItem: "30", orderQuantity: Number.POSITIVE_INFINITY },
          { purchaseOrder: "4500001", purchaseOrderItem: "40", orderQuantity: "not-a-decimal" },
        ],
      },
    }));

    expect(facts?.map((fact) => fact.value)).toEqual([1, null, null, null]);
    expect(facts?.map((fact) => fact.evidence[0]?.orderQuantity)).toEqual([
      "1.000",
      Number.NaN,
      Number.POSITIVE_INFINITY,
      "not-a-decimal",
    ]);
  });

  it("preserves an invalid item quantity instead of falling back to the header quantity", () => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve("MM.PurchaseOrder.GetList");
    const facts = builder?.build(record({
      nodeId: "node.po",
      capabilityId: "MM.PurchaseOrder.GetList",
      producesFactTypes: ["PurchaseOrder"],
      executeData: {
        purchaseOrders: [{
          purchaseOrder: "4500001",
          orderQuantity: 12,
          items: [{ purchaseOrderItem: "10", orderQuantity: "" }],
        }],
      },
    }));

    expect(facts).toHaveLength(1);
    expect(facts?.[0]?.value).toBeNull();
    expect(facts?.[0]?.evidence[0]?.orderQuantity).toBe("");
    expect(facts?.[0]?.evidence[0]?.orderQuantity).not.toBe("12");
  });

  it.each([
    { label: "malformed", dataAsOf: "not-a-timestamp" },
    { label: "timezone-less", dataAsOf: "2026-08-04T00:00:00" },
  ])("falls back to node execution time for $label freshness", ({ dataAsOf }) => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve(
      "MM.Inventory.GetAvailability",
    );
    const facts = builder?.build(record({
      executeData: { availableQuantity: 7, dataAsOf },
    }));

    expect(facts?.[0]?.asOf).toBe("2026-08-04T00:00:01Z");
  });

  it.each([
    "1900-02-29T00:00:00Z",
    "2025-02-29T00:00:00+08:00",
    "2026-02-30T00:00:00Z",
    "2026-00-01T00:00:00Z",
    "2026-13-01T00:00:00Z",
    "2026-01-00T00:00:00Z",
    "2026-01-01T24:00:00Z",
    "2026-01-01T00:60:00Z",
    "2026-01-01T00:00:60Z",
    "2026-01-01T00:00:00+24:00",
    "2026-01-01T00:00:00-23:60",
  ])("falls back for invalid ISO-8601 calendar freshness: %s", (dataAsOf) => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve(
      "MM.Inventory.GetAvailability",
    );
    const facts = builder?.build(record({
      executeData: { availableQuantity: 7, dataAsOf },
    }));

    expect(facts?.[0]?.asOf).toBe("2026-08-04T00:00:01Z");
  });

  it.each([
    "2000-02-29T23:59:59Z",
    "2024-02-29T23:59:59.123+08:30",
    "2024-02-29T23:59:59-23:59",
  ])("preserves valid leap-day and offset freshness: %s", (dataAsOf) => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve(
      "MM.Inventory.GetAvailability",
    );
    const facts = builder?.build(record({
      executeData: { availableQuantity: 7, dataAsOf },
    }));

    expect(facts?.[0]?.asOf).toBe(dataAsOf);
  });

  it("preserves purchase-order item identity in fact evidence", () => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve("MM.PurchaseOrder.GetList");
    const build = (purchaseOrderItem: string) => builder?.build(record({
      nodeId: "node.po",
      capabilityId: "MM.PurchaseOrder.GetList",
      producesFactTypes: ["PurchaseOrder"],
      executeData: {
        purchaseOrders: [{
          purchaseOrder: "4500001",
          purchaseOrderItem,
          material: "MAT-1",
          plant: "P1",
          orderQuantity: 1,
          purchaseOrderUnit: "EA",
        }],
      },
    }));

    expect(build("10")?.[0]?.evidence[0]?.purchaseOrderItem).toBe("10");
    expect(build("10")).not.toEqual(build("20"));
  });

  it("produces identical facts when tied business-key rows arrive in reverse order", () => {
    const builder = createMaterialSupplyFactBuilderRegistry().resolve("MM.PurchaseOrder.GetList");
    const rows = [
      {
        purchaseOrder: "4500001",
        purchaseOrderItem: "20",
        material: "MAT-1",
        plant: "P1",
        orderQuantity: 2,
        purchaseOrderUnit: "EA",
      },
      {
        purchaseOrder: "4500001",
        purchaseOrderItem: "10",
        material: "MAT-1",
        plant: "P1",
        orderQuantity: 1,
        purchaseOrderUnit: "EA",
      },
    ];
    const buildFacts = (purchaseOrders: typeof rows) => builder?.build(record({
      nodeId: "node.po",
      capabilityId: "MM.PurchaseOrder.GetList",
      producesFactTypes: ["PurchaseOrder"],
      executeData: { purchaseOrders },
    }));

    expect(buildFacts([...rows].reverse())).toEqual(buildFacts(rows));
  });
});

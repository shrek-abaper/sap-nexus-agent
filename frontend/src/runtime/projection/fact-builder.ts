import type { NodeFactRecord } from "../plan-executor/types";
import type { FactBuilderDeclaration, ReasoningFact } from "./types";

export class FactBuilderRegistry {
  private readonly builders = new Map<string, FactBuilderDeclaration>();

  register(builder: FactBuilderDeclaration): void {
    if (this.builders.has(builder.capabilityId)) {
      throw new Error(`fact builder already registered: ${builder.capabilityId}`);
    }
    this.builders.set(builder.capabilityId, builder);
  }

  resolve(capabilityId: string): FactBuilderDeclaration | null {
    return this.builders.get(capabilityId) ?? null;
  }
}

function freshness(record: NodeFactRecord, field = "dataAsOf"): string {
  const value = record.executeData[field];
  return typeof value === "string" && value.length > 0 ? value : record.nodeExecutedAt;
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function source(record: NodeFactRecord, factType: string): Record<string, unknown> {
  return { nodeId: record.nodeId, capabilityId: record.capabilityId, factType };
}

const inventoryBuilder: FactBuilderDeclaration = {
  capabilityId: "MM.Inventory.GetAvailability",
  freshnessField: "dataAsOf",
  build(record): ReasoningFact[] {
    const availableQuantity = record.executeData.availableQuantity;
    if (typeof availableQuantity !== "number" || !Number.isFinite(availableQuantity)) {
      return [];
    }
    const unit = optionalText(record.executeData.unit) ?? optionalText(record.parameters.unit);

    return [{
      factId: `${record.nodeId}:availableQuantity:0`,
      agentTraceId: "",
      traceId: "",
      gatewayTraceId: record.gatewayTraceId,
      domain: "MM",
      businessObject: "InventoryStock",
      predicate: "availableQuantity",
      value: availableQuantity,
      unit,
      deterministic: true,
      confidence: 1,
      source: source(record, "InventoryAvailability"),
      evidence: [{ field: "availableQuantity", value: availableQuantity }],
      material: optionalText(record.parameters.material),
      plant: optionalText(record.parameters.plant),
      asOf: freshness(record, "dataAsOf"),
    }];
  },
};

type PurchaseOrderRow = {
  purchaseOrder: string | null;
  supplier: string | null;
  material: string | null;
  plant: string | null;
  orderQuantity: number | null;
  purchaseOrderUnit: string | null;
};

function objectRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function purchaseOrderRow(
  record: NodeFactRecord,
  header: Record<string, unknown>,
  item: Record<string, unknown>,
): PurchaseOrderRow {
  const itemQuantity = item.orderQuantity;
  const headerQuantity = header.orderQuantity;
  return {
    purchaseOrder: optionalText(item.purchaseOrder) ?? optionalText(header.purchaseOrder),
    supplier: optionalText(header.supplier) ?? optionalText(item.supplier),
    material: optionalText(item.material)
      ?? optionalText(record.parameters.material)
      ?? optionalText(header.material),
    plant: optionalText(item.plant)
      ?? optionalText(record.parameters.plant)
      ?? optionalText(header.plant),
    orderQuantity: typeof itemQuantity === "number" && Number.isFinite(itemQuantity)
      ? itemQuantity
      : typeof headerQuantity === "number" && Number.isFinite(headerQuantity)
        ? headerQuantity
        : null,
    purchaseOrderUnit: optionalText(item.purchaseOrderUnit)
      ?? optionalText(header.purchaseOrderUnit),
  };
}

function purchaseOrderRows(record: NodeFactRecord): PurchaseOrderRow[] {
  const purchaseOrders = record.executeData.purchaseOrders;
  if (!Array.isArray(purchaseOrders)) return [];

  const rows: PurchaseOrderRow[] = [];
  for (const value of purchaseOrders) {
    const header = objectRecord(value);
    if (!header) continue;

    if (Array.isArray(header.items)) {
      for (const itemValue of header.items) {
        const item = objectRecord(itemValue);
        if (item) rows.push(purchaseOrderRow(record, header, item));
      }
    } else {
      rows.push(purchaseOrderRow(record, header, header));
    }
  }

  return rows.sort((left, right) => {
    const leftKey = [left.purchaseOrder ?? "", left.material ?? "", left.plant ?? ""].join("\u0000");
    const rightKey = [right.purchaseOrder ?? "", right.material ?? "", right.plant ?? ""].join("\u0000");
    return leftKey.localeCompare(rightKey);
  });
}

const purchaseOrderBuilder: FactBuilderDeclaration = {
  capabilityId: "MM.PurchaseOrder.GetList",
  freshnessField: "dataAsOf",
  build(record): ReasoningFact[] {
    const asOf = freshness(record, "dataAsOf");
    return purchaseOrderRows(record).map((row, index) => ({
      factId: `${record.nodeId}:purchaseOrderItem:${index}`,
      agentTraceId: "",
      traceId: "",
      gatewayTraceId: record.gatewayTraceId,
      domain: "MM",
      businessObject: "PurchaseOrder",
      predicate: "purchaseOrderItem",
      value: row.orderQuantity,
      unit: row.purchaseOrderUnit,
      deterministic: true,
      confidence: 1,
      source: source(record, "PurchaseOrder"),
      evidence: [{
        purchaseOrder: row.purchaseOrder,
        supplier: row.supplier,
        material: row.material,
        plant: row.plant,
        orderQuantity: row.orderQuantity,
        purchaseOrderUnit: row.purchaseOrderUnit,
      }],
      material: row.material,
      plant: row.plant,
      asOf,
    }));
  },
};

export function createMaterialSupplyFactBuilderRegistry(): FactBuilderRegistry {
  const registry = new FactBuilderRegistry();
  registry.register(inventoryBuilder);
  registry.register(purchaseOrderBuilder);
  return registry;
}

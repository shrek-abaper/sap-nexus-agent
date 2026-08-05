import type { FactBuilderDeclaration, ReasoningFact } from "./types";

type TraceableNodeFactRecord = Parameters<FactBuilderDeclaration["build"]>[0];

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

const TIMEZONE_AWARE_ISO_8601 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function freshness(record: TraceableNodeFactRecord, field = "dataAsOf"): string {
  const value = record.executeData[field];
  return typeof value === "string"
    && TIMEZONE_AWARE_ISO_8601.test(value)
    && Number.isFinite(Date.parse(value))
    ? value
    : record.nodeExecutedAt;
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function source(record: TraceableNodeFactRecord, factType: string): Record<string, unknown> {
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
      agentTraceId: record.agentTraceId,
      traceId: record.agentTraceId,
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
  purchaseOrderItem: string | null;
  supplier: string | null;
  material: string | null;
  plant: string | null;
  orderQuantity: number | null;
  orderQuantityEvidence: string | number | null;
  purchaseOrderUnit: string | null;
};

const DECIMAL_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

function finiteDecimal(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !DECIMAL_PATTERN.test(value)) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function quantityEvidence(value: unknown): string | number | null {
  return typeof value === "string" || typeof value === "number" ? value : null;
}

function orderQuantity(
  item: Record<string, unknown>,
  header: Record<string, unknown>,
): { value: number | null; evidence: string | number | null } {
  const selected = Object.prototype.hasOwnProperty.call(item, "orderQuantity")
    ? item.orderQuantity
    : header.orderQuantity;
  return {
    value: finiteDecimal(selected),
    evidence: quantityEvidence(selected),
  };
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function purchaseOrderRow(
  record: TraceableNodeFactRecord,
  header: Record<string, unknown>,
  item: Record<string, unknown>,
): PurchaseOrderRow {
  const quantity = orderQuantity(item, header);
  return {
    purchaseOrder: optionalText(item.purchaseOrder) ?? optionalText(header.purchaseOrder),
    purchaseOrderItem: optionalText(item.purchaseOrderItem)
      ?? optionalText(header.purchaseOrderItem),
    supplier: optionalText(header.supplier) ?? optionalText(item.supplier),
    material: optionalText(item.material)
      ?? optionalText(record.parameters.material)
      ?? optionalText(header.material),
    plant: optionalText(item.plant)
      ?? optionalText(record.parameters.plant)
      ?? optionalText(header.plant),
    orderQuantity: quantity.value,
    orderQuantityEvidence: quantity.evidence,
    purchaseOrderUnit: optionalText(item.purchaseOrderUnit)
      ?? optionalText(header.purchaseOrderUnit),
  };
}

function purchaseOrderRows(record: TraceableNodeFactRecord): PurchaseOrderRow[] {
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

  return rows.sort(compareRows);
}

function canonicalScalar(value: string | number | null): string {
  if (value === null) return "null";
  if (typeof value === "string") return `string:${JSON.stringify(value)}`;
  if (Number.isNaN(value)) return "number:NaN";
  if (value === Number.POSITIVE_INFINITY) return "number:Infinity";
  if (value === Number.NEGATIVE_INFINITY) return "number:-Infinity";
  if (Object.is(value, -0)) return "number:-0";
  return `number:${value}`;
}

function rowSortKey(row: PurchaseOrderRow): string {
  return JSON.stringify([
    row.purchaseOrder,
    row.material,
    row.plant,
    row.purchaseOrderItem,
    row.orderQuantity,
    row.purchaseOrderUnit,
    row.supplier,
    canonicalScalar(row.orderQuantityEvidence),
  ]);
}

function compareRows(left: PurchaseOrderRow, right: PurchaseOrderRow): number {
  const leftKey = rowSortKey(left);
  const rightKey = rowSortKey(right);
  return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
}

const purchaseOrderBuilder: FactBuilderDeclaration = {
  capabilityId: "MM.PurchaseOrder.GetList",
  freshnessField: "dataAsOf",
  build(record): ReasoningFact[] {
    const asOf = freshness(record, "dataAsOf");
    return purchaseOrderRows(record).map((row, index) => ({
      factId: `${record.nodeId}:purchaseOrderItem:${index}`,
      agentTraceId: record.agentTraceId,
      traceId: record.agentTraceId,
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
        orderQuantity: row.orderQuantityEvidence,
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

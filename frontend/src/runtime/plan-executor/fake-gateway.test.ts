// frontend/src/runtime/plan-executor/fake-gateway.test.ts
import { describe, expect, it } from "vitest";
import { FakeGateway } from "./fake-gateway";

describe("FakeGateway", () => {
  it("validate returns valid:true by default", async () => {
    const gw = new FakeGateway();
    const result = await gw.validate("MM.Inventory.GetAvailability", { material: "M", plant: "5300" });
    expect(result.valid).toBe(true);
  });

  it("execute returns success:true with data by default", async () => {
    const gw = new FakeGateway();
    const result = await gw.execute("MM.Inventory.GetAvailability", { material: "M", plant: "5300" });
    expect(result.success).toBe(true);
    expect(result.data).toBeDefined();
  });

  it("can be configured to fail validate for a capabilityId", async () => {
    const gw = new FakeGateway();
    gw.setValidateResult("MM.Inventory.GetAvailability", { valid: false, errors: ["bad param"] });
    const result = await gw.validate("MM.Inventory.GetAvailability", { material: "M" });
    expect(result.valid).toBe(false);
    expect(result.errors).toEqual(["bad param"]);
  });

  it("can be configured to fail execute for a capabilityId", async () => {
    const gw = new FakeGateway();
    gw.setExecuteResult("MM.PurchaseOrder.GetList", { success: false, errorType: "SAP_BUSINESS_ERROR", message: "no PO found" });
    const result = await gw.execute("MM.PurchaseOrder.GetList", { material: "M" });
    expect(result.success).toBe(false);
    expect(result.errorType).toBe("SAP_BUSINESS_ERROR");
  });

  it("records validate/execute calls for assertion", async () => {
    const gw = new FakeGateway();
    await gw.validate("Cap.A", { p: "1" });
    await gw.execute("Cap.B", { p: "2" });
    expect(gw.validateCalls).toEqual([{ capabilityId: "Cap.A", parameters: { p: "1" } }]);
    expect(gw.executeCalls).toEqual([{ capabilityId: "Cap.B", parameters: { p: "2" } }]);
  });

  it("can simulate latency via delayMs", async () => {
    const gw = new FakeGateway({ delayMs: 50 });
    const start = Date.now();
    await gw.execute("Cap.A", {});
    expect(Date.now() - start).toBeGreaterThanOrEqual(40);
  });
});

import { describe, expect, it, vi } from "vitest";
import { createServerReadGateway } from "./server-read-gateway";

function jsonResponse(payload: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createServerReadGateway", () => {
  it("sends only capabilityId and parameters through the registered validate endpoint", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({
      success: true,
      traceId: "trace-validate",
      messages: [],
    }));
    const gateway = createServerReadGateway({ baseUrl: "http://gateway.test", fetchImpl });

    await expect(gateway.validate("MM.Inventory.GetAvailability", {
      material: "MAT-1",
      plant: "P1",
    })).resolves.toEqual({ valid: true, traceId: "trace-validate", errors: [] });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://gateway.test/capabilities/MM.Inventory.GetAvailability/validate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parameters: { material: "MAT-1", plant: "P1" } }),
      },
    );
  });

  it("maps registered execute results without exposing raw response bodies", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({
      success: false,
      traceId: "trace-execute",
      errorType: "SAP_VALIDATION_FAILED",
      message: "safe summary",
      data: { status: "failed" },
      rawSapPayload: "must-not-pass-through",
    }, 422));
    const gateway = createServerReadGateway({ baseUrl: "http://gateway.test/", fetchImpl });

    await expect(gateway.execute("MM.PurchaseOrder.GetList", { material: "MAT-1" }))
      .resolves.toEqual({
        success: false,
        traceId: "trace-execute",
        errorType: "SAP_VALIDATION_FAILED",
        message: "safe summary",
        data: { status: "failed" },
      });
  });

  it("fails closed on a malformed Gateway response", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response("not-json", { status: 502 }));
    const gateway = createServerReadGateway({ baseUrl: "http://gateway.test", fetchImpl });

    await expect(gateway.validate("MM.Inventory.GetAvailability", {}))
      .resolves.toEqual({
        valid: false,
        errors: ["Gateway returned an invalid response"],
      });
  });
});

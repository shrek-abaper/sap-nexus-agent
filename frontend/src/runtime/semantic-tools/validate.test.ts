import { describe, expect, it } from "vitest";
import { SemanticToolRequestError } from "./types";
import { buildToolQuery, validateSemanticToolRequest } from "./validate";

const base = {
  contractVersion: 1,
  tool: "diagnose_material_supply",
  utterance: "A100 在 1000 工厂够不够用",
};

describe("validateSemanticToolRequest", () => {
  it("accepts a minimal valid request", () => {
    const request = validateSemanticToolRequest({ ...base });
    expect(request.tool).toBe("diagnose_material_supply");
    expect(request.utterance).toBe(base.utterance);
  });

  it("accepts slots and context", () => {
    const request = validateSemanticToolRequest({
      ...base,
      slots: { material: "A100", plant: "1000" },
      context: { plantScope: "1000", module: "MM", periodHint: "本月" },
    });
    expect(request.slots).toEqual({ material: "A100", plant: "1000" });
    expect(request.context?.module).toBe("MM");
  });

  it("rejects a non-object body", () => {
    expect(() => validateSemanticToolRequest("nope")).toThrow(SemanticToolRequestError);
  });

  it("rejects wrong contract version", () => {
    try {
      validateSemanticToolRequest({ ...base, contractVersion: 3 });
      throw new Error("expected");
    } catch (error) {
      expect(error).toBeInstanceOf(SemanticToolRequestError);
      expect((error as SemanticToolRequestError).message).toContain("contractVersion");
    }
  });

  it("rejects an unknown tool with UNKNOWN_SEMANTIC_TOOL (404)", () => {
    try {
      validateSemanticToolRequest({ ...base, tool: "MM.Inventory.GetAvailability" });
      throw new Error("expected");
    } catch (error) {
      expect(error).toBeInstanceOf(SemanticToolRequestError);
      const typed = error as SemanticToolRequestError;
      expect(typed.errorType).toBe("UNKNOWN_SEMANTIC_TOOL");
      expect(typed.httpStatus).toBe(404);
    }
  });

  it.each([
    ["rfcName", { rfcName: "BAPI_MATERIAL_AVAILABILITY" }],
    ["bindingId", { bindingId: "jco-inventory" }],
    ["nested credential", { slots: { material: "A100", token: "x" } }],
    ["uppercase endpoint", { ENDPOINT: "http://sap" }],
  ])("rejects technical override field: %s", (_label, extra) => {
    try {
      validateSemanticToolRequest({ ...base, ...extra });
      throw new Error("expected");
    } catch (error) {
      expect(error).toBeInstanceOf(SemanticToolRequestError);
      expect((error as SemanticToolRequestError).errorType).toBe("TECHNICAL_OVERRIDE_REJECTED");
    }
  });

  it("rejects unknown benign fields as INVALID_REQUEST", () => {
    try {
      validateSemanticToolRequest({ ...base, capabilityId: "x" });
      throw new Error("expected");
    } catch (error) {
      expect((error as SemanticToolRequestError).errorType).toBe("INVALID_REQUEST");
    }
  });

  it("rejects empty utterance and bad module", () => {
    expect(() => validateSemanticToolRequest({ ...base, utterance: " " })).toThrow();
    expect(() =>
      validateSemanticToolRequest({ ...base, context: { module: "PP" } })).toThrow();
  });
});

describe("buildToolQuery", () => {
  it("renders only the utterance without slots or context", () => {
    expect(buildToolQuery(validateSemanticToolRequest({ ...base }))).toBe(base.utterance);
  });

  it("renders slots and context deterministically", () => {
    const query = buildToolQuery(validateSemanticToolRequest({
      ...base,
      slots: { material: "A100", plant: "1000" },
      context: { module: "MM", periodHint: "本月" },
    }));
    expect(query).toBe("A100 在 1000 工厂够不够用\n[已知条件] 物料: A100；工厂: 1000；模块: MM；时间: 本月");
  });

  it("falls back to context.plantScope when the plant slot is absent", () => {
    const query = buildToolQuery(validateSemanticToolRequest({
      ...base,
      slots: { material: "A100" },
      context: { plantScope: "1000" },
    }));
    expect(query).toContain("工厂: 1000");
  });
});

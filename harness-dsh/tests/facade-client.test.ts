import { describe, expect, it } from "vitest";
import {
  facadeEndpoint,
  FacadeContractError,
  validateFacadeResponse,
  type SemanticToolResponse,
} from "../src/facade-client.js";

const baseResponse: SemanticToolResponse = {
  contractVersion: 1,
  tool: "diagnose_material_supply",
  status: "complete",
  runId: "run-1",
  resolved: { semanticValues: [] },
  capabilityChain: [],
  facts: [],
  narrative: { summary: "ok", limitations: [] },
  limitations: [],
};

describe("validateFacadeResponse", () => {
  it("accepts a well-formed response", () => {
    expect(validateFacadeResponse({ ...baseResponse })).toMatchObject({ runId: "run-1" });
  });

  it.each([
    ["non-object", null],
    ["wrong contract version", { ...baseResponse, contractVersion: 2 }],
    ["wrong tool", { ...baseResponse, tool: "MM.Inventory.GetAvailability" }],
    ["missing runId", { ...baseResponse, runId: "" }],
    ["missing facts array", { ...baseResponse, facts: undefined }],
    ["missing narrative", { ...baseResponse, narrative: undefined }],
  ])("rejects %s", (_label, raw) => {
    expect(() => validateFacadeResponse(raw)).toThrow(FacadeContractError);
  });
});

describe("facadeEndpoint", () => {
  it("joins base URL and facade path", () => {
    expect(facadeEndpoint("http://127.0.0.1:3000")).toBe("http://127.0.0.1:3000/api/semantic-tools");
    expect(facadeEndpoint("http://127.0.0.1:3000/")).toBe("http://127.0.0.1:3000/api/semantic-tools");
  });
});

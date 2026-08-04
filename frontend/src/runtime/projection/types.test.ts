import { describe, expect, it } from "vitest";
import type { MaterialSupplySnapshot, OutputProjectionDeclaration } from "./types";

describe("projection contracts", () => {
  it("constructs the frozen snapshot and declaration contract", () => {
    const snapshot: MaterialSupplySnapshot = {
      projectionId: "material-supply-snapshot",
      projectionVersion: "1.0.0",
      snapshotId: "sha256:snap-001",
      asOf: "2026-08-04T00:00:00.000Z",
      sourceFreshness: [],
      completeness: "complete",
      facts: [],
      lineage: [],
      missingFacts: [],
      failedNodes: [],
      limitations: [],
      outputHash: "a".repeat(64),
    };
    const declaration: Pick<
      OutputProjectionDeclaration,
      "projectionId" | "version" | "outputSchema" | "timeBasis" | "partialPolicy"
    > = {
      projectionId: "material-supply-snapshot",
      version: "1.0.0",
      outputSchema: "MaterialSupplySnapshot@1.0.0",
      timeBasis: "dataAsOf",
      partialPolicy: "complete-partial-incomplete",
    };

    expect(snapshot.completeness).toBe("complete");
    expect(declaration.timeBasis).toBe("dataAsOf");
  });
});

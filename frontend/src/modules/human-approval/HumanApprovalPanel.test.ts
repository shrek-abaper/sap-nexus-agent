import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HumanApprovalPanel } from "./HumanApprovalPanel";

(globalThis as typeof globalThis & { React: typeof React }).React = React;

describe("HumanApprovalPanel governed subject evidence", () => {
  it("shows immutable parameter sources and governed refs before confirmation", () => {
    const markup = renderToStaticMarkup(React.createElement(HumanApprovalPanel, {
      state: "awaiting_human_approval",
      artifact: {
        label: "ApprovalRecord",
        kind: "approval-record",
        payload: {
          data: {
            approvalId: "approval-1",
            status: "pending",
            parameters: {
              material: "MAT-1",
              plant: "1000",
              quantity: "3",
              unit: "EA",
              delivery_date: "2026-08-15",
              purchasing_group: "001",
            },
            parameterSources: {
              material: [{ kind: "fact", ref: "fact-inventory", field: "material" }],
              quantity: [{ kind: "constraint", ref: "requiredQuantity" }],
            },
            factRefs: ["fact-inventory"],
            projectionRef: { projectionId: "MaterialSupplySnapshot", version: "1.0.0", outputHash: "projection-hash-1" },
            ruleSetRefs: ["material-shortage@1.0.0"],
            proposalId: "proposal-1",
            limitations: [{ code: "SANDBOX_ONLY", detail: "No live SAP WRITE in verification" }],
            expiresAt: "2026-08-05T08:10:00.000Z",
            parameterSnapshotHash: "sha256:parameters",
            capabilityVersion: "2.1.0",
            subjectHash: "sha256:subject",
            proposalHash: "sha256:proposal",
            separationOfDutyResult: "not_applicable",
          },
        },
      },
      onDecision: () => undefined,
    }));

    expect(markup).toContain("参数来源");
    expect(markup).toContain("fact-inventory");
    expect(markup).toContain("MaterialSupplySnapshot@1.0.0");
    expect(markup).toContain("material-shortage@1.0.0");
    expect(markup).toContain("proposal-1");
    expect(markup).toContain("No live SAP WRITE in verification");
  });
});

import { describe, expect, it } from "vitest";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  canDecideApproval,
  HumanApprovalPanel
} from "../../src/modules/human-approval/HumanApprovalPanel";

(globalThis as typeof globalThis & { React: typeof React }).React = React;

describe("canDecideApproval", () => {
  it("exposes decisions only while awaiting human approval", () => {
    expect(canDecideApproval("awaiting_human_approval")).toBe(true);
    expect(canDecideApproval("approval_required")).toBe(false);
    expect(canDecideApproval("approved")).toBe(false);
    expect(canDecideApproval("rejected")).toBe(false);
    expect(canDecideApproval("approval_not_required")).toBe(false);
  });

  it("shows approval expiry and snapshot hash before decision", () => {
    const markup = renderToStaticMarkup(React.createElement(
      HumanApprovalPanel,
      {
        state: "awaiting_human_approval",
        artifact: {
          label: "ApprovalRecord",
          kind: "approval",
          payload: {
            approvalId: "appr-001",
            parameterSnapshotHash: "sha256:abc123",
            expiresAt: "2026-07-17T10:10:00Z",
            parameters: { material: "M001", plant: "1000" }
          }
        },
        onDecision: () => undefined
      }
    ));

    expect(markup).toContain("2026-07-17T10:10:00Z");
    expect(markup).toContain("sha256:abc123");
  });
});

import { describe, expect, it } from "vitest";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  canDecideApproval,
  HumanApprovalPanel
} from "../../src/modules/human-approval/HumanApprovalPanel";

(globalThis as typeof globalThis & { React: typeof React }).React = React;

describe("canDecideApproval", () => {
  const pendingArtifact = {
    label: "PlanApprovalRecord",
    kind: "approval-record" as const,
    payload: { approvalId: "appr-001", status: "pending" }
  };

  it("exposes decisions only for a real pending approval record", () => {
    expect(canDecideApproval("awaiting_human_approval", pendingArtifact)).toBe(true);
    expect(canDecideApproval("awaiting_human_approval", undefined)).toBe(false);
    expect(canDecideApproval("awaiting_human_approval", {
      ...pendingArtifact,
      payload: { approvalId: "appr-001", status: "revoked" }
    })).toBe(false);
    expect(canDecideApproval("approval_required", pendingArtifact)).toBe(false);
    expect(canDecideApproval("approved", pendingArtifact)).toBe(false);
    expect(canDecideApproval("rejected", pendingArtifact)).toBe(false);
    expect(canDecideApproval("approval_not_required", pendingArtifact)).toBe(false);
  });

  it("shows approval expiry and snapshot hash before decision", () => {
    const markup = renderToStaticMarkup(React.createElement(
      HumanApprovalPanel,
      {
        state: "awaiting_human_approval",
        artifact: {
          label: "ApprovalRecord",
          kind: "approval-record",
          payload: {
            approvalId: "appr-001",
            status: "pending",
            parameterSnapshotHash: "sha256:abc123",
            expiresAt: "2026-07-17T10:10:00Z",
            capabilityVersion: "2.1.0",
            subjectHash: "sha256:subject",
            separationOfDutyResult: "not_applicable",
            parameters: { material: "M001", plant: "1000" }
          }
        },
        onDecision: () => undefined
      }
    ));

    expect(markup).toContain("2026-07-17T10:10:00Z");
    expect(markup).toContain("sha256:abc123");
    expect(markup).toContain("2.1.0");
    expect(markup).toContain("sha256:subject");
    expect(markup).toContain("批准并执行");
  });

  it("never renders decision buttons for proposal-only or terminal approval state", () => {
    const proposalOnly = renderToStaticMarkup(React.createElement(
      HumanApprovalPanel,
      { state: "awaiting_human_approval", onDecision: () => undefined }
    ));
    const revoked = renderToStaticMarkup(React.createElement(
      HumanApprovalPanel,
      {
        state: "awaiting_human_approval",
        artifact: { ...pendingArtifact, payload: { approvalId: "appr-001", status: "revoked" } },
        onDecision: () => undefined
      }
    ));

    expect(proposalOnly).not.toContain("<button");
    expect(revoked).not.toContain("<button");
    expect(revoked).toContain("已撤销");
  });
});

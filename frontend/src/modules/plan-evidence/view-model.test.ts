import { describe, expect, it } from "vitest";
import { planEvidenceFixtures } from "../../runtime/plan-evidence/fixtures";
import { buildPlanEvidenceView } from "./view-model";

describe("buildPlanEvidenceView", () => {
  it("builds the complete desktop and mobile workspace from a multi-READ run", () => {
    const view = buildPlanEvidenceView(planEvidenceFixtures.multiRead);

    expect(view.mode).toBe("ready");
    expect(view.sections.map((section) => section.id)).toEqual([
      "conversation",
      "intent-recall",
      "plan",
      "execution",
      "evidence",
      "recommendation-narrative",
      "action-approval",
      "trace-replay",
    ]);
    expect(view.desktopColumns).toEqual({ left: "plan", right: "evidence" });
    expect(view.mobileOrder).toEqual(view.sections.map((section) => section.id));
    expect(view.claims).toEqual([
      expect.objectContaining({
        claimId: "claim-supply-1",
        supported: true,
        evidenceRefs: ["fact-inventory", "fact-po"],
      }),
    ]);
    expect(view.claims[0].evidenceTargets.map((target) => target.ref)).toEqual([
      "fact-inventory",
      "fact-po",
    ]);
    expect(view.sections.find((section) => section.id === "trace-replay")?.objects).toEqual([
      expect.objectContaining({
        ref: "trace-run-multi-read",
        data: expect.objectContaining({ runId: "run-multi-read", snapshotIds: ["snapshot-fixture-1"] }),
      }),
    ]);
  });

  it("marks partial node/projection evidence as limited instead of complete", () => {
    const view = buildPlanEvidenceView(planEvidenceFixtures.partialFailure);

    expect(view.mode).toBe("limited");
    expect(view.limitations).toContain("采购订单节点超时，供给快照不完整");
    expect(view.sections.find((section) => section.id === "execution")?.objects).toEqual(
      expect.arrayContaining([expect.objectContaining({ data: expect.objectContaining({ state: "TIMED_OUT" }) })]),
    );
  });

  it("keeps a proposal read-only until an ApprovalRecord exists", () => {
    const view = buildPlanEvidenceView(planEvidenceFixtures.readToWriteProposal);

    expect(view.proposal).toMatchObject({
      status: "pending_approval",
      capabilityId: "MM.PR.CreateDraft",
      readOnly: true,
      proposalHash: "proposal-hash-1",
      parameters: expect.objectContaining({ material: "DEMOA1", plant: "1000" }),
      factsUsed: ["fact-inventory", "fact-po"],
      ruleSetRefs: ["material-supply-v1"],
    });
    expect(view.canDecideApproval).toBe(false);
  });

  it("allows a decision only for a real pending PlanApprovalRecord", () => {
    const pending = structuredClone(planEvidenceFixtures.readToWritePendingApproval);
    const view = buildPlanEvidenceView(pending);

    expect(view.approval).toMatchObject({
      approvalId: "approval-fixture-1",
      status: "pending",
      capabilityVersion: "2.1.0",
      separationOfDutyResult: "not_applicable",
    });
    expect(view.canDecideApproval).toBe(true);

    const terminal = structuredClone(pending);
    const event = terminal.events.find((candidate) => candidate.artifact?.kind === "approval-record");
    if (event?.artifact && event.artifact.payload && typeof event.artifact.payload === "object" && !Array.isArray(event.artifact.payload)) {
      const data = event.artifact.payload.data;
      if (data && typeof data === "object" && !Array.isArray(data)) data.status = "revoked";
    }
    expect(buildPlanEvidenceView(terminal).canDecideApproval).toBe(false);
  });

  it("surfaces replay gaps and unsupported claims as non-authoritative evidence", () => {
    const snapshot = {
      ...structuredClone(planEvidenceFixtures.multiRead),
      replayIntegrity: {
        status: "gap" as const,
        expectedSequence: 4,
        receivedSequence: 5,
        message: "Expected sequence 4, received 5",
      },
    };
    const narrative = snapshot.events.find((event) => event.artifact?.kind === "narrative-envelope");
    if (narrative?.artifact && narrative.artifact.payload && typeof narrative.artifact.payload === "object" && !Array.isArray(narrative.artifact.payload)) {
      const envelope = narrative.artifact.payload as Record<string, unknown>;
      envelope.data = {
        claims: [{ claimId: "unsupported", text: "无依据结论", evidenceRefs: ["missing-ref"] }],
      };
    }

    const view = buildPlanEvidenceView(snapshot);

    expect(view.mode).toBe("error");
    expect(view.replayMessage).toContain("Expected sequence 4");
    expect(view.claims[0]).toMatchObject({ supported: false });
  });

  it("marks a corrupt governed object reference as an error", () => {
    const snapshot = structuredClone(planEvidenceFixtures.multiRead);
    const plan = snapshot.events.find((event) => event.artifact?.kind === "plan-graph");
    if (plan?.artifact && plan.artifact.payload && typeof plan.artifact.payload === "object" && !Array.isArray(plan.artifact.payload)) {
      plan.artifact.payload.evidenceRefs = ["node-missing"];
    }

    expect(buildPlanEvidenceView(snapshot).mode).toBe("error");
  });

  it("distinguishes loading and empty states", () => {
    expect(buildPlanEvidenceView(null, true).mode).toBe("loading");
    expect(buildPlanEvidenceView(null).mode).toBe("empty");
    expect(buildPlanEvidenceView(planEvidenceFixtures.singleCapability).mode).toBe("ready");
  });

  it("renders a failed run as an error instead of complete evidence", () => {
    const snapshot = {
      ...planEvidenceFixtures.singleCapability,
      state: "failed" as const,
      error: { errorType: "RunnerError", message: "runner failed", stage: "running" as const },
    };

    expect(buildPlanEvidenceView(snapshot).mode).toBe("error");
  });

  it("reads structured limitation details from governed projection objects", () => {
    const snapshot = structuredClone(planEvidenceFixtures.multiRead);
    for (const event of snapshot.events) {
      const payload = event.artifact?.payload;
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) continue;
      const data = payload.data;
      if (!data || typeof data !== "object" || Array.isArray(data) || !("limitations" in data)) continue;
      data.limitations = [{ code: "stale_source", detail: "采购订单来源超出 freshness 窗口", evidenceRefs: [] }];
    }

    expect(buildPlanEvidenceView(snapshot).limitations).toContain("采购订单来源超出 freshness 窗口");
  });

  it("maps legacy single-capability evidence into intent, execution, evidence and trace sections", () => {
    const view = buildPlanEvidenceView(planEvidenceFixtures.singleCapability);
    const populated = new Set(view.sections.filter((section) => section.objects.length > 0).map((section) => section.id));

    expect([...populated]).toEqual(expect.arrayContaining([
      "intent-recall",
      "execution",
      "evidence",
      "trace-replay",
    ]));
  });
});

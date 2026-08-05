import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { planEvidenceFixtures } from "../../runtime/plan-evidence/fixtures";
import { PlanEvidencePanel } from "./PlanEvidencePanel";

describe("PlanEvidencePanel", () => {
  it("renders the eight semantic sections and claim-to-evidence navigation", () => {
    const html = renderToStaticMarkup(createElement(PlanEvidencePanel, { snapshot: planEvidenceFixtures.multiRead }));

    for (const section of [
      "conversation",
      "intent-recall",
      "plan",
      "execution",
      "evidence",
      "recommendation-narrative",
      "action-approval",
      "trace-replay",
    ]) {
      expect(html).toContain(`data-section="${section}"`);
    }
    expect(html).toContain('href="#evidence-fact-inventory"');
    expect(html).toContain('id="evidence-fact-inventory"');
    expect(html).toContain('href="#evidence-node-inventory"');
    expect(html).toContain("safeCallPlan");
    expect(html).toContain("safeResult");
    expect(html).toContain('aria-label="Plan and evidence workspace"');
  });

  it("renders pending proposal provenance without an approval button", () => {
    const html = renderToStaticMarkup(createElement(PlanEvidencePanel, { snapshot: planEvidenceFixtures.readToWriteProposal }));

    expect(html).toContain("待审批");
    expect(html).toContain("MM.PR.CreateDraft");
    expect(html).toContain("proposal-hash-1");
    expect(html).toContain("DEMOA1");
    expect(html).toContain("fact-inventory");
    expect(html).toContain("material-supply-v1");
    expect(html).not.toContain("<button");
  });

  it("renders partial evidence and replay integrity as visible status", () => {
    const html = renderToStaticMarkup(createElement(PlanEvidencePanel, { snapshot: planEvidenceFixtures.partialFailure }));

    expect(html).toContain('data-mode="limited"');
    expect(html).toContain('role="status"');
    expect(html).toContain("采购订单节点超时，供给快照不完整");
  });

  it("renders distinct loading and empty states", () => {
    expect(renderToStaticMarkup(createElement(PlanEvidencePanel, { snapshot: null, loading: true }))).toContain("正在加载 plan 与 evidence");
    expect(renderToStaticMarkup(createElement(PlanEvidencePanel, { snapshot: null }))).toContain("尚无 plan/evidence 事件");
  });

  it("visibly rejects a claim without evidence references", () => {
    const snapshot = structuredClone(planEvidenceFixtures.multiRead);
    const narrative = snapshot.events.find((event) => event.artifact?.kind === "narrative-envelope");
    if (narrative?.artifact && narrative.artifact.payload && typeof narrative.artifact.payload === "object" && !Array.isArray(narrative.artifact.payload)) {
      const data = narrative.artifact.payload.data;
      if (data && typeof data === "object" && !Array.isArray(data)) {
        data.claims = [{ claimId: "unsupported", text: "无依据结论", evidenceRefs: [] }];
      }
    }

    const html = renderToStaticMarkup(createElement(PlanEvidencePanel, { snapshot }));
    expect(html).toContain("unsupported claim");
    expect(html).toContain('data-mode="error"');
  });
});

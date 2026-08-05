import { describe, expect, it, vi } from "vitest";
import type { PlanApprovalRecord } from "./action-governance";
import { createServerActionGateway } from "./server-action-gateway";

function approvedRecord(): PlanApprovalRecord {
  return {
    approvalId: "appr-plan-21",
    runId: "run-21",
    traceId: "trace-21",
    planId: "plan-21",
    planHash: "sha256:plan",
    snapshotId: "snapshot-21",
    actionNodeId: "action-1",
    capabilityId: "MM.PR.CreateDraft",
    capabilityVersion: "2.1.0",
    parameterSnapshotHash: "sha256:parameters",
    parameters: { material: "M001", plant: "1000" },
    parameterSources: { material: [{ kind: "fact", ref: "fact-1", field: "material" }] },
    factSetHash: "sha256:facts",
    factRefs: ["fact-1"],
    projectionRef: {
      projectionId: "MaterialSupplySnapshot",
      version: "1.0.0",
      outputHash: "sha256:projection",
    },
    ruleSetRefs: ["material-shortage@1.0.0"],
    ruleSetHash: "sha256:rules",
    proposalId: "proposal-21",
    proposalHash: "sha256:proposal",
    limitations: [],
    subjectHash: "sha256:subject-21",
    principalId: "run-owner",
    tenantId: "tenant-1",
    role: "operator",
    dataScopeHash: "sha256:scope",
    confirmingPrincipalId: "run-owner",
    decidedAt: "2026-08-05T08:01:00.000Z",
    createdAt: "2026-08-05T08:00:00.000Z",
    expiresAt: "2026-08-05T08:10:00.000Z",
    revokedAt: null,
    revocationReason: null,
    separationOfDutyResult: "not_applicable",
    status: "approved",
  };
}

describe("createServerActionGateway", () => {
  it("maps a verified PlanApprovalRecord to the existing atomic Gateway contract", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(input), init: init ?? {} });
      return new Response(JSON.stringify({ approvalId: "appr-plan-21" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;
    const gateway = createServerActionGateway({
      fetchImpl,
      env: {
        SAP_NEXUS_GATEWAY_URL: "http://gateway.internal:8080",
        SAP_NEXUS_APPROVAL_TOKEN: "server-only-token",
      },
    });

    await gateway.approve(approvedRecord());

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://gateway.internal:8080/capabilities/MM.PR.CreateDraft/approve");
    expect(new Headers(calls[0].init.headers).get("X-SAP-Nexus-Approval-Token")).toBe("server-only-token");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      approvalId: "appr-plan-21",
      capabilityId: "MM.PR.CreateDraft",
      parameterSnapshotHash: "sha256:parameters",
      parameters: { material: "M001", plant: "1000" },
      approver: "run-owner",
      approvedAt: "2026-08-05T08:01:00.000Z",
      expiresAt: "2026-08-05T08:10:00.000Z",
      status: "approved",
      registrySnapshotId: "snapshot-21",
      capabilityVersion: "2.1.0",
      approvalSubjectHash: "sha256:subject-21",
    });
    expect(String(calls[0].init.body)).not.toContain("server-only-token");
    expect(String(calls[0].init.body)).not.toContain("planHash");
    expect(String(calls[0].init.body)).not.toContain("dataScopeHash");
  });

  it("sends only governed Action fields and normalizes the Gateway ActionResult", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(input), init: init ?? {} });
      return new Response(JSON.stringify({
        traceId: "gateway-trace-21",
        capabilityId: "MM.PR.CreateDraft",
        success: true,
        prNumber: "10000021",
        commitStatus: "committed",
        returnMessages: [{ type: "S", message: "created" }],
        errorType: "NONE",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
    const gateway = createServerActionGateway({
      fetchImpl,
      env: { SAP_NEXUS_GATEWAY_URL: "http://gateway.internal:8080", SAP_NEXUS_APPROVAL_TOKEN: "token" },
    });

    const result = await gateway.execute({
      capabilityId: "MM.PR.CreateDraft",
      parameters: { material: "M001", plant: "1000" },
      approvalId: "appr-plan-21",
      parameterSnapshotHash: "sha256:parameters",
      registrySnapshotId: "snapshot-21",
      capabilityVersion: "2.1.0",
      approvalSubjectHash: "sha256:subject-21",
    });

    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      parameters: { material: "M001", plant: "1000" },
      approvalId: "appr-plan-21",
      parameterSnapshotHash: "sha256:parameters",
      registrySnapshotId: "snapshot-21",
      capabilityVersion: "2.1.0",
      approvalSubjectHash: "sha256:subject-21",
    });
    expect(String(calls[0].init.body)).not.toMatch(/rfcName|bindingId|token|principal/i);
    expect(result).toMatchObject({
      success: true,
      traceId: "gateway-trace-21",
      data: { prNumber: "10000021", commitStatus: "committed" },
      errorType: "NONE",
    });
  });

  it("fails closed before network access when the server approval token is absent", async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    const gateway = createServerActionGateway({
      fetchImpl,
      env: { SAP_NEXUS_GATEWAY_URL: "http://gateway.internal:8080" },
    });

    await expect(gateway.approve(approvedRecord())).rejects.toMatchObject({
      errorType: "APPROVAL_SERVICE_FORBIDDEN",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("treats duplicate atomic registration as retry-safe and leaves execute to revalidate", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      errorType: "APPROVAL_DUPLICATE",
    }), { status: 409, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch;
    const gateway = createServerActionGateway({
      fetchImpl,
      env: { SAP_NEXUS_GATEWAY_URL: "http://gateway.internal:8080", SAP_NEXUS_APPROVAL_TOKEN: "token" },
    });

    await expect(gateway.approve(approvedRecord())).resolves.toBeUndefined();
  });
});

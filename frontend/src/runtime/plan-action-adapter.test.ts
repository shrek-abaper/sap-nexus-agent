import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { canonicalJson, sha256Hex } from "./durable/canonical-json";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import { PLACEHOLDER_PRINCIPAL, type TrustedPrincipal } from "./principal/types";
import {
  decideAgentRunApproval,
  getAgentRunEvents,
  setAgentRunnerForTests,
  setDurableStoresForTests,
} from "./agent-runtime-adapter";
import { POST as decideApprovalRoute } from "../../app/api/agent-runs/[runId]/approval/route";

const temporaryDirectories: string[] = [];

beforeEach(() => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "sap-nexus-plan-action-adapter-"));
  temporaryDirectories.push(directory);
  setDurableStoresForTests(
    new JsonlRunStore(path.join(directory, "runs"), "adapter-worker"),
    new JsonlConversationStore(path.join(directory, "conversations")),
  );
  setAgentRunnerForTests(null);
});

afterEach(() => {
  setAgentRunnerForTests(null);
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("agent runtime plan-aware approval routing", () => {
  it("routes a durable plan approval to subject validation instead of the legacy Python continuation", async () => {
    const directory = temporaryDirectories.at(-1)!;
    const store = new JsonlRunStore(path.join(directory, "runs"), "adapter-worker");
    setDurableStoresForTests(store, new JsonlConversationStore(path.join(directory, "conversations")));
    await store.save("run-1", {
      runId: "run-1",
      query: "governed plan action",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [{ runId: "run-1", sequence: 1, timestamp: "2026-08-05T08:00:00.000Z", type: "run_started", state: "running" }],
      pendingOutcome: {
        status: "awaiting_approval",
        approvalRecord: { approvalId: "approval-plan-1", status: "pending" },
        data: {
          actionGovernance: {
            schema: "sap-nexus.plan-action-governance.v1",
            input: {},
          },
        },
      },
    });

    await expect(decideAgentRunApproval(
      "run-1",
      "approval-plan-1",
      "approve",
      PLACEHOLDER_PRINCIPAL,
    )).rejects.toMatchObject({ errorType: "APPROVAL_SUBJECT_MISMATCH" });
  });

  it("preserves the structured plan approval error at the browser API boundary", async () => {
    const directory = temporaryDirectories.at(-1)!;
    const store = new JsonlRunStore(path.join(directory, "runs"), "adapter-worker");
    setDurableStoresForTests(store, new JsonlConversationStore(path.join(directory, "conversations")));
    await store.save("run-1", {
      runId: "run-1",
      query: "governed plan action",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [{ runId: "run-1", sequence: 1, timestamp: "2026-08-05T08:00:00.000Z", type: "run_started", state: "running" }],
      pendingOutcome: {
        status: "awaiting_approval",
        approvalRecord: { approvalId: "approval-plan-1", status: "pending" },
        data: { actionGovernance: { schema: "sap-nexus.plan-action-governance.v1", input: {} } },
      },
    });

    const response = await decideApprovalRoute(
      new Request("http://localhost/api/agent-runs/run-1/approval", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approvalId: "approval-plan-1", decision: "approve" }),
      }),
      { params: Promise.resolve({ runId: "run-1" }) },
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ errorType: "APPROVAL_SUBJECT_MISMATCH" });
  });

  it("does not expose plan approval events when trusted tenant/role/data scope drift", async () => {
    const directory = temporaryDirectories.at(-1)!;
    const store = new JsonlRunStore(path.join(directory, "runs"), "adapter-worker");
    setDurableStoresForTests(store, new JsonlConversationStore(path.join(directory, "conversations")));
    await store.save("run-1", {
      runId: "run-1",
      query: "governed plan action",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [{ runId: "run-1", sequence: 1, timestamp: "2026-08-05T08:00:00.000Z", type: "run_started", state: "running" }],
      pendingOutcome: {
        status: "awaiting_approval",
        approvalRecord: {
          approvalId: "approval-plan-1",
          status: "pending",
          planId: "plan-1",
          subjectHash: "subject-hash-1",
          principalId: PLACEHOLDER_PRINCIPAL.principalId,
          tenantId: "default",
          role: PLACEHOLDER_PRINCIPAL.role,
          dataScopeHash: sha256Hex(canonicalJson(PLACEHOLDER_PRINCIPAL.dataScope)),
        },
      },
    });
    const drifted: TrustedPrincipal = {
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      role: "operator",
      dataScope: { tenantId: "other-tenant" },
    };

    expect(await getAgentRunEvents("run-1", drifted)).toEqual([]);
  });
});

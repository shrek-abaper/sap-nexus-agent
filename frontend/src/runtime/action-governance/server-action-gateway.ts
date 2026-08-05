import {
  ActionGovernanceError,
  type ActionGateway,
  type ActionGatewayRequest,
  type ActionGatewayResult,
  type PlanApprovalRecord,
} from "./action-governance";

type GatewayEnvironment = {
  SAP_NEXUS_GATEWAY_URL?: string;
  GATEWAY_PORT?: string;
  SAP_NEXUS_APPROVAL_TOKEN?: string;
};

type ServerActionGatewayOptions = {
  fetchImpl?: typeof fetch;
  env?: GatewayEnvironment;
};

class ServerActionGateway implements ActionGateway {
  constructor(
    private readonly baseUrl: string,
    private readonly approvalToken: string,
    private readonly fetchImpl: typeof fetch,
  ) {}

  async approve(record: PlanApprovalRecord): Promise<void> {
    if (!this.approvalToken) {
      throw new ActionGovernanceError(
        "APPROVAL_SERVICE_FORBIDDEN",
        "Server approval token is not configured",
      );
    }
    if (record.status !== "approved" || !record.confirmingPrincipalId || !record.decidedAt) {
      throw new ActionGovernanceError(
        "APPROVAL_REQUIRED",
        "Only an explicitly confirmed approval can be registered",
      );
    }
    const response = await this.fetchImpl(this.capabilityUrl(record.capabilityId, "approve"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SAP-Nexus-Approval-Token": this.approvalToken,
      },
      body: JSON.stringify({
        approvalId: record.approvalId,
        capabilityId: record.capabilityId,
        parameterSnapshotHash: record.parameterSnapshotHash,
        parameters: record.parameters,
        approver: record.confirmingPrincipalId,
        approvedAt: record.decidedAt,
        expiresAt: record.expiresAt,
        status: "approved",
        registrySnapshotId: record.snapshotId,
        capabilityVersion: record.capabilityVersion,
        approvalSubjectHash: record.subjectHash,
      }),
    });
    if (!response.ok) {
      const error = await responseJson(response);
      if (response.status === 409 && error.errorType === "APPROVAL_DUPLICATE") {
        return;
      }
      throw new ActionGovernanceError(
        text(error.errorType) || "APPROVAL_REGISTRATION_FAILED",
        text(error.message) || `Gateway approval registration failed with HTTP ${response.status}`,
      );
    }
  }

  async execute(request: ActionGatewayRequest): Promise<ActionGatewayResult> {
    const response = await this.fetchImpl(this.capabilityUrl(request.capabilityId, "execute"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parameters: request.parameters,
        approvalId: request.approvalId,
        parameterSnapshotHash: request.parameterSnapshotHash,
        registrySnapshotId: request.registrySnapshotId,
        capabilityVersion: request.capabilityVersion,
        approvalSubjectHash: request.approvalSubjectHash,
      }),
    });
    const payload = await responseJson(response);
    const returnMessages = recordArray(payload.returnMessages);
    return {
      success: response.ok && payload.success === true,
      traceId: text(payload.traceId) || undefined,
      data: {
        prNumber: text(payload.prNumber),
        commitStatus: text(payload.commitStatus),
      },
      returnMessages,
      errorType: text(payload.errorType) || (response.ok ? undefined : "GATEWAY_EXECUTION_FAILED"),
      message: text(payload.message) || text(returnMessages[0]?.message) || undefined,
    };
  }

  private capabilityUrl(capabilityId: string, operation: "approve" | "execute"): string {
    return `${this.baseUrl}/capabilities/${encodeURIComponent(capabilityId)}/${operation}`;
  }
}

export function createServerActionGateway(
  options: ServerActionGatewayOptions = {},
): ActionGateway {
  const env = options.env ?? process.env;
  const baseUrl = (env.SAP_NEXUS_GATEWAY_URL
    || `http://127.0.0.1:${env.GATEWAY_PORT || "8080"}`).replace(/\/$/, "");
  return new ServerActionGateway(
    baseUrl,
    env.SAP_NEXUS_APPROVAL_TOKEN?.trim() ?? "",
    options.fetchImpl ?? fetch,
  );
}

async function responseJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const payload = await response.json();
    return payload && typeof payload === "object" && !Array.isArray(payload)
      ? payload as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object" && !Array.isArray(entry))
    : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

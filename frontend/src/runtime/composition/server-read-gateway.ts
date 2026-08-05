import type {
  GatewayClient,
  GatewayExecuteResult,
  GatewayValidateResult,
} from "../plan-executor/types";

type ServerReadGatewayOptions = {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
};

class ServerReadGateway implements GatewayClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch,
  ) {}

  async validate(
    capabilityId: string,
    parameters: Record<string, string>,
  ): Promise<GatewayValidateResult> {
    const response = await this.request(capabilityId, "validate", parameters);
    if (!response) {
      return { valid: false, errors: ["Gateway returned an invalid response"] };
    }
    return {
      valid: response.success === true,
      traceId: text(response.traceId) || undefined,
      errors: stringArray(response.messages),
    };
  }

  async execute(
    capabilityId: string,
    parameters: Record<string, string>,
  ): Promise<GatewayExecuteResult> {
    const response = await this.request(capabilityId, "execute", parameters);
    if (!response) {
      return {
        success: false,
        errorType: "GATEWAY_INVALID_RESPONSE",
        message: "Gateway returned an invalid response",
      };
    }
    return {
      success: response.success === true,
      traceId: text(response.traceId) || undefined,
      data: record(response.data) ?? {},
      errorType: text(response.errorType) || undefined,
      message: text(response.message) || undefined,
    };
  }

  private async request(
    capabilityId: string,
    operation: "validate" | "execute",
    parameters: Record<string, string>,
  ): Promise<Record<string, unknown> | null> {
    const response = await this.fetchImpl(
      `${this.baseUrl}/capabilities/${encodeURIComponent(capabilityId)}/${operation}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parameters }),
      },
    );
    try {
      return record(await response.json());
    } catch {
      return null;
    }
  }
}

export function createServerReadGateway(
  options: ServerReadGatewayOptions = {},
): GatewayClient {
  const baseUrl = (options.baseUrl
    ?? process.env.SAP_NEXUS_GATEWAY_URL
    ?? `http://127.0.0.1:${process.env.GATEWAY_PORT || "8080"}`
  ).replace(/\/$/, "");
  return new ServerReadGateway(baseUrl, options.fetchImpl ?? fetch);
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (typeof entry === "string") return [entry];
    const message = text(record(entry)?.message);
    return message ? [message] : [];
  });
}

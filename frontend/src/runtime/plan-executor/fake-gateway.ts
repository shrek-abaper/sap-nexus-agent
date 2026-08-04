// frontend/src/runtime/plan-executor/fake-gateway.ts
import type { GatewayClient, GatewayValidateResult, GatewayExecuteResult } from "./types";

type ValidateCall = { capabilityId: string; parameters: Record<string, string> };
type ExecuteCall = { capabilityId: string; parameters: Record<string, string> };

export class FakeGateway implements GatewayClient {
  private validateResults = new Map<string, GatewayValidateResult>();
  private executeResults = new Map<string, GatewayExecuteResult>();
  private readonly delayMs: number;
  readonly validateCalls: ValidateCall[] = [];
  readonly executeCalls: ExecuteCall[] = [];

  constructor(opts?: { delayMs?: number }) {
    this.delayMs = opts?.delayMs ?? 0;
  }

  setValidateResult(capabilityId: string, result: GatewayValidateResult): void {
    this.validateResults.set(capabilityId, result);
  }

  setExecuteResult(capabilityId: string, result: GatewayExecuteResult): void {
    this.executeResults.set(capabilityId, result);
  }

  async validate(capabilityId: string, parameters: Record<string, string>): Promise<GatewayValidateResult> {
    this.validateCalls.push({ capabilityId, parameters });
    if (this.delayMs > 0) await sleep(this.delayMs);
    return this.validateResults.get(capabilityId) ?? { valid: true, traceId: `fake-val-${this.validateCalls.length}` };
  }

  async execute(capabilityId: string, parameters: Record<string, string>): Promise<GatewayExecuteResult> {
    this.executeCalls.push({ capabilityId, parameters });
    if (this.delayMs > 0) await sleep(this.delayMs);
    return (
      this.executeResults.get(capabilityId) ?? {
        success: true,
        traceId: `fake-exec-${this.executeCalls.length}`,
        data: { capabilityId, parameters },
      }
    );
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

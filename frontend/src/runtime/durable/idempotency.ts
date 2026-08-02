import { canonicalJson, sha256Hex } from "./canonical-json";
import type { ContinuationType } from "./types";

export function idempotencyKey(
  runId: string,
  continuationType: ContinuationType,
  params: Record<string, unknown>
): string {
  return `${runId}:${continuationType}:${sha256Hex(canonicalJson(params))}`;
}

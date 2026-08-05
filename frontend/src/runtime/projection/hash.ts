import { canonicalJson, sha256Hex } from "../durable/canonical-json";
import type { ReasoningFact } from "./types";

export function normalizeFacts(facts: ReasoningFact[]): ReasoningFact[] {
  return [...facts].sort((a, b) => {
    const left = [
      a.businessObject,
      a.predicate,
      a.material ?? "",
      a.plant ?? "",
      a.factId,
    ].join("\u0000");
    const right = [
      b.businessObject,
      b.predicate,
      b.material ?? "",
      b.plant ?? "",
      b.factId,
    ].join("\u0000");
    return left < right ? -1 : left > right ? 1 : 0;
  });
}

export function computeOutputHash(
  facts: ReasoningFact[],
  version: string,
  snapshotId: string,
): string {
  return sha256Hex(canonicalJson(normalizeFacts(facts)) + version + snapshotId);
}

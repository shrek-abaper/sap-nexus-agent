import type { WorkbenchOutcome } from "../durable/types";
import { parsePlanGraphV2, validatePlanGraphV2 } from "../plan-executor/plan-graph-v2-parser";
import type { CompositionHandoff } from "./types";

export class CompositionHandoffError extends Error {
  constructor(readonly errorType: string, message: string) {
    super(message);
    this.name = "CompositionHandoffError";
  }
}

export function parseCompositionHandoff(
  outcome: WorkbenchOutcome,
): CompositionHandoff | null {
  const decision = record(outcome.matchDecision);
  if (decision?.decisionType !== "ESCALATE_TO_PLANNER") return null;

  const handoff = record(decision.handoff);
  const snapshotId = text(handoff?.registrySnapshotId);
  const dryRun = record(outcome.dryRun);
  const graph = parsePlanGraphV2(dryRun?.planGraph);
  if (!snapshotId || !graph) {
    throw new CompositionHandoffError(
      "COMPOSITION_PLAN_INVALID",
      "Composition requires a valid PlanGraph v2 and governed snapshot",
    );
  }
  if (graph.snapshotId !== snapshotId) {
    throw new CompositionHandoffError(
      "COMPOSITION_SNAPSHOT_MISMATCH",
      "PlanGraph snapshot does not match the semantic handoff",
    );
  }
  if (array(dryRun?.gaps).length > 0) {
    throw new CompositionHandoffError(
      "COMPOSITION_PLAN_GAPS",
      "Composition PlanGraph has unresolved gaps",
    );
  }
  if (!validatePlanGraphV2(graph, snapshotId).valid) {
    throw new CompositionHandoffError(
      "COMPOSITION_PLAN_INVALID",
      "Composition PlanGraph failed deterministic validation",
    );
  }
  return { graph, snapshotId };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

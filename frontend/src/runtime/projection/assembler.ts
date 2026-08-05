import type { NodeFactRecord, PlanExecutorResult } from "../plan-executor/types";
import type {
  MissingFact,
  ProjectionInput,
  ReasoningFact,
  TraceableNodeFactRecord,
} from "./types";
import type { FactBuilderRegistry } from "./fact-builder";

function hasGatewayTrace(record: NodeFactRecord): record is TraceableNodeFactRecord {
  return record.gatewayTraceId !== null;
}

function compareCodeUnits(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

export class ProjectionInputAssembler {
  assemble(result: PlanExecutorResult, builders: FactBuilderRegistry): ProjectionInput {
    const facts: ReasoningFact[] = [];
    const missingFacts: MissingFact[] = [];

    for (const record of [...result.succeededNodeResults].sort((a, b) =>
      compareCodeUnits(a.nodeId, b.nodeId))) {
      if (!hasGatewayTrace(record)) {
        for (const factType of record.producesFactTypes) {
          missingFacts.push({ factType, reason: "missing_gateway_trace" });
        }
        continue;
      }
      const builder = builders.resolve(record.capabilityId);
      if (!builder) {
        for (const factType of record.producesFactTypes) {
          missingFacts.push({ factType, reason: "no_fact_builder" });
        }
        continue;
      }
      facts.push(...builder.build(record));
    }

    const failedNodes = [...result.failed, ...result.timedOut, ...result.cancelled].sort();
    let earliestEpoch: number | null = null;
    for (const fact of facts) {
      const epoch = Date.parse(fact.asOf);
      if (earliestEpoch === null || epoch < earliestEpoch) earliestEpoch = epoch;
    }
    const asOf = earliestEpoch === null ? "" : new Date(earliestEpoch).toISOString();

    return {
      facts,
      planExecutionRecord: {
        runId: result.runId,
        snapshotId: result.snapshotId,
        asOf,
        succeededNodes: [...result.succeeded].sort(),
        failedNodes,
        missingFacts,
        nodeLedgerSummary: Object.entries(result.nodeLedger)
          .sort(([left], [right]) => compareCodeUnits(left, right))
          .map(([nodeId, entry]) => ({
            nodeId,
            state: entry.state,
            ...(entry.state === "SUCCEEDED" ? { nodeExecutedAt: entry.updatedAt } : {}),
          })),
      },
    };
  }
}

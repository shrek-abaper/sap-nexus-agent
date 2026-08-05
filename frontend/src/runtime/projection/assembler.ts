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

export class ProjectionInputAssembler {
  assemble(result: PlanExecutorResult, builders: FactBuilderRegistry): ProjectionInput {
    const facts: ReasoningFact[] = [];
    const missingFacts: MissingFact[] = [];

    for (const record of [...result.succeededNodeResults].sort((a, b) =>
      a.nodeId.localeCompare(b.nodeId))) {
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
    const asOf = facts.length > 0
      ? new Date(Math.min(...facts.map((fact) => Date.parse(fact.asOf)))).toISOString()
      : "";

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
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([nodeId, entry]) => ({
            nodeId,
            state: entry.state,
            ...(entry.state === "SUCCEEDED" ? { nodeExecutedAt: entry.updatedAt } : {}),
          })),
      },
    };
  }
}

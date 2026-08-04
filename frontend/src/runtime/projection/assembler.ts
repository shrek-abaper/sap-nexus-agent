import type { PlanExecutorResult } from "../plan-executor/types";
import type { MissingFact, ProjectionInput, ReasoningFact } from "./types";
import type { FactBuilderRegistry } from "./fact-builder";

export class ProjectionInputAssembler {
  assemble(result: PlanExecutorResult, builders: FactBuilderRegistry): ProjectionInput {
    const facts: ReasoningFact[] = [];
    const missingFacts: MissingFact[] = [];

    for (const record of [...result.succeededNodeResults].sort((a, b) =>
      a.nodeId.localeCompare(b.nodeId))) {
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
    const asOf = facts.map((fact) => fact.asOf).sort()[0] ?? "";

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

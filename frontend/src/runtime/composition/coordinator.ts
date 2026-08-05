import type { DurableRunStore } from "../durable/types";
import { createNarrativeEnvelope } from "../narrative/narrative";
import { PlanExecutor } from "../plan-executor/plan-executor";
import type { GatewayClient, ParameterBinding, PlanNodeV2 } from "../plan-executor/types";
import { projectPlanEvidenceEvents } from "../plan-evidence/event-projector";
import { ProjectionInputAssembler } from "../projection/assembler";
import { createMaterialSupplyFactBuilderRegistry } from "../projection/fact-builder";
import { createOutputProjectionRegistry } from "../projection/material-supply-snapshot";
import { RecommendationDecisionEngine } from "../recommendation/decision-engine";
import { RuleSetRegistry } from "../recommendation/rule-set-registry";
import type {
  DecisionConstraints,
  DecisionRegistrySnapshot,
  MaterialShortageRuleSet,
} from "../recommendation/types";
import { compositionEvidenceObjects } from "./evidence";
import type { CompositionInput, CompositionOutcome } from "./types";

type CompositionCoordinatorDependencies = {
  store: DurableRunStore;
  gateway: GatewayClient;
  workerId: string;
  now?: () => string;
};

export class CompositionCoordinator {
  private readonly now: () => string;

  constructor(private readonly dependencies: CompositionCoordinatorDependencies) {
    this.now = dependencies.now ?? (() => new Date().toISOString());
  }

  async execute(input: CompositionInput): Promise<CompositionOutcome> {
    const run = await this.dependencies.store.load(input.runId);
    if (!run || run.principalId !== input.principal.principalId) {
      throw new Error("Composition run not found");
    }
    const { graph, snapshotId } = input.handoff;
    const execution = await new PlanExecutor(
      this.dependencies.store,
      this.dependencies.gateway,
      this.dependencies.workerId,
    ).execute(graph, input.runId, snapshotId);
    const projectionInput = new ProjectionInputAssembler().assemble(
      execution,
      createMaterialSupplyFactBuilderRegistry(),
    );
    const projection = createOutputProjectionRegistry()
      .resolve("material-supply-snapshot", "1.0.0")
      .project(projectionInput);
    const ruleSetRegistry = new RuleSetRegistry(snapshotId);
    ruleSetRegistry.register(materialShortageRuleSet(snapshotId));
    const recommendation = new RecommendationDecisionEngine(ruleSetRegistry).decide({
      registrySnapshot: decisionRegistrySnapshot(snapshotId),
      projection,
      ruleSetRef: { ruleSetId: "material-shortage-pr", version: "1.0.0" },
      constraints: actionConstraints(graph.nodes.find((node) =>
        graph.actionPartition.includes(node.nodeId))),
      evaluatedAt: this.now(),
    });
    const proposalState = recommendation.actionProposal
      ? {
          status: "pending_approval" as const,
          proposalId: recommendation.actionProposal.proposalId,
          stateRef: `proposal:${recommendation.actionProposal.proposalId}`,
        }
      : {
          status: "none" as const,
          stateRef: `recommendation:${recommendation.recommendationId}`,
        };
    const narrative = await createNarrativeEnvelope({
      locale: input.locale ?? "zh-CN",
      facts: projectionInput.facts,
      projection,
      recommendation,
      proposalState,
    });
    const objects = compositionEvidenceObjects({
      snapshotId,
      graph,
      execution,
      facts: projectionInput.facts,
      projection,
      recommendation,
      narrative,
    });
    const latest = await this.dependencies.store.load(input.runId);
    if (!latest) throw new Error("Composition run not found");
    const events = projectPlanEvidenceEvents({
      runId: input.runId,
      traceId: input.traceId,
      snapshotId,
      startSequence: latest.events.length + 1,
      objects,
    });
    for (const event of events) {
      await this.dependencies.store.appendEvent(input.runId, event);
    }

    const actionGovernanceInput = recommendation.actionProposal
      ? {
          runId: input.runId,
          traceId: input.traceId,
          principal: input.principal,
          plan: graph,
          planExecution: projectionInput.planExecutionRecord,
          projection,
          recommendation,
          capabilityVersion: "2.1.0",
          capabilityStatus: "active",
          createdAt: this.now(),
          expiresAt: new Date(Date.parse(this.now()) + 10 * 60_000).toISOString(),
        }
      : undefined;
    if (!actionGovernanceInput) {
      const current = await this.dependencies.store.load(input.runId);
      if (!current) throw new Error("Composition run not found");
      await this.dependencies.store.appendEvent(input.runId, {
        runId: input.runId,
        traceId: input.traceId,
        snapshotId,
        sequence: current.events.length + 1,
        timestamp: this.now(),
        type: "run_completed",
        state: "completed",
        hitlState: "approval_not_required",
      });
    }
    return {
      execution,
      facts: projectionInput.facts,
      projection,
      recommendation,
      narrative,
      events,
      actionGovernanceInput,
    };
  }
}

function materialShortageRuleSet(snapshotId: string): MaterialShortageRuleSet {
  return {
    ruleSetId: "material-shortage-pr",
    version: "1.0.0",
    registrySnapshotId: snapshotId,
    inputProjection: { projectionId: "material-supply-snapshot", version: "1.0.0" },
    requiredConstraints: ["requiredQuantity", "targetDate", "purchasingGroup"],
    maxProjectionAgeMs: 86_400_000,
    actionCapabilityId: "MM.PR.CreateDraft",
    strategy: "material-shortage",
  };
}

function decisionRegistrySnapshot(snapshotId: string): DecisionRegistrySnapshot {
  return {
    snapshotId,
    actionCapabilities: [{
      capabilityId: "MM.PR.CreateDraft",
      kind: "Action",
      status: "active",
      sideEffect: "sap_write",
      requiresApproval: true,
      approvalPolicy: "human_required",
      requiredParameters: [
        "material", "plant", "quantity", "unit", "delivery_date", "purchasing_group",
      ],
    }],
  };
}

function actionConstraints(node?: PlanNodeV2): DecisionConstraints {
  if (!node || node.capabilityId !== "MM.PR.CreateDraft" || !node.governance.requiresApproval) {
    return {};
  }
  const values = new Map(node.parameterBindings.flatMap((binding) => {
    const value = literalValue(binding);
    return value === null ? [] : [[binding.parameterName, value] as const];
  }));
  const quantity = Number(values.get("quantity"));
  return {
    ...(Number.isFinite(quantity) && quantity > 0 ? { requiredQuantity: quantity } : {}),
    ...(values.get("delivery_date") ? { targetDate: values.get("delivery_date") } : {}),
    ...(values.get("purchasing_group") ? { purchasingGroup: values.get("purchasing_group") } : {}),
  };
}

function literalValue(binding: ParameterBinding): string | null {
  return binding.source.kind === "literal" ? binding.source.value : null;
}

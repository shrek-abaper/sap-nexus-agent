import type { PlanGraphV2 } from "../plan-executor/types";
import type { ActionGovernanceInput } from "../action-governance/action-governance";
import type { AgentRunEvent } from "../run-event-schema";
import type { NarrativeEnvelope, NarrativeLocale } from "../narrative/types";
import type { PlanExecutorResult } from "../plan-executor/types";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";
import type { TrustedPrincipal } from "../principal/types";

export type CompositionHandoff = {
  graph: PlanGraphV2;
  snapshotId: string;
};

export type CompositionInput = {
  runId: string;
  traceId: string;
  principal: TrustedPrincipal;
  handoff: CompositionHandoff;
  locale?: NarrativeLocale;
};

export type CompositionOutcome = {
  execution: PlanExecutorResult;
  facts: ReasoningFact[];
  projection: MaterialSupplySnapshot;
  recommendation: RecommendationPlan;
  narrative: NarrativeEnvelope;
  events: AgentRunEvent[];
  actionGovernanceInput?: ActionGovernanceInput;
};

import { canonicalJson, sha256Hex } from "../durable/canonical-json";
import type { ApprovalDecision, DurableRunStore, WorkbenchOutcome } from "../durable/types";
import { projectPlanEvidenceEvents, type PlanEvidenceObject } from "../plan-evidence/event-projector";
import type { TrustedPrincipal } from "../principal/types";
import type { PlanGraphV2 } from "../plan-executor/types";
import type { MaterialSupplySnapshot, PlanExecutionRecord } from "../projection/types";
import type { ActionProposalParameters, ParameterSource, RecommendationPlan } from "../recommendation/types";
import type { JsonValue } from "../../shared/types/artifacts";

export type PlanApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "revoked"
  | "executing"
  | "executed"
  | "failed";

export type ActionGovernanceInput = {
  runId: string;
  traceId: string;
  principal: TrustedPrincipal;
  plan: PlanGraphV2;
  planExecution: PlanExecutionRecord;
  projection: MaterialSupplySnapshot;
  recommendation: RecommendationPlan;
  capabilityVersion: string;
  capabilityStatus: string;
  createdAt: string;
  expiresAt: string;
};

export type PlanApprovalRecord = {
  approvalId: string;
  runId: string;
  traceId: string;
  planId: string;
  planHash: string;
  snapshotId: string;
  actionNodeId: string;
  capabilityId: "MM.PR.CreateDraft";
  capabilityVersion: string;
  parameterSnapshotHash: string;
  parameters: Record<string, string>;
  parameterSources: Record<string, ParameterSource[]>;
  factSetHash: string;
  factRefs: string[];
  projectionRef: {
    projectionId: string;
    version: string;
    outputHash: string;
  };
  ruleSetRefs: string[];
  ruleSetHash: string;
  proposalId: string;
  proposalHash: string;
  limitations: RecommendationPlan["limitations"];
  subjectHash: string;
  principalId: string;
  tenantId: string;
  role: TrustedPrincipal["role"];
  dataScopeHash: string;
  confirmingPrincipalId: string | null;
  decidedAt: string | null;
  createdAt: string;
  expiresAt: string;
  revokedAt: string | null;
  revocationReason: string | null;
  separationOfDutyResult: "not_applicable";
  status: PlanApprovalStatus;
};

export type ApprovalValidation = {
  valid: boolean;
  errorType?: string;
  message?: string;
};

export type ActionGatewayRequest = {
  capabilityId: "MM.PR.CreateDraft";
  parameters: Record<string, string>;
  approvalId: string;
  parameterSnapshotHash: string;
  registrySnapshotId: string;
  capabilityVersion: string;
  approvalSubjectHash: string;
};

export type ActionGatewayResult = {
  success: boolean;
  traceId?: string;
  data?: Record<string, unknown>;
  returnMessages?: Array<Record<string, unknown>>;
  errorType?: string;
  message?: string;
};

export interface ActionGateway {
  approve(record: PlanApprovalRecord): Promise<void>;
  execute(request: ActionGatewayRequest): Promise<ActionGatewayResult>;
}

type SubjectBinding = {
  runId: string;
  traceId: string;
  planId: string;
  planHash: string;
  snapshotId: string;
  actionNodeId: string;
  capabilityId: "MM.PR.CreateDraft";
  capabilityVersion: string;
  parameterSnapshotHash: string;
  parameters: Record<string, string>;
  parameterSources: Record<string, ParameterSource[]>;
  factSetHash: string;
  factRefs: string[];
  projectionRef: PlanApprovalRecord["projectionRef"];
  ruleSetRefs: string[];
  ruleSetHash: string;
  proposalId: string;
  proposalHash: string;
  limitations: RecommendationPlan["limitations"];
  principalId: string;
  tenantId: string;
  role: TrustedPrincipal["role"];
  dataScopeHash: string;
};

type DurableActionEnvelope = {
  schema: "sap-nexus.plan-action-governance.v1";
  input: ActionGovernanceInput;
};

type DurableActionState = {
  envelope: DurableActionEnvelope;
  record: PlanApprovalRecord;
  runDecision?: ApprovalDecision;
};

export class ActionGovernanceError extends Error {
  constructor(readonly errorType: string, message: string) {
    super(message);
    this.name = "ActionGovernanceError";
  }
}

export function createPlanApprovalRecord(input: ActionGovernanceInput): PlanApprovalRecord {
  const binding = buildSubjectBinding(input);
  const subjectHash = hash(binding);
  const approvalId = `approval_${hash({ subjectHash, createdAt: input.createdAt }).slice(0, 24)}`;
  assertTimestampOrder(input.createdAt, input.expiresAt);
  return {
    approvalId,
    ...binding,
    subjectHash,
    confirmingPrincipalId: null,
    decidedAt: null,
    createdAt: input.createdAt,
    expiresAt: input.expiresAt,
    revokedAt: null,
    revocationReason: null,
    separationOfDutyResult: "not_applicable",
    status: "pending",
  };
}

export function decidePlanApproval(
  record: PlanApprovalRecord,
  decision: "approve" | "reject",
  principal: TrustedPrincipal,
  decidedAt: string,
): PlanApprovalRecord {
  assertRunOwner(record, principal);
  if (record.status !== "pending") {
    throw new ActionGovernanceError("APPROVAL_CONFLICT", "Only a pending approval can be decided");
  }
  if (isExpired(record, decidedAt)) {
    throw new ActionGovernanceError("APPROVAL_EXPIRED", "Approval expired before the human decision");
  }
  return {
    ...record,
    confirmingPrincipalId: principal.principalId,
    decidedAt,
    status: decision === "approve" ? "approved" : "rejected",
  };
}

export function revokePlanApproval(
  record: PlanApprovalRecord,
  principal: TrustedPrincipal,
  reason: string,
  revokedAt: string,
): PlanApprovalRecord {
  assertRunOwner(record, principal);
  if (!reason.trim()) {
    throw new ActionGovernanceError("APPROVAL_REVOCATION_INVALID", "Revocation reason is required");
  }
  if (record.status !== "pending" && record.status !== "approved") {
    throw new ActionGovernanceError("APPROVAL_CONFLICT", "Only pending or approved approval can be revoked");
  }
  return {
    ...record,
    status: "revoked",
    revokedAt,
    revocationReason: reason,
  };
}

export function hasDurablePlanActionEnvelope(outcome?: WorkbenchOutcome): boolean {
  return actionEnvelope(outcome) !== null;
}

export function planApprovalOwnership(
  outcome: WorkbenchOutcome | undefined,
  principal: TrustedPrincipal,
): boolean | null {
  const record = planApprovalRecord(outcome);
  if (!record || typeof record.planId !== "string" || typeof record.subjectHash !== "string") {
    return null;
  }
  return record.principalId === principal.principalId
    && record.tenantId === principal.dataScope.tenantId
    && record.role === principal.role
    && record.dataScopeHash === hash(principal.dataScope);
}

export function validatePlanApproval(
  record: PlanApprovalRecord,
  current: ActionGovernanceInput,
  principal: TrustedPrincipal,
  now: string,
): ApprovalValidation {
  if (record.principalId !== principal.principalId
      || record.tenantId !== principal.dataScope.tenantId
      || record.role !== principal.role
      || record.dataScopeHash !== hash(principal.dataScope)) {
    return invalid("APPROVAL_PRINCIPAL_MISMATCH", "Approval is not owned by the confirming principal");
  }
  if (record.status === "revoked") {
    return invalid("APPROVAL_REVOKED", "Approval was revoked");
  }
  if (record.status === "rejected") {
    return invalid("APPROVAL_REJECTED", "Approval was rejected");
  }
  if (record.status !== "approved") {
    return invalid("APPROVAL_REQUIRED", "Approval is not approved");
  }
  if (record.confirmingPrincipalId !== principal.principalId) {
    return invalid("APPROVAL_PRINCIPAL_MISMATCH", "Human confirmation principal does not own the run");
  }
  if (isExpired(record, now)) {
    return invalid("APPROVAL_EXPIRED", "Approval expired before continuation");
  }
  let currentBinding: SubjectBinding;
  try {
    currentBinding = buildSubjectBinding(current);
  } catch (error) {
    return invalid(
      error instanceof ActionGovernanceError ? error.errorType : "APPROVAL_SUBJECT_INVALID",
      error instanceof Error ? error.message : "Approval subject is invalid",
    );
  }
  if (currentBinding.principalId !== record.principalId
      || currentBinding.tenantId !== record.tenantId
      || currentBinding.dataScopeHash !== record.dataScopeHash) {
    return invalid("APPROVAL_PRINCIPAL_MISMATCH", "Current run principal differs from the approved subject");
  }
  if (currentBinding.snapshotId !== record.snapshotId) {
    return invalid("APPROVAL_SNAPSHOT_MISMATCH", "Registry snapshot drifted after approval");
  }
  if (hash(currentBinding) !== record.subjectHash) {
    return invalid("APPROVAL_SUBJECT_MISMATCH", "Plan, facts, rules, proposal, capability or parameters drifted after approval");
  }
  return { valid: true };
}

export class PlanActionContinuation {
  private static readonly LEASE_TTL_MS = 60_000;
  private readonly leaseOwnerId: string;

  constructor(
    private readonly store: DurableRunStore,
    private readonly gateway: ActionGateway,
    workerId: string,
  ) {
    this.leaseOwnerId = `${workerId}:plan-action:${crypto.randomUUID()}`;
  }

  async prepare(input: ActionGovernanceInput): Promise<PlanApprovalRecord> {
    const run = await this.store.load(input.runId);
    if (!run || run.principalId !== input.principal.principalId) {
      throw new ActionGovernanceError("APPROVAL_RUN_NOT_FOUND", "Agent run not found");
    }
    const existing = planApprovalRecord(run.pendingOutcome);
    if (existing) {
      throw new ActionGovernanceError("APPROVAL_CONFLICT", "Agent run already has an Action approval");
    }

    const record = createPlanApprovalRecord(input);
    const envelope = durableEnvelope(input);
    await this.store.appendPendingOutcome(input.runId, approvalOutcome("awaiting_approval", record, envelope));
    await this.appendEvidence(
      input.runId,
      input.traceId,
      input.plan.snapshotId,
      preparationEvidence(input, record),
      true,
    );
    return record;
  }

  async recordDecision(
    runId: string,
    approvalId: string,
    decision: ApprovalDecision,
    principal: TrustedPrincipal,
    decidedAt: string,
  ): Promise<WorkbenchOutcome> {
    const lease = await this.store.claim(runId, this.leaseOwnerId, PlanActionContinuation.LEASE_TTL_MS);
    if (lease.status === "rejected") {
      throw new ActionGovernanceError("ACTION_CONTINUATION_IN_PROGRESS", "Another worker owns this Action continuation");
    }
    try {
      const state = await this.loadDurableState(runId, approvalId, principal);
      if (state.record.status !== "pending") {
        if (decision === "approve" && (state.record.status === "executed" || state.record.status === "failed")) {
          const completed = await this.store.lookupExecuted(continuationKey(state.record));
          if (completed) return completed;
        }
        if (decision === "approve" && state.record.status === "executing") {
          return approvalOutcome("in_progress", state.record, state.envelope, "ACTION_CONTINUATION_IN_PROGRESS", "Action execution is already in progress");
        }
        const expected = decision === "approve" ? "approved" : "rejected";
        if (state.record.status === expected && state.runDecision === decision) {
          return approvalOutcome(expected, state.record, state.envelope);
        }
        throw new ActionGovernanceError("APPROVAL_CONFLICT", "Action approval was already decided");
      }

      let decided: PlanApprovalRecord;
      try {
        decided = decidePlanApproval(state.record, decision, principal, decidedAt);
      } catch (error) {
        if (!(error instanceof ActionGovernanceError) || error.errorType !== "APPROVAL_EXPIRED") throw error;
        const expired = { ...state.record, status: "expired" as const };
        const outcome = approvalOutcome("expired", expired, state.envelope, error.errorType, error.message);
        await this.store.appendPendingOutcome(runId, outcome);
        await this.appendEvidence(runId, expired.traceId, expired.snapshotId, [approvalEvidence(expired)]);
        await this.appendFailure(runId, error.errorType, error.message);
        return outcome;
      }

      await this.store.appendDecision(runId, decision);
      const outcome = approvalOutcome(
        decided.status,
        decided,
        state.envelope,
        decision === "reject" ? "APPROVAL_REJECTED" : undefined,
        decision === "reject" ? "Action approval was rejected" : undefined,
      );
      await this.store.appendPendingOutcome(runId, outcome);
      await this.appendEvidence(runId, decided.traceId, decided.snapshotId, [approvalEvidence(decided)]);
      if (decision === "reject") {
        await this.appendFailure(runId, "APPROVAL_REJECTED", "Action approval was rejected");
      }
      return outcome;
    } finally {
      await this.store.release(runId, this.leaseOwnerId);
    }
  }

  async executeDurable(
    runId: string,
    approvalId: string,
    principal: TrustedPrincipal,
    now: string,
  ): Promise<WorkbenchOutcome> {
    let state: DurableActionState;
    try {
      state = await this.loadDurableState(runId, approvalId, principal);
    } catch (error) {
      const outcome: WorkbenchOutcome = {
        status: "blocked",
        errorType: error instanceof ActionGovernanceError ? error.errorType : "APPROVAL_SUBJECT_INVALID",
        message: error instanceof Error ? error.message : "Durable Action approval state is invalid",
      };
      const run = await this.store.load(runId);
      const record = planApprovalRecord(run?.pendingOutcome);
      const envelope = actionEnvelope(run?.pendingOutcome);
      if (record) outcome.approvalRecord = plainRecord(record);
      if (envelope) outcome.data = { actionGovernance: envelope };
      await this.store.appendPendingOutcome(runId, outcome);
      await this.appendFailure(runId, outcome.errorType ?? "APPROVAL_SUBJECT_INVALID", outcome.message ?? "Action continuation was blocked");
      return outcome;
    }
    const completed = await this.store.lookupExecuted(continuationKey(state.record));
    if (completed) return completed;
    return this.execute(state.record, state.envelope.input, principal, now, state.envelope);
  }

  async revokeDurable(
    runId: string,
    approvalId: string,
    principal: TrustedPrincipal,
    reason: string,
    revokedAt: string,
  ): Promise<WorkbenchOutcome> {
    const lease = await this.store.claim(runId, this.leaseOwnerId, PlanActionContinuation.LEASE_TTL_MS);
    if (lease.status === "rejected") {
      throw new ActionGovernanceError("ACTION_CONTINUATION_IN_PROGRESS", "Another worker owns this Action continuation");
    }
    try {
      const state = await this.loadDurableState(runId, approvalId, principal);
      const revoked = revokePlanApproval(state.record, principal, reason, revokedAt);
      const outcome = approvalOutcome("revoked", revoked, state.envelope);
      await this.store.appendPendingOutcome(runId, outcome);
      await this.appendEvidence(runId, revoked.traceId, revoked.snapshotId, [approvalEvidence(revoked)]);
      return outcome;
    } finally {
      await this.store.release(runId, this.leaseOwnerId);
    }
  }

  async execute(
    record: PlanApprovalRecord,
    current: ActionGovernanceInput,
    principal: TrustedPrincipal,
    now: string,
    envelope?: DurableActionEnvelope,
  ): Promise<WorkbenchOutcome> {
    const validation = validatePlanApproval(record, current, principal, now);
    if (!validation.valid) {
      const outcome = blockedOutcome(record, validation);
      if (envelope) outcome.data = { actionGovernance: envelope };
      await this.store.appendPendingOutcome(record.runId, outcome);
      await this.appendFailure(record.runId, outcome.errorType ?? "APPROVAL_REQUIRED", outcome.message ?? "Action continuation was blocked");
      return outcome;
    }

    const key = continuationKey(record);
    const completed = await this.store.lookupExecuted(key);
    if (completed) return completed;

    const lease = await this.store.claim(record.runId, this.leaseOwnerId, PlanActionContinuation.LEASE_TTL_MS);
    if (lease.status === "rejected") {
      return {
        status: "in_progress",
        errorType: "ACTION_CONTINUATION_IN_PROGRESS",
        message: "Another worker owns this Action continuation",
        approvalRecord: plainRecord(record),
      };
    }

    try {
      const recovered = await this.store.lookupExecuted(key);
      if (recovered) return recovered;

      const executing: PlanApprovalRecord = { ...record, status: "executing" };
      await this.store.appendPendingOutcome(record.runId, {
        status: "executing",
        approvalRecord: plainRecord(executing),
        data: envelope ? { actionGovernance: envelope } : undefined,
      });
      await this.appendEvidence(record.runId, record.traceId, record.snapshotId, [actionEvidence(executing)]);
      await this.gateway.approve(record);
      const actionResult = await this.gateway.execute({
        capabilityId: record.capabilityId,
        parameters: record.parameters,
        approvalId: record.approvalId,
        parameterSnapshotHash: record.parameterSnapshotHash,
        registrySnapshotId: record.snapshotId,
        capabilityVersion: record.capabilityVersion,
        approvalSubjectHash: record.subjectHash,
      });
      const terminal: PlanApprovalRecord = {
        ...record,
        status: actionResult.success ? "executed" : "failed",
      };
      const actionResultRecord = {
        success: actionResult.success,
        traceId: actionResult.traceId,
        data: actionResult.data ?? {},
        returnMessages: actionResult.returnMessages ?? [],
        errorType: actionResult.errorType,
      };
      const outcome: WorkbenchOutcome = {
        status: actionResult.success ? "executed" : "failure",
        errorType: actionResult.errorType,
        message: actionResult.message,
        gatewayTraceId: actionResult.traceId,
        executionResult: actionResultRecord,
        actionResult: actionResultRecord,
        approvalRecord: plainRecord(terminal),
        data: envelope
          ? { actionGovernance: envelope, actionResult: actionResultRecord }
          : { actionResult: actionResultRecord },
      };
      await this.store.appendPendingOutcome(record.runId, outcome);
      await this.store.markExecuted(key, outcome);
      await this.appendEvidence(record.runId, record.traceId, record.snapshotId, [
        actionEvidence(terminal, actionResultRecord),
      ]);
      if (actionResult.success) {
        await this.appendCompletion(record.runId, record.traceId, record.snapshotId);
      } else {
        await this.appendFailure(
          record.runId,
          actionResult.errorType ?? "ACTION_EXECUTION_FAILED",
          actionResult.message ?? "Action execution failed",
          "executing",
        );
      }
      return outcome;
    } finally {
      await this.store.release(record.runId, this.leaseOwnerId);
    }
  }

  private async loadDurableState(
    runId: string,
    approvalId: string,
    principal: TrustedPrincipal,
  ): Promise<DurableActionState> {
    const run = await this.store.load(runId);
    if (!run || run.principalId !== principal.principalId) {
      throw new ActionGovernanceError("APPROVAL_RUN_NOT_FOUND", "Agent run not found");
    }
    const envelope = actionEnvelope(run.pendingOutcome);
    const record = planApprovalRecord(run.pendingOutcome);
    if (!envelope || !record || record.approvalId !== approvalId) {
      throw new ActionGovernanceError("APPROVAL_SUBJECT_INVALID", "Durable Action approval state is incomplete");
    }
    assertDurableSubject(record, envelope.input);
    assertRunOwner(record, principal);
    return { envelope, record, runDecision: run.decision };
  }

  private async appendEvidence(
    runId: string,
    traceId: string,
    snapshotId: string,
    objects: PlanEvidenceObject[],
    skipExisting = false,
  ): Promise<void> {
    const run = await this.store.load(runId);
    if (!run) throw new ActionGovernanceError("APPROVAL_RUN_NOT_FOUND", "Agent run not found");
    const existingRefs = new Set(run.events.flatMap((event) => event.objectRefs?.map((ref) => ref.ref) ?? []));
    const newObjects = skipExisting
      ? objects.filter((object) => !existingRefs.has(object.ref))
      : objects;
    if (newObjects.length === 0) return;
    const events = projectPlanEvidenceEvents({
      runId,
      traceId,
      snapshotId,
      startSequence: run.events.length + 1,
      objects: newObjects,
    });
    for (const event of events) {
      await this.store.appendEvent(runId, event);
    }
  }

  private async appendCompletion(runId: string, traceId: string, snapshotId: string): Promise<void> {
    const run = await this.store.load(runId);
    if (!run) throw new ActionGovernanceError("APPROVAL_RUN_NOT_FOUND", "Agent run not found");
    await this.store.appendEvent(runId, {
      runId,
      traceId,
      snapshotId,
      sequence: run.events.length + 1,
      timestamp: new Date().toISOString(),
      type: "run_completed",
      state: "completed",
      hitlState: "approved",
    });
  }

  private async appendFailure(
    runId: string,
    errorType: string,
    message: string,
    stage: "approval_checked" | "executing" = "approval_checked",
  ): Promise<void> {
    const run = await this.store.load(runId);
    if (!run) throw new ActionGovernanceError("APPROVAL_RUN_NOT_FOUND", "Agent run not found");
    await this.store.appendEvent(runId, {
      runId,
      sequence: run.events.length + 1,
      timestamp: new Date().toISOString(),
      type: "run_failed",
      state: "failed",
      error: { errorType, message, stage },
    });
  }
}

function buildSubjectBinding(input: ActionGovernanceInput): SubjectBinding {
  requireText(input.runId, "runId");
  requireText(input.traceId, "traceId");
  requireText(input.principal.principalId, "principalId");
  requireText(input.principal.dataScope.tenantId, "tenantId");
  requireText(input.capabilityVersion, "capabilityVersion");
  if (input.capabilityStatus !== "active") {
    throw new ActionGovernanceError("APPROVAL_CAPABILITY_INACTIVE", "Action capability must be active");
  }
  const snapshotId = input.plan.snapshotId;
  requireText(snapshotId, "snapshotId");
  if (input.plan.actionPartition.length !== 1) {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_INVALID", "Plan must contain exactly one Action node");
  }
  const actionNodeId = input.plan.actionPartition[0];
  const actionNode = input.plan.nodes.find((node) => node.nodeId === actionNodeId);
  const proposal = input.recommendation.actionProposal;
  if (!actionNode || !actionNode.governance.requiresApproval || actionNode.capabilityId !== "MM.PR.CreateDraft") {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_INVALID", "Action partition must resolve to governed MM.PR.CreateDraft");
  }
  if (!proposal || proposal.capabilityId !== actionNode.capabilityId || proposal.status !== "pending_approval") {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_INVALID", "Recommendation must contain the single governed Action proposal");
  }
  if (input.planExecution.runId !== input.runId
      || input.planExecution.snapshotId !== snapshotId
      || input.projection.snapshotId !== snapshotId
      || input.recommendation.snapshotId !== snapshotId
      || proposal.snapshotId !== snapshotId) {
    throw new ActionGovernanceError("APPROVAL_SNAPSHOT_MISMATCH", "Approval inputs must share one run and snapshot");
  }
  if (input.planExecution.failedNodes.length > 0
      || input.planExecution.missingFacts.length > 0
      || input.projection.completeness !== "complete"
      || input.projection.failedNodes.length > 0
      || input.projection.missingFacts.length > 0) {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_INCOMPLETE", "READ evidence must be complete before approval");
  }
  for (const nodeId of input.plan.readPartition) {
    if (!input.planExecution.succeededNodes.includes(nodeId)) {
      throw new ActionGovernanceError("APPROVAL_SUBJECT_INCOMPLETE", `READ node did not succeed: ${nodeId}`);
    }
  }
  if (input.recommendation.status !== "RECOMMEND"
      || input.recommendation.projectionRef.projectionId !== input.projection.projectionId
      || input.recommendation.projectionRef.version !== input.projection.projectionVersion
      || input.recommendation.projectionRef.outputHash !== input.projection.outputHash
      || proposal.projectionRef.projectionId !== input.projection.projectionId
      || proposal.projectionRef.version !== input.projection.projectionVersion
      || proposal.projectionRef.outputHash !== input.projection.outputHash) {
    throw new ActionGovernanceError("APPROVAL_PROJECTION_MISMATCH", "Recommendation/proposal projection binding is invalid");
  }
  const factIds = new Set(input.projection.facts.map((fact) => fact.factId));
  if (proposal.factsUsed.length === 0 || proposal.factsUsed.some((factId) => !factIds.has(factId))) {
    throw new ActionGovernanceError("APPROVAL_FACT_MISMATCH", "Proposal references unknown governed facts");
  }
  const ruleSetRefs = sortedUnique(input.recommendation.ruleSetRefs);
  if (ruleSetRefs.length === 0
      || canonicalJson(ruleSetRefs) !== canonicalJson(sortedUnique(proposal.ruleSetRefs))) {
    throw new ActionGovernanceError("APPROVAL_RULE_MISMATCH", "Recommendation/proposal RuleSet refs differ");
  }
  requireText(proposal.proposalId, "proposalId");
  requireText(proposal.proposalHash, "proposalHash");
  const parameters = normalizeParameters(proposal.parameters);
  return {
    runId: input.runId,
    traceId: input.traceId,
    planId: input.plan.planId,
    planHash: hash(input.plan),
    snapshotId,
    actionNodeId,
    capabilityId: "MM.PR.CreateDraft",
    capabilityVersion: input.capabilityVersion,
    parameterSnapshotHash: `sha256:${hash(parameters)}`,
    parameters,
    parameterSources: proposal.parameterSources,
    factSetHash: hash([...input.projection.facts].sort((left, right) => compare(left.factId, right.factId))),
    factRefs: sortedUnique(proposal.factsUsed),
    projectionRef: {
      projectionId: input.projection.projectionId,
      version: input.projection.projectionVersion,
      outputHash: input.projection.outputHash,
    },
    ruleSetRefs,
    ruleSetHash: hash(ruleSetRefs),
    proposalId: proposal.proposalId,
    proposalHash: proposal.proposalHash,
    limitations: input.recommendation.limitations,
    principalId: input.principal.principalId,
    tenantId: input.principal.dataScope.tenantId,
    role: input.principal.role,
    dataScopeHash: hash(input.principal.dataScope),
  };
}

function normalizeParameters(parameters: ActionProposalParameters): Record<string, string> {
  const normalized = Object.fromEntries(
    Object.entries(parameters).map(([key, value]) => [key, String(value)]),
  );
  const required = ["material", "plant", "quantity", "unit", "delivery_date", "purchasing_group"];
  if (required.some((key) => !normalized[key])) {
    throw new ActionGovernanceError("APPROVAL_PARAMETER_INVALID", "All Action parameters must be explicit");
  }
  return normalized;
}

function durableEnvelope(input: ActionGovernanceInput): DurableActionEnvelope {
  return { schema: "sap-nexus.plan-action-governance.v1", input };
}

function actionEnvelope(outcome?: WorkbenchOutcome): DurableActionEnvelope | null {
  const data = objectValue(outcome?.data);
  const value = objectValue(data?.actionGovernance);
  const input = objectValue(value?.input);
  return value?.schema === "sap-nexus.plan-action-governance.v1" && input
    ? value as DurableActionEnvelope
    : null;
}

function planApprovalRecord(outcome?: WorkbenchOutcome): PlanApprovalRecord | null {
  const value = objectValue(outcome?.approvalRecord);
  return value ? value as PlanApprovalRecord : null;
}

function approvalOutcome(
  status: string,
  record: PlanApprovalRecord,
  envelope: DurableActionEnvelope,
  errorType?: string,
  message?: string,
): WorkbenchOutcome {
  return {
    status,
    errorType,
    message,
    approvalRecord: plainRecord(record),
    data: { actionGovernance: envelope },
  };
}

function assertDurableSubject(record: PlanApprovalRecord, input: ActionGovernanceInput): void {
  let expected: PlanApprovalRecord;
  try {
    expected = createPlanApprovalRecord(input);
  } catch (error) {
    throw new ActionGovernanceError(
      "APPROVAL_SUBJECT_MISMATCH",
      error instanceof Error ? error.message : "Durable Action subject is invalid",
    );
  }
  const statuses: PlanApprovalStatus[] = [
    "pending", "approved", "rejected", "expired", "revoked", "executing", "executed", "failed",
  ];
  if (!statuses.includes(record.status)) {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_MISMATCH", "Durable approval status is invalid");
  }
  const immutableRecord: PlanApprovalRecord = {
    ...record,
    confirmingPrincipalId: null,
    decidedAt: null,
    revokedAt: null,
    revocationReason: null,
    status: "pending",
  };
  if (canonicalJson(immutableRecord) !== canonicalJson(expected)) {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_MISMATCH", "Durable Action subject differs from its authoritative inputs");
  }
}

function proposalEvidence(input: ActionGovernanceInput): PlanEvidenceObject {
  const proposal = input.recommendation.actionProposal;
  if (!proposal) {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_INVALID", "Action proposal is required");
  }
  return {
    ref: proposal.proposalId,
    kind: "proposal",
    snapshotId: input.plan.snapshotId,
    payload: jsonValue(proposal),
  };
}

function preparationEvidence(
  input: ActionGovernanceInput,
  record: PlanApprovalRecord,
): PlanEvidenceObject[] {
  const ledger = new Map(input.planExecution.nodeLedgerSummary.map((entry) => [entry.nodeId, entry]));
  const plan: PlanEvidenceObject = {
    ref: input.plan.planId,
    kind: "plan",
    snapshotId: input.plan.snapshotId,
    payload: jsonValue(input.plan),
  };
  const nodes: PlanEvidenceObject[] = input.plan.nodes.map((node) => {
    const execution = ledger.get(node.nodeId);
    return {
      ref: node.nodeId,
      kind: "node",
      snapshotId: input.plan.snapshotId,
      payload: jsonValue({
        nodeId: node.nodeId,
        capabilityId: node.capabilityId,
        state: execution?.state ?? "PENDING",
        updatedAt: execution?.nodeExecutedAt,
        dependencies: input.plan.edges
          .filter((edge) => edge.toNodeId === node.nodeId)
          .map((edge) => edge.fromNodeId),
        producesFactTypes: node.producesFactTypes,
      }),
    };
  });
  const facts: PlanEvidenceObject[] = input.projection.facts.map((fact) => ({
    ref: fact.factId,
    kind: "fact",
    snapshotId: input.plan.snapshotId,
    payload: jsonValue({
      factId: fact.factId,
      agentTraceId: fact.agentTraceId,
      traceId: fact.traceId,
      gatewayTraceId: fact.gatewayTraceId,
      domain: fact.domain,
      businessObject: fact.businessObject,
      predicate: fact.predicate,
      value: fact.value,
      unit: fact.unit,
      deterministic: fact.deterministic,
      confidence: fact.confidence,
      material: fact.material,
      plant: fact.plant,
      asOf: fact.asOf,
      sourceSummary: fact.source,
      evidenceSummary: fact.evidence,
    }),
  }));
  return [
    plan,
    ...nodes,
    ...facts,
    {
      ref: input.projection.projectionId,
      kind: "projection",
      snapshotId: input.plan.snapshotId,
      payload: jsonValue(input.projection),
    },
    {
      ref: input.recommendation.recommendationId,
      kind: "recommendation",
      snapshotId: input.plan.snapshotId,
      payload: jsonValue(input.recommendation),
    },
    proposalEvidence(input),
    approvalEvidence(record),
  ];
}

function approvalEvidence(record: PlanApprovalRecord): PlanEvidenceObject {
  return {
    ref: record.approvalId,
    kind: "approval",
    snapshotId: record.snapshotId,
    payload: jsonValue({
      approvalId: record.approvalId,
      runId: record.runId,
      traceId: record.traceId,
      planId: record.planId,
      planHash: record.planHash,
      actionNodeId: record.actionNodeId,
      proposalId: record.proposalId,
      snapshotId: record.snapshotId,
      status: record.status,
      capabilityId: record.capabilityId,
      capabilityVersion: record.capabilityVersion,
      principalId: record.principalId,
      confirmingPrincipalId: record.confirmingPrincipalId,
      parameterSnapshotHash: record.parameterSnapshotHash,
      parameterSources: record.parameterSources,
      factSetHash: record.factSetHash,
      factRefs: record.factRefs,
      projectionRef: record.projectionRef,
      ruleSetRefs: record.ruleSetRefs,
      ruleSetHash: record.ruleSetHash,
      proposalHash: record.proposalHash,
      subjectHash: record.subjectHash,
      parameters: record.parameters,
      limitations: record.limitations,
      separationOfDutyResult: record.separationOfDutyResult,
      createdAt: record.createdAt,
      expiresAt: record.expiresAt,
      decidedAt: record.decidedAt,
      revokedAt: record.revokedAt,
      revocationReason: record.revocationReason,
    }),
  };
}

function actionEvidence(
  record: PlanApprovalRecord,
  result?: Record<string, unknown>,
): PlanEvidenceObject {
  return {
    ref: `action:${record.approvalId}`,
    kind: "action",
    snapshotId: record.snapshotId,
    payload: jsonValue({
      actionId: `action:${record.approvalId}`,
      proposalId: record.proposalId,
      approvalId: record.approvalId,
      snapshotId: record.snapshotId,
      status: record.status,
      capabilityId: record.capabilityId,
      resultSummary: result
        ? { success: result.success, errorType: result.errorType, returnMessageCount: Array.isArray(result.returnMessages) ? result.returnMessages.length : 0 }
        : { phase: "claiming_gateway" },
      gatewayTraceId: typeof result?.traceId === "string" ? result.traceId : undefined,
      traceId: record.traceId,
      executedAt: record.status === "executed" || record.status === "failed" ? new Date().toISOString() : undefined,
      idempotencyKey: continuationKey(record),
      executionHash: hash(result ?? { approvalId: record.approvalId, status: record.status }),
    }),
  };
}

function jsonValue(value: unknown): JsonValue {
  return JSON.parse(JSON.stringify(value)) as JsonValue;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function continuationKey(record: PlanApprovalRecord): string {
  return `plan-action:${record.approvalId}:${record.proposalHash}:${record.parameterSnapshotHash}`;
}

function blockedOutcome(record: PlanApprovalRecord, validation: ApprovalValidation): WorkbenchOutcome {
  return {
    status: "blocked",
    errorType: validation.errorType ?? "APPROVAL_REQUIRED",
    message: validation.message ?? "Action continuation was blocked",
    approvalRecord: plainRecord(record),
  };
}

function plainRecord(record: PlanApprovalRecord): Record<string, unknown> {
  return { ...record };
}

function assertRunOwner(record: PlanApprovalRecord, principal: TrustedPrincipal): void {
  if (record.principalId !== principal.principalId
      || record.tenantId !== principal.dataScope.tenantId
      || record.role !== principal.role
      || record.dataScopeHash !== hash(principal.dataScope)) {
    throw new ActionGovernanceError("APPROVAL_PRINCIPAL_MISMATCH", "Decision principal does not own the run");
  }
}

function assertTimestampOrder(createdAt: string, expiresAt: string): void {
  const created = Date.parse(createdAt);
  const expires = Date.parse(expiresAt);
  if (!Number.isFinite(created) || !Number.isFinite(expires) || expires <= created) {
    throw new ActionGovernanceError("APPROVAL_EXPIRY_INVALID", "Approval timestamps are invalid");
  }
}

function isExpired(record: PlanApprovalRecord, now: string): boolean {
  const nowValue = Date.parse(now);
  const expires = Date.parse(record.expiresAt);
  return !Number.isFinite(nowValue) || !Number.isFinite(expires) || nowValue >= expires;
}

function requireText(value: string, field: string): void {
  if (!value.trim()) {
    throw new ActionGovernanceError("APPROVAL_SUBJECT_INVALID", `${field} is required`);
  }
}

function sortedUnique(values: string[]): string[] {
  return [...new Set(values)].sort(compare);
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function hash(value: unknown): string {
  return sha256Hex(canonicalJson(value));
}

function invalid(errorType: string, message: string): ApprovalValidation {
  return { valid: false, errorType, message };
}

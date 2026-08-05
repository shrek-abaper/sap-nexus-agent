import { canonicalJson } from "../durable/canonical-json";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";
import type {
  NarrativeClaim,
  NarrativeContentItem,
  NarrativeEnvelope,
  NarrativeGenerationOptions,
  NarrativeGroundingMetrics,
  NarrativeInputProjection,
  NarrativeLimitation,
  NarrativeLocale,
  NarrativeModel,
  NarrativePrompt,
  NarrativeProposalStatus,
  NarrativeSourceInput,
} from "./types";

export class NarrativeInputError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "NarrativeInputError";
  }
}

const completenessLabels = {
  "zh-CN": {
    complete: "数据完整",
    partial: "数据部分完整",
    incomplete: "数据不完整",
  },
  en: {
    complete: "data complete",
    partial: "data partial",
    incomplete: "data incomplete",
  },
} as const;

const recommendationLabels = {
  "zh-CN": {
    RECOMMEND: "建议",
    NO_ACTION: "无需操作",
    CLARIFY: "需要澄清",
    INSUFFICIENT_INPUT: "输入不足",
  },
  en: {
    RECOMMEND: "recommendation available",
    NO_ACTION: "no action",
    CLARIFY: "clarification required",
    INSUFFICIENT_INPUT: "insufficient input",
  },
} as const;

const proposalStateLabels = {
  "zh-CN": {
    none: "无 proposal",
    pending_approval: "待审批",
    approved: "已批准",
    executed: "已执行",
    failed: "执行失败",
  },
  en: {
    none: "no proposal",
    pending_approval: "pending approval",
    approved: "approved",
    executed: "executed",
    failed: "failed",
  },
} as const;

function sortedUnique(values: string[]): string[] {
  return [...new Set(values)].sort();
}

function encoded(value: string): string {
  return encodeURIComponent(value);
}

function sortFacts<T extends { factId: string }>(facts: T[]): T[] {
  return [...facts].sort((left, right) => left.factId.localeCompare(right.factId));
}

function assertNonEmpty(value: string, code: string, field: string): void {
  if (value.trim().length === 0) {
    throw new NarrativeInputError(code, `${field} must be non-empty`);
  }
}

function assertUniqueFacts(facts: ReasoningFact[]): void {
  const ids = facts.map((fact) => fact.factId);
  if (ids.some((id) => id.trim().length === 0) || new Set(ids).size !== ids.length) {
    throw new NarrativeInputError(
      "NARRATIVE_FACT_ID_INVALID",
      "facts must have unique non-empty factId values",
    );
  }
}

function projectionRefMatches(
  projection: MaterialSupplySnapshot,
  ref: RecommendationPlan["projectionRef"],
): boolean {
  return ref.projectionId === projection.projectionId
    && ref.version === projection.projectionVersion
    && ref.outputHash === projection.outputHash;
}

function validateInput(input: NarrativeSourceInput): void {
  assertUniqueFacts(input.facts);
  assertNonEmpty(input.projection.snapshotId, "NARRATIVE_SNAPSHOT_INVALID", "snapshotId");
  assertNonEmpty(input.projection.outputHash, "NARRATIVE_PROJECTION_INVALID", "outputHash");
  assertNonEmpty(
    input.recommendation.recommendationId,
    "NARRATIVE_RECOMMENDATION_INVALID",
    "recommendationId",
  );
  assertNonEmpty(
    input.proposalState.stateRef,
    "NARRATIVE_PROPOSAL_STATE_INVALID",
    "stateRef",
  );

  if (canonicalJson(sortFacts(input.facts))
    !== canonicalJson(sortFacts(input.projection.facts))) {
    throw new NarrativeInputError(
      "NARRATIVE_FACT_PROJECTION_MISMATCH",
      "facts must match the facts carried by the projection",
    );
  }
  if (input.recommendation.snapshotId !== input.projection.snapshotId
    || !projectionRefMatches(input.projection, input.recommendation.projectionRef)) {
    throw new NarrativeInputError(
      "NARRATIVE_RECOMMENDATION_PROJECTION_MISMATCH",
      "recommendation must reference the supplied projection and snapshot",
    );
  }

  const proposal = input.recommendation.actionProposal;
  if (!proposal) {
    if (input.proposalState.status !== "none" || input.proposalState.proposalId !== undefined) {
      throw new NarrativeInputError(
        "NARRATIVE_PROPOSAL_STATE_MISMATCH",
        "proposal state must be none when the recommendation has no proposal",
      );
    }
    return;
  }
  if (proposal.snapshotId !== input.projection.snapshotId
    || !projectionRefMatches(input.projection, proposal.projectionRef)
    || input.proposalState.status === "none"
    || input.proposalState.proposalId !== proposal.proposalId) {
    throw new NarrativeInputError(
      "NARRATIVE_PROPOSAL_STATE_MISMATCH",
      "proposal state must reference the supplied recommendation proposal",
    );
  }
}

function item(
  sourceKind: NarrativeContentItem["sourceKind"],
  sourceRef: string,
  evidenceRefs: string[],
  templateText: string,
): NarrativeContentItem {
  const refs = sortedUnique(evidenceRefs);
  if (refs.length === 0) {
    throw new NarrativeInputError(
      "NARRATIVE_EVIDENCE_MISSING",
      `content item ${sourceRef} has no evidence references`,
    );
  }
  return {
    claimId: `claim:${sourceKind}:${encoded(sourceRef)}`,
    sourceKind,
    sourceRef,
    evidenceRefs: refs,
    templateText,
  };
}

function assertUniqueItems(items: NarrativeContentItem[]): void {
  const claimIds = items.map((entry) => entry.claimId);
  if (new Set(claimIds).size !== claimIds.length) {
    throw new NarrativeInputError(
      "NARRATIVE_CONTENT_ID_DUPLICATE",
      "narrative content items must have unique claim identities",
    );
  }
}

function factText(fact: ReasoningFact, locale: NarrativeLocale): string {
  const value = fact.value === null ? "null" : String(fact.value);
  const unit = fact.unit ?? "-";
  const material = fact.material ?? "-";
  const plant = fact.plant ?? "-";
  if (locale === "zh-CN") {
    return `事实 ${fact.factId}：物料 ${material}、工厂 ${plant} 的 ${fact.predicate} 为 ${value} ${unit}，时间 ${fact.asOf}。`;
  }
  return `Fact ${fact.factId}: ${fact.predicate} for material ${material} at plant ${plant} is ${value} ${unit} as of ${fact.asOf}.`;
}

function limitationText(
  limitation: NarrativeLimitation,
  locale: NarrativeLocale,
): string {
  return locale === "zh-CN"
    ? `限制 ${limitation.code}：${limitation.detail}。`
    : `Limitation ${limitation.code}: ${limitation.detail}.`;
}

function projectionLimitations(input: NarrativeSourceInput): NarrativeLimitation[] {
  const projectionRef = `projection:${input.projection.outputHash}`;
  const limitations: NarrativeLimitation[] = input.projection.limitations.map((entry) => ({
    code: `PROJECTION_${entry.kind.toUpperCase()}`,
    detail: entry.detail,
    evidenceRefs: [`${projectionRef}:limitation:${entry.kind}:${encoded(entry.detail)}`],
  }));
  limitations.push(...input.projection.missingFacts.map((entry) => ({
    code: "PROJECTION_MISSING_FACT",
    detail: `${entry.factType}:${entry.reason}`,
    evidenceRefs: [`${projectionRef}:missing:${encoded(entry.factType)}:${encoded(entry.reason)}`],
  })));
  limitations.push(...input.projection.failedNodes.map((nodeId) => ({
    code: "PROJECTION_FAILED_NODE",
    detail: nodeId,
    evidenceRefs: [`${projectionRef}:failed-node:${encoded(nodeId)}`],
  })));
  limitations.push(...input.recommendation.limitations.map((entry) => ({
    code: entry.code,
    detail: entry.detail,
    evidenceRefs: sortedUnique([
      `recommendation:${input.recommendation.recommendationId}:limitation:${encoded(entry.code)}`,
      ...entry.sourceRefs,
    ]),
  })));
  return limitations.sort((left, right) =>
    `${left.code}:${left.detail}`.localeCompare(`${right.code}:${right.detail}`));
}

export function projectNarrativeInput(
  input: NarrativeSourceInput,
): NarrativeInputProjection {
  validateInput(input);
  const projectionRef = `projection:${input.projection.outputHash}`;
  const recommendationRef = `recommendation:${input.recommendation.recommendationId}`;
  const proposal = input.recommendation.actionProposal;
  const proposalRef = proposal ? `proposal:${proposal.proposalId}` : null;
  const items: NarrativeContentItem[] = [];

  for (const fact of sortFacts(input.facts)) {
    const factRef = `fact:${fact.factId}`;
    items.push(item("fact", factRef, [factRef], factText(fact, input.locale)));
  }

  const completeness = completenessLabels[input.locale][input.projection.completeness];
  const completenessText = input.locale === "zh-CN"
    ? `Projection ${input.projection.projectionId}@${input.projection.projectionVersion} ${completeness}，时间 ${input.projection.asOf}。`
    : `Projection ${input.projection.projectionId}@${input.projection.projectionVersion} is ${completeness} as of ${input.projection.asOf}.`;
  items.push(item(
    "projection",
    `${projectionRef}:completeness`,
    [`${projectionRef}:completeness`],
    completenessText,
  ));

  for (const freshness of [...input.projection.sourceFreshness].sort((left, right) =>
    left.nodeId.localeCompare(right.nodeId))) {
    const freshnessRef = `${projectionRef}:freshness:${encoded(freshness.nodeId)}`;
    const text = input.locale === "zh-CN"
      ? `节点 ${freshness.nodeId} 数据时间 ${freshness.dataAsOf}，执行时间 ${freshness.nodeExecutedAt}。`
      : `Node ${freshness.nodeId} data is as of ${freshness.dataAsOf}; executed at ${freshness.nodeExecutedAt}.`;
    items.push(item("projection", freshnessRef, [freshnessRef], text));
  }

  const recommendationText = input.locale === "zh-CN"
    ? `Recommendation ${input.recommendation.recommendationId} 状态为 ${recommendationLabels[input.locale][input.recommendation.status]}，代码 ${input.recommendation.summaryCode}。`
    : `Recommendation ${input.recommendation.recommendationId} is ${recommendationLabels[input.locale][input.recommendation.status]} with code ${input.recommendation.summaryCode}.`;
  items.push(item(
    "recommendation",
    recommendationRef,
    [recommendationRef, projectionRef],
    recommendationText,
  ));

  for (const rule of [...input.recommendation.rules].sort((left, right) =>
    `${left.ruleSetRef}:${left.ruleId}`.localeCompare(`${right.ruleSetRef}:${right.ruleId}`))) {
    const ruleRef = `rule:${rule.ruleSetRef}:${rule.ruleId}`;
    const text = input.locale === "zh-CN"
      ? `规则 ${rule.ruleId}（${rule.ruleSetRef}）${rule.triggered ? "已命中" : "未命中"}。`
      : `Rule ${rule.ruleId} (${rule.ruleSetRef}) was ${rule.triggered ? "triggered" : "not triggered"}.`;
    items.push(item("rule", ruleRef, [ruleRef, recommendationRef], text));
  }

  const limitations = projectionLimitations(input);
  for (const limitation of limitations) {
    items.push(item(
      "projection",
      `limitation:${limitation.code}:${encoded(limitation.detail)}`,
      limitation.evidenceRefs,
      limitationText(limitation, input.locale),
    ));
  }

  const stateText = proposalStateLabels[input.locale][input.proposalState.status];
  const proposalText = input.locale === "zh-CN"
    ? `Proposal ${proposal?.proposalId ?? "-"} 状态为 ${stateText}。`
    : `Proposal ${proposal?.proposalId ?? "-"} is ${stateText}.`;
  items.push(item(
    "proposal_state",
    `proposal-state:${input.proposalState.stateRef}`,
    [input.proposalState.stateRef, proposalRef ?? recommendationRef],
    proposalText,
  ));
  assertUniqueItems(items);

  return {
    locale: input.locale,
    completeness: input.projection.completeness,
    items,
    limitations,
    recommendationRef,
    proposalRef,
    approvalState: input.proposalState.status,
    stateEvidenceRef: input.proposalState.stateRef,
  };
}

function buildPrompt(projection: NarrativeInputProjection): NarrativePrompt {
  return {
    system: "Rewrite only the supplied claim text. Keep every identity and reference unchanged. Return strict JSON only.",
    user: JSON.stringify({
      schema: "sap-nexus.narrative-candidate.v1",
      locale: projection.locale,
      claims: projection.items.map((entry) => ({
        claimId: entry.claimId,
        sourceRef: entry.sourceRef,
        evidenceRefs: entry.evidenceRefs,
        providedText: entry.templateText,
      })),
    }),
  };
}

type CandidateClaim = {
  claimId: string;
  sourceRef: string;
  evidenceRefs: string[];
  text: string;
};

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
}

function normalizedClaimText(value: string): string {
  return value
    .normalize("NFKC")
    .trim()
    .replace(/\s+/gu, " ")
    .replace(/[.!?。！？]$/u, "");
}

function parseCandidate(
  raw: string,
  projection: NarrativeInputProjection,
): NarrativeClaim[] | null {
  if (raw.trim().length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  const object = parsed as Record<string, unknown>;
  if (!hasExactKeys(object, ["schema", "claims"])
    || object.schema !== "sap-nexus.narrative-candidate.v1"
    || !Array.isArray(object.claims)
    || object.claims.length !== projection.items.length) {
    return null;
  }

  const candidates = new Map<string, CandidateClaim>();
  for (const entry of object.claims) {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) return null;
    const claim = entry as Record<string, unknown>;
    if (!hasExactKeys(claim, ["claimId", "sourceRef", "evidenceRefs", "text"])
      || typeof claim.claimId !== "string"
      || typeof claim.sourceRef !== "string"
      || !Array.isArray(claim.evidenceRefs)
      || !claim.evidenceRefs.every((ref) => typeof ref === "string")
      || typeof claim.text !== "string"
      || claim.text.trim().length === 0
      || candidates.has(claim.claimId)) {
      return null;
    }
    candidates.set(claim.claimId, claim as unknown as CandidateClaim);
  }

  const result: NarrativeClaim[] = [];
  for (const expected of projection.items) {
    const claim = candidates.get(expected.claimId);
    if (!claim
      || claim.sourceRef !== expected.sourceRef
      || canonicalJson(claim.evidenceRefs) !== canonicalJson(expected.evidenceRefs)
      || normalizedClaimText(claim.text) !== normalizedClaimText(expected.templateText)) {
      return null;
    }
    result.push({
      claimId: expected.claimId,
      sourceRef: expected.sourceRef,
      evidenceRefs: expected.evidenceRefs,
      text: claim.text.trim(),
    });
  }
  return result;
}

function envelopeFromClaims(
  projection: NarrativeInputProjection,
  claims: NarrativeClaim[],
  templateFallbackUsed: boolean,
): NarrativeEnvelope {
  return {
    summary: claims.map((claim) => claim.text).join(" "),
    claims,
    evidenceRefs: sortedUnique(claims.flatMap((claim) => claim.evidenceRefs)),
    limitations: projection.limitations,
    recommendationRef: projection.recommendationRef,
    proposalRef: projection.proposalRef,
    approvalState: projection.approvalState,
    completeness: projection.completeness,
    templateFallbackUsed,
  };
}

function templateEnvelope(projection: NarrativeInputProjection): NarrativeEnvelope {
  return envelopeFromClaims(
    projection,
    projection.items.map((entry) => ({
      claimId: entry.claimId,
      text: entry.templateText,
      sourceRef: entry.sourceRef,
      evidenceRefs: entry.evidenceRefs,
    })),
    true,
  );
}

export async function createNarrativeEnvelope(
  input: NarrativeSourceInput,
  model?: NarrativeModel,
  options: NarrativeGenerationOptions = {},
): Promise<NarrativeEnvelope> {
  const projection = projectNarrativeInput(input);
  const fallback = templateEnvelope(projection);
  if (!model) return fallback;
  const timeoutMs = options.timeoutMs ?? 5_000;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new NarrativeInputError(
      "NARRATIVE_MODEL_TIMEOUT_INVALID",
      "timeoutMs must be a finite positive number",
    );
  }
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    const raw = await Promise.race<string | null>([
      model.generateJson(buildPrompt(projection)),
      new Promise<null>((resolve) => {
        timeout = setTimeout(() => resolve(null), timeoutMs);
      }),
    ]);
    if (raw === null) return fallback;
    const claims = parseCandidate(raw, projection);
    return claims ? envelopeFromClaims(projection, claims, false) : fallback;
  } catch {
    return fallback;
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

export function evaluateNarrativeGrounding(
  envelope: NarrativeEnvelope,
  projection: NarrativeInputProjection,
): NarrativeGroundingMetrics {
  const expected = new Map(projection.items.map((entry) => [entry.claimId, entry]));
  const actual = new Map<string, NarrativeClaim[]>();
  for (const claim of envelope.claims) {
    actual.set(claim.claimId, [...(actual.get(claim.claimId) ?? []), claim]);
  }
  const groundedClaims = projection.items.filter((source) => {
    const matches = actual.get(source.claimId) ?? [];
    return matches.length === 1
      && matches[0].sourceRef === source.sourceRef
      && matches[0].evidenceRefs.length > 0
      && canonicalJson(matches[0].evidenceRefs) === canonicalJson(source.evidenceRefs);
  }).length;
  const totalClaims = Math.max(expected.size, envelope.claims.length);
  const unsupportedClaims = totalClaims - groundedClaims;
  return {
    totalClaims,
    groundedClaims,
    unsupportedClaims,
    claimGroundingRate: totalClaims === 0 ? 1 : groundedClaims / totalClaims,
    unsupportedClaimRate: totalClaims === 0 ? 0 : unsupportedClaims / totalClaims,
  };
}

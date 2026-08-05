import { canonicalJson } from "../durable/canonical-json";
import type { MaterialShortageRuleSet } from "./types";

export type RuleSetRegistryErrorCode =
  | "RULESET_REGISTRY_SNAPSHOT_INVALID"
  | "RULESET_SNAPSHOT_MISMATCH"
  | "RULESET_DECLARATION_INVALID"
  | "RULESET_NOT_REGISTERED"
  | "RULESET_DUPLICATE"
  | "RULESET_CONFLICT";

export class RuleSetRegistryError extends Error {
  constructor(
    readonly code: RuleSetRegistryErrorCode,
    message: string,
    readonly ruleSetId?: string,
    readonly version?: string,
  ) {
    super(message);
    this.name = "RuleSetRegistryError";
  }
}

function declarationIsValid(ruleSet: MaterialShortageRuleSet): boolean {
  const requiredConstraints = new Set(ruleSet.requiredConstraints);
  return ruleSet.ruleSetId.length > 0
    && ruleSet.version.length > 0
    && ruleSet.inputProjection.projectionId.length > 0
    && ruleSet.inputProjection.version.length > 0
    && Number.isFinite(ruleSet.maxProjectionAgeMs)
    && ruleSet.maxProjectionAgeMs > 0
    && ruleSet.requiredConstraints.length === 3
    && requiredConstraints.size === 3
    && requiredConstraints.has("requiredQuantity")
    && requiredConstraints.has("targetDate")
    && requiredConstraints.has("purchasingGroup")
    && ruleSet.actionCapabilityId === "MM.PR.CreateDraft"
    && ruleSet.strategy === "material-shortage";
}

function copyDeclaration(
  ruleSet: MaterialShortageRuleSet,
): MaterialShortageRuleSet {
  return {
    ...ruleSet,
    inputProjection: { ...ruleSet.inputProjection },
    requiredConstraints: [...ruleSet.requiredConstraints],
  };
}

export class RuleSetRegistry {
  private readonly declarations = new Map<
    string,
    Map<string, MaterialShortageRuleSet>
  >();

  constructor(readonly snapshotId: string) {
    if (snapshotId.length === 0) {
      throw new RuleSetRegistryError(
        "RULESET_REGISTRY_SNAPSHOT_INVALID",
        "rule-set registry snapshot id must be non-empty",
      );
    }
  }

  register(ruleSet: MaterialShortageRuleSet): void {
    if (ruleSet.registrySnapshotId !== this.snapshotId) {
      throw new RuleSetRegistryError(
        "RULESET_SNAPSHOT_MISMATCH",
        `rule set snapshot mismatch: ${ruleSet.registrySnapshotId}`,
        ruleSet.ruleSetId,
        ruleSet.version,
      );
    }
    if (!declarationIsValid(ruleSet)) {
      throw new RuleSetRegistryError(
        "RULESET_DECLARATION_INVALID",
        `invalid rule-set declaration: ${ruleSet.ruleSetId}@${ruleSet.version}`,
        ruleSet.ruleSetId,
        ruleSet.version,
      );
    }

    const versions = this.declarations.get(ruleSet.ruleSetId) ?? new Map();
    const existing = versions.get(ruleSet.version);
    if (existing) {
      const code = canonicalJson(existing) === canonicalJson(ruleSet)
        ? "RULESET_DUPLICATE"
        : "RULESET_CONFLICT";
      throw new RuleSetRegistryError(
        code,
        `${code === "RULESET_DUPLICATE" ? "duplicate" : "conflicting"} rule set: ${ruleSet.ruleSetId}@${ruleSet.version}`,
        ruleSet.ruleSetId,
        ruleSet.version,
      );
    }

    versions.set(ruleSet.version, copyDeclaration(ruleSet));
    this.declarations.set(ruleSet.ruleSetId, versions);
  }

  resolve(ruleSetId: string, version: string): MaterialShortageRuleSet {
    const ruleSet = this.declarations.get(ruleSetId)?.get(version);
    if (!ruleSet) {
      throw new RuleSetRegistryError(
        "RULESET_NOT_REGISTERED",
        `rule set not registered: ${ruleSetId}@${version}`,
        ruleSetId,
        version,
      );
    }
    return copyDeclaration(ruleSet);
  }
}

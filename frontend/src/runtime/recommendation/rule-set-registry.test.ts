import { describe, expect, it } from "vitest";
import {
  RuleSetRegistry,
  RuleSetRegistryError,
} from "./rule-set-registry";
import type { MaterialShortageRuleSet } from "./types";

const ruleSet = {
  ruleSetId: "material-shortage-pr",
  version: "1.0.0",
  registrySnapshotId: "snapshot-1",
  inputProjection: {
    projectionId: "material-supply-snapshot",
    version: "1.0.0",
  },
  requiredConstraints: [
    "requiredQuantity",
    "targetDate",
    "purchasingGroup",
  ],
  maxProjectionAgeMs: 86_400_000,
  actionCapabilityId: "MM.PR.CreateDraft",
  strategy: "material-shortage",
} satisfies MaterialShortageRuleSet;

function captureError(operation: () => void): RuleSetRegistryError {
  try {
    operation();
  } catch (error) {
    expect(error).toBeInstanceOf(RuleSetRegistryError);
    return error as RuleSetRegistryError;
  }
  throw new Error("expected RuleSetRegistryError");
}

describe("RuleSetRegistry", () => {
  it("resolves only an exact registered rule-set id and version", () => {
    const registry = new RuleSetRegistry("snapshot-1");
    registry.register(ruleSet);

    expect(registry.resolve("material-shortage-pr", "1.0.0")).toEqual(ruleSet);
    expect(captureError(() => registry.resolve("material-shortage-pr", "2.0.0")))
      .toMatchObject({
        code: "RULESET_NOT_REGISTERED",
        ruleSetId: "material-shortage-pr",
        version: "2.0.0",
      });
    expect(captureError(() => registry.resolve("missing", "1.0.0")))
      .toMatchObject({
        code: "RULESET_NOT_REGISTERED",
        ruleSetId: "missing",
        version: "1.0.0",
      });
  });

  it("distinguishes an exact duplicate from a conflicting tuple", () => {
    const registry = new RuleSetRegistry("snapshot-1");
    registry.register(ruleSet);

    expect(captureError(() => registry.register({ ...ruleSet }))).toMatchObject({
      code: "RULESET_DUPLICATE",
      ruleSetId: "material-shortage-pr",
      version: "1.0.0",
    });
    expect(captureError(() => registry.register({
      ...ruleSet,
      maxProjectionAgeMs: 1,
    }))).toMatchObject({
      code: "RULESET_CONFLICT",
      ruleSetId: "material-shortage-pr",
      version: "1.0.0",
    });
  });

  it.each([
    {
      label: "empty registry snapshot",
      snapshotId: "",
      declaration: ruleSet,
      code: "RULESET_REGISTRY_SNAPSHOT_INVALID",
    },
    {
      label: "mismatched declaration snapshot",
      snapshotId: "snapshot-2",
      declaration: ruleSet,
      code: "RULESET_SNAPSHOT_MISMATCH",
    },
    {
      label: "zero freshness age",
      snapshotId: "snapshot-1",
      declaration: { ...ruleSet, maxProjectionAgeMs: 0 },
      code: "RULESET_DECLARATION_INVALID",
    },
    {
      label: "non-finite freshness age",
      snapshotId: "snapshot-1",
      declaration: { ...ruleSet, maxProjectionAgeMs: Number.POSITIVE_INFINITY },
      code: "RULESET_DECLARATION_INVALID",
    },
    {
      label: "incomplete required constraint declaration",
      snapshotId: "snapshot-1",
      declaration: { ...ruleSet, requiredConstraints: ["targetDate"] },
      code: "RULESET_DECLARATION_INVALID",
    },
    {
      label: "duplicate required constraint declaration",
      snapshotId: "snapshot-1",
      declaration: {
        ...ruleSet,
        requiredConstraints: [
          "requiredQuantity",
          "targetDate",
          "purchasingGroup",
          "purchasingGroup",
        ],
      },
      code: "RULESET_DECLARATION_INVALID",
    },
  ])("rejects $label", ({ snapshotId, declaration, code }) => {
    const operation = () => {
      const registry = new RuleSetRegistry(snapshotId);
      registry.register(declaration as MaterialShortageRuleSet);
    };

    expect(captureError(operation).code).toBe(code);
  });

  it("keeps at-sign-containing tuples distinct", () => {
    const registry = new RuleSetRegistry("snapshot-1");
    const left = { ...ruleSet, ruleSetId: "a@b", version: "c" };
    const right = { ...ruleSet, ruleSetId: "a", version: "b@c" };
    registry.register(left);
    registry.register(right);

    expect(registry.resolve("a@b", "c")).toEqual(left);
    expect(registry.resolve("a", "b@c")).toEqual(right);
  });

  it("does not retain mutable aliases from registered declarations", () => {
    const registry = new RuleSetRegistry("snapshot-1");
    const mutableRuleSet: MaterialShortageRuleSet = {
      ...ruleSet,
      inputProjection: { ...ruleSet.inputProjection },
      requiredConstraints: [...ruleSet.requiredConstraints],
    };
    registry.register(mutableRuleSet);

    mutableRuleSet.maxProjectionAgeMs = 1;
    mutableRuleSet.inputProjection.version = "2.0.0";
    mutableRuleSet.requiredConstraints.pop();

    expect(registry.resolve("material-shortage-pr", "1.0.0")).toEqual(ruleSet);
  });

  it("does not expose mutable aliases when declarations resolve", () => {
    const registry = new RuleSetRegistry("snapshot-1");
    registry.register({
      ...ruleSet,
      inputProjection: { ...ruleSet.inputProjection },
      requiredConstraints: [...ruleSet.requiredConstraints],
    });

    const resolved = registry.resolve("material-shortage-pr", "1.0.0");
    resolved.maxProjectionAgeMs = 1;
    resolved.inputProjection.version = "2.0.0";
    resolved.requiredConstraints.pop();

    expect(registry.resolve("material-shortage-pr", "1.0.0")).toEqual(ruleSet);
  });
});

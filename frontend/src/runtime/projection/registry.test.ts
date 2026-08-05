import { describe, expect, it } from "vitest";
import { OutputProjectionRegistry, ProjectionRegistryError } from "./registry";
import type { OutputProjectionDeclaration } from "./types";

const declaration = {
  projectionId: "material-supply-snapshot",
  version: "1.0.0",
} as OutputProjectionDeclaration;

describe("OutputProjectionRegistry", () => {
  it("resolves only an exact registered id and version", () => {
    const registry = new OutputProjectionRegistry();
    registry.register(declaration);

    expect(registry.resolve("material-supply-snapshot", "1.0.0")).toBe(declaration);
  });

  it.each([
    ["unknown", "1.0.0"],
    ["material-supply-snapshot", "2.0.0"],
  ])("fails closed for %s@%s", (id, version) => {
    const registry = new OutputProjectionRegistry();
    registry.register(declaration);

    expect(() => registry.resolve(id, version)).toThrowError(ProjectionRegistryError);
    try {
      registry.resolve(id, version);
    } catch (error) {
      expect(error).toMatchObject({
        code: "PROJECTION_NOT_REGISTERED",
        projectionId: id,
        version,
      });
    }
  });

  it("rejects duplicate registration", () => {
    const registry = new OutputProjectionRegistry();
    registry.register(declaration);

    expect(() => registry.register(declaration)).toThrowError(/already registered/);
  });

  it("does not resolve a different tuple across an at-sign boundary", () => {
    const registry = new OutputProjectionRegistry();
    registry.register({
      ...declaration,
      projectionId: "a@b",
      version: "c",
    });

    expect(() => registry.resolve("a", "b@c")).toThrowError(ProjectionRegistryError);
  });

  it("registers and resolves distinct tuples across an at-sign boundary", () => {
    const registry = new OutputProjectionRegistry();
    const left = { ...declaration, projectionId: "a@b", version: "c" };
    const right = { ...declaration, projectionId: "a", version: "b@c" };

    registry.register(left);
    registry.register(right);

    expect(registry.resolve("a@b", "c")).toBe(left);
    expect(registry.resolve("a", "b@c")).toBe(right);
  });

  it("rejects an exact duplicate tuple containing at-signs", () => {
    const registry = new OutputProjectionRegistry();
    const withAtSigns = { ...declaration, projectionId: "a@b", version: "c@d" };
    registry.register(withAtSigns);

    expect(() => registry.register({ ...withAtSigns })).toThrowError(/already registered/);
  });
});

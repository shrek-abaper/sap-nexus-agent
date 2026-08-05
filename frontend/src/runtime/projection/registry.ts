import type { OutputProjectionDeclaration } from "./types";

export class ProjectionRegistryError extends Error {
  readonly code = "PROJECTION_NOT_REGISTERED";

  constructor(
    readonly projectionId: string,
    readonly version: string,
  ) {
    super(`projection not registered: ${projectionId}@${version}`);
    this.name = "ProjectionRegistryError";
  }
}

export class OutputProjectionRegistry {
  private readonly declarations = new Map<
    string,
    Map<string, OutputProjectionDeclaration>
  >();

  register(declaration: OutputProjectionDeclaration): void {
    const versions = this.declarations.get(declaration.projectionId) ?? new Map();
    if (versions.has(declaration.version)) {
      throw new Error(
        `projection already registered: ${declaration.projectionId}@${declaration.version}`,
      );
    }

    versions.set(declaration.version, declaration);
    this.declarations.set(declaration.projectionId, versions);
  }

  resolve(projectionId: string, version: string): OutputProjectionDeclaration {
    const declaration = this.declarations.get(projectionId)?.get(version);
    if (!declaration) {
      throw new ProjectionRegistryError(projectionId, version);
    }

    return declaration;
  }
}

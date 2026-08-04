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
  private readonly declarations = new Map<string, OutputProjectionDeclaration>();

  register(declaration: OutputProjectionDeclaration): void {
    const key = this.key(declaration.projectionId, declaration.version);
    if (this.declarations.has(key)) {
      throw new Error(`projection already registered: ${key}`);
    }

    this.declarations.set(key, declaration);
  }

  resolve(projectionId: string, version: string): OutputProjectionDeclaration {
    const declaration = this.declarations.get(this.key(projectionId, version));
    if (!declaration) {
      throw new ProjectionRegistryError(projectionId, version);
    }

    return declaration;
  }

  private key(projectionId: string, version: string): string {
    return `${projectionId}@${version}`;
  }
}

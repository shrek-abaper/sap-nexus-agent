import type { RedactedArtifact } from "../types/artifacts";

export function ArtifactJson({ artifact }: { artifact?: RedactedArtifact }) {
  if (!artifact) {
    return <p className="muted">等待运行产物。</p>;
  }

  return (
    <section className="artifact-card">
      <h3>{artifact.label}</h3>
      <pre>{JSON.stringify(artifact.payload, null, 2)}</pre>
    </section>
  );
}

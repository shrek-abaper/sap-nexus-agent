import type { RedactedArtifact } from "@/shared/types/artifacts";
import { ArtifactJson } from "@/shared/ui/ArtifactJson";

export function ReasoningFactPanel({ artifact }: { artifact?: RedactedArtifact }) {
  return <ArtifactJson artifact={artifact} />;
}

import type { MaturityLevel } from "./types";

export const RELEASE_PROFILE_VERSIONS: Record<MaturityLevel, string> = {
  L1: "1.0.0",
  L2: "1.0.0",
  L3: "1.0.0",
};

export const MATURITY_LEVELS: MaturityLevel[] = ["L1", "L2", "L3"];

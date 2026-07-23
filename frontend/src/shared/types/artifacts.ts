export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type RedactedArtifact = {
  label: string;
  kind:
    | "intent"
    | "capability"
    | "callplan"
    | "validation"
    | "execution-result"
    | "approval"
    | "reasoning-fact"
    | "narrative"
    | "trace";
  payload: JsonValue;
};

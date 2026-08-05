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
    | "trace"
    | "match-decision"
    | "intent-envelope"
    | "capability-recall"
    | "plan-graph"
    | "node-ledger"
    | "fact"
    | "projection"
    | "recommendation"
    | "narrative-envelope"
    | "action-proposal"
    | "approval-record"
    | "action-result";
  payload: JsonValue;
};

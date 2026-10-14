import type { DshSemanticToolResult } from "./types";

/**
 * Pure section model for ontology-analysis tool cards (C3).
 * Kept separate from ToolCallCard.tsx so it is testable without a DOM.
 */

export interface DshOntologyField {
  value: string;
  semanticType: string;
}

export interface DshOntologyFact {
  factTypeRef: string;
  fields: Record<string, DshOntologyField>;
  unit: { field: string; value: string } | null;
}

export interface DshOntologyResultRow {
  groupKey?: Record<string, unknown>;
  measures?: Record<string, { decimal: string; unit: string }>;
}

export interface DshOntologyResult {
  nodeId: string;
  operatorId: string;
  status: string;
  rows: DshOntologyResultRow[];
}

export interface DshOntologyToolResult {
  kind: "ontology-analysis";
  status: string;
  runId: string;
  facts?: DshOntologyFact[];
  results?: DshOntologyResult[];
  gaps?: string[];
  limitations?: string[];
  narrative?: { summary: string; limitations: string[] };
  error?: { errorType: string; message: string };
}

export function isOntologyResult(result: unknown): result is DshOntologyToolResult {
  return (
    typeof result === "object" &&
    result !== null &&
    (result as { kind?: unknown }).kind === "ontology-analysis"
  );
}

export function isSemanticToolResult(result: unknown): result is DshSemanticToolResult {
  return typeof result === "object" && result !== null && !isOntologyResult(result);
}

function factLine(fact: DshOntologyFact): string {
  const suffix = fact.unit ? ` ${fact.unit.value}` : "";
  const values = Object.entries(fact.fields).map(
    ([name, field]) => `${name}=${field.value}${suffix}`,
  );
  return `${fact.factTypeRef}: ${values.join(", ")}`;
}

function resultLine(result: DshOntologyResult): string {
  const rows = result.rows
    .map((row) => {
      const key = row.groupKey ? Object.values(row.groupKey).join("/") : "";
      const measures = row.measures
        ? Object.values(row.measures).map((measure) => `${measure.decimal} ${measure.unit}`).join(", ")
        : "";
      return [key, measures].filter(Boolean).join(": ");
    })
    .join("; ");
  return `${result.operatorId} (${result.status}): ${rows || "(no rows)"}`;
}

export interface OntologySections {
  facts: string[];
  analysis: string[];
  limitations: string[];
}

export function ontologySections(result: DshOntologyToolResult): OntologySections {
  return {
    facts: (result.facts ?? []).map(factLine),
    analysis: (result.results ?? []).map(resultLine),
    limitations: result.limitations ?? [],
  };
}

import type { JsonValue, RedactedArtifact } from "../shared/types/artifacts";

const SENSITIVE_KEY =
  /(^|\b|[._-])(password|passwd|secret|token|api[_-]?key|authorization|cookie|session|private[_-]?key|credential|llm[_-]?api|destination|saprouter|ashost|mshost|gwhost|sysnr|client|user|rawresponse|llmresponse|modelresponse|choices|raw.*llm|\.env)(\b|$|[._-])/i;
const SENSITIVE_VALUE =
  /(password\s*=|passwd\s*=|api[_-]?key\s*=|authorization\s*[:=]|cookie\s*[:=]|session\s*[:=]|bearer\s+|sk-[a-z0-9]|gh[opusr]_[a-z0-9_]+|github_pat_[a-z0-9_]+|xox[abprs]-[a-z0-9-]+|akia[0-9a-z]{12,20}|-----BEGIN [A-Z ]*PRIVATE KEY-----)/i;

export function redactArtifact(artifact: RedactedArtifact): RedactedArtifact {
  return {
    ...artifact,
    payload: redactJson(artifact.payload, "")
  };
}

function redactJson(value: JsonValue, key: string): JsonValue {
  if (SENSITIVE_KEY.test(key)) {
    return "[REDACTED]";
  }

  if (typeof value === "string") {
    return SENSITIVE_VALUE.test(value) ? "[REDACTED]" : value;
  }

  if (Array.isArray(value)) {
    return value.map((entry) => redactJson(entry, key));
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([entryKey, entryValue]) => [entryKey, redactJson(entryValue, entryKey)])
    );
  }

  return value;
}

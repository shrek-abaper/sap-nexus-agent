import { describe, expect, it } from "vitest";
import { redactArtifact } from "../../src/runtime/redaction";

describe("redactArtifact", () => {
  it("masks sensitive keys recursively", () => {
    const redacted = redactArtifact({
      label: "execution",
      kind: "execution-result",
      payload: {
        SAP_PASSWORD: "secret",
        nested: {
          token: "abc",
          destinationConfig: "ashost=internal password=secret"
        }
      }
    });

    expect(JSON.stringify(redacted)).not.toContain("secret");
    expect(JSON.stringify(redacted)).not.toContain("abc");
    expect(JSON.stringify(redacted)).toContain("[REDACTED]");
  });

  it("masks SAP destination aliases, raw LLM containers, and provider tokens", () => {
    const rawValues = [
      "sap.internal.example",
      "SAP_DEMO_USER",
      "jco.internal.example",
      "message-server.internal.example",
      "Bearer live-authorization",
      "raw completion payload",
      "llm response payload",
      "ghp_providersecret",
      "xoxb-providersecret",
      "AKIAIOSFODNN7EXAMPLE"
    ];

    const redacted = redactArtifact({
      label: "execution",
      kind: "execution-result",
      payload: {
        SAP_ASHOST: rawValues[0],
        SAP_USER: rawValues[1],
        "jco.client.ashost": rawValues[2],
        mshost: rawValues[3],
        authorization: rawValues[4],
        rawResponse: { text: rawValues[5], choices: [{ message: "do not display" }] },
        llmResponse: rawValues[6],
        providerTokens: rawValues.slice(7)
      }
    });

    const serialized = JSON.stringify(redacted);
    for (const rawValue of rawValues) {
      expect(serialized).not.toContain(rawValue);
    }
    expect(serialized).toContain("[REDACTED]");
  });

  it("keeps safe trace identifiers", () => {
    const redacted = redactArtifact({
      label: "trace",
      kind: "trace",
      payload: {
        agentTraceId: "agent-123",
        gatewayTraceId: "gw-456",
        capabilityId: "MM.Inventory.GetAvailability"
      }
    });

    expect(JSON.stringify(redacted)).toContain("agent-123");
    expect(JSON.stringify(redacted)).toContain("MM.Inventory.GetAvailability");
  });
});

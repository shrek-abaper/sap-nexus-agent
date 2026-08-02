import { afterEach, describe, expect, it } from "vitest";
import { injectPrincipal, LocalPlaceholderPrincipalInjector, setPrincipalInjectorForTests } from "./principal-injector";
import { PLACEHOLDER_PRINCIPAL } from "./types";

describe("PrincipalInjector", () => {
  afterEach(() => setPrincipalInjectorForTests(null));

  it("LocalPlaceholderPrincipalInjector returns PLACEHOLDER_PRINCIPAL", () => {
    const injector = new LocalPlaceholderPrincipalInjector();
    const request = new Request("http://localhost/api/agent-runs", {
      method: "POST",
      body: JSON.stringify({ query: "test" })
    });
    expect(injector.inject(request)).toEqual(PLACEHOLDER_PRINCIPAL);
  });

  it("injectPrincipal returns placeholder principal by default", () => {
    const request = new Request("http://localhost/api/agent-runs");
    expect(injectPrincipal(request)).toEqual(PLACEHOLDER_PRINCIPAL);
  });

  it("injectPrincipal ignores principal fields in request body (server-owned)", () => {
    const request = new Request("http://localhost/api/agent-runs", {
      method: "POST",
      body: JSON.stringify({
        query: "test",
        principal: { principalId: "attacker-001", role: "admin", dataScope: { tenantId: "evil" } },
        principalId: "attacker-001"
      })
    });
    const principal = injectPrincipal(request);
    expect(principal.principalId).toBe("local-user-0001");
    expect(principal.principalId).not.toBe("attacker-001");
  });

  it("setPrincipalInjectorForTests allows overriding the injector", () => {
    const customPrincipal = { principalId: "test-user", role: "admin" as const, dataScope: { tenantId: "t1" } };
    setPrincipalInjectorForTests({
      inject: () => customPrincipal
    });
    const request = new Request("http://localhost/api/agent-runs");
    expect(injectPrincipal(request)).toEqual(customPrincipal);
  });

  it("setPrincipalInjectorForTests(null) restores default injector", () => {
    setPrincipalInjectorForTests(null);
    const request = new Request("http://localhost/api/agent-runs");
    expect(injectPrincipal(request)).toEqual(PLACEHOLDER_PRINCIPAL);
  });
});

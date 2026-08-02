import { describe, expect, it } from "vitest";
import { PLACEHOLDER_PRINCIPAL } from "./types";
import type { TrustedPrincipal } from "./types";

describe("TrustedPrincipal model", () => {
  it("PLACEHOLDER_PRINCIPAL has v1 placeholder values", () => {
    expect(PLACEHOLDER_PRINCIPAL).toEqual({
      principalId: "local-user-0001",
      role: "operator",
      dataScope: { tenantId: "default" }
    });
  });

  it("TrustedPrincipal satisfies the type contract", () => {
    const principal: TrustedPrincipal = {
      principalId: "user-001",
      role: "admin",
      dataScope: { tenantId: "tenant-a" }
    };
    expect(principal.principalId).toBe("user-001");
    expect(principal.role).toBe("admin");
    expect(principal.dataScope.tenantId).toBe("tenant-a");
  });
});

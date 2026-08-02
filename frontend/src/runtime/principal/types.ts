export type PrincipalRole = "admin" | "operator" | "viewer";

export type DataScope = {
  tenantId: string;
};

export type TrustedPrincipal = {
  principalId: string;
  role: PrincipalRole;
  dataScope: DataScope;
};

export const PLACEHOLDER_PRINCIPAL: TrustedPrincipal = {
  principalId: "local-user-0001",
  role: "operator",
  dataScope: { tenantId: "default" }
};

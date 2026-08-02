import type { TrustedPrincipal } from "./types";
import { PLACEHOLDER_PRINCIPAL } from "./types";

export interface PrincipalInjector {
  inject(request: Request): TrustedPrincipal;
}

export class LocalPlaceholderPrincipalInjector implements PrincipalInjector {
  inject(_request: Request): TrustedPrincipal {
    return PLACEHOLDER_PRINCIPAL;
  }
}

let principalInjector: PrincipalInjector = new LocalPlaceholderPrincipalInjector();

export function injectPrincipal(request: Request): TrustedPrincipal {
  return principalInjector.inject(request);
}

export function setPrincipalInjectorForTests(injector: PrincipalInjector | null): void {
  principalInjector = injector ?? new LocalPlaceholderPrincipalInjector();
}

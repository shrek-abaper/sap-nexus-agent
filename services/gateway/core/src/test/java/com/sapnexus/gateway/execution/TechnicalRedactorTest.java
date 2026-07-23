package com.sapnexus.gateway.execution;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class TechnicalRedactorTest {
    @Test
    void redactsSensitiveTechnicalKeysRecursively() {
        Map<String, Object> redacted = TechnicalRedactor.redactMap(Map.of(
                "password", "secret-password",
                "credentialRef", "sap-prod-credential",
                "headers", Map.of("Authorization", "Bearer token-value"),
                "safe", "value"
        ));

        assertThat(redacted.toString()).doesNotContain("secret-password", "sap-prod-credential", "token-value");
        assertThat(redacted).containsEntry("safe", "value");
    }

    @Test
    void redactsCookieKey() {
        Map<String, Object> redacted = TechnicalRedactor.redactMap(Map.of(
                "cookie", "sap-usercontext=sid%3D100",
                "Set-Cookie", "JSESSIONID=abc123",
                "safe", "value"
        ));

        assertThat(redacted.get("cookie")).isEqualTo("***");
        assertThat(redacted.get("Set-Cookie")).isEqualTo("***");
        assertThat(redacted).containsEntry("safe", "value");
    }

    @Test
    void isSensitiveKeyRecognizesCookie() {
        assertThat(TechnicalRedactor.isSensitiveKey("cookie")).isTrue();
        assertThat(TechnicalRedactor.isSensitiveKey("Cookie")).isTrue();
        assertThat(TechnicalRedactor.isSensitiveKey("set-cookie")).isTrue();
        assertThat(TechnicalRedactor.isSensitiveKey("sap_cookie")).isTrue();
    }

    @Test
    void redactsSensitiveValuesAcrossFreeTextFormats() {
        String redacted = TechnicalRedactor.redactText(
                "destination SAP-PRD unavailable; token: abc123; "
                        + "Authorization: Bearer bearer-secret; "
                        + "Authorization: Basic dXNlcjpwYXNz; "
                        + "\"password\":\"json-secret\"; \"secret\":\"alpha beta\"");

        assertThat(redacted).doesNotContain(
                "SAP-PRD", "abc123", "bearer-secret", "dXNlcjpwYXNz",
                "json-secret", "alpha", "beta");
        assertThat(redacted).contains("destination ***", "token: ***", "Bearer ***");
    }
}

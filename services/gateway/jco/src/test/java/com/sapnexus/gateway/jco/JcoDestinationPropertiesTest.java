package com.sapnexus.gateway.jco;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class JcoDestinationPropertiesTest {
    @Test
    void readinessUsesSapEnvironmentWithoutExposingPassword() {
        JcoDestinationProperties properties = JcoDestinationProperties.from(Map.of(
                "SAP_ASHOST", "sap.example.local",
                "SAP_SYSNR", "00",
                "SAP_CLIENT", "100",
                "SAP_USER", "USER1",
                "SAP_PASSWORD", "secret",
                "SAP_LANG", "ZH",
                "SAP_JCO_LIB_PATH", "/opt/sapjco"
        ));

        assertThat(properties.sapEnvironmentPresent()).isTrue();
        assertThat(properties.jcoConfigured()).isTrue();
        assertThat(properties.safeSummary()).doesNotContain("secret");
        assertThat(properties.safeSummary()).doesNotContain("SAP_PASSWORD");
    }

    @Test
    void missingRequiredEnvironmentIsReportedByKeyOnly() {
        JcoDestinationProperties properties = JcoDestinationProperties.from(Map.of("SAP_USER", "USER1"));

        assertThat(properties.sapEnvironmentPresent()).isFalse();
        assertThat(properties.missingRequiredKeys()).contains("SAP_ASHOST", "SAP_SYSNR", "SAP_CLIENT", "SAP_PASSWORD", "SAP_LANG");
    }
}

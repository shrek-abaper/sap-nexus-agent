package com.sapnexus.gateway.api;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class CapabilityRequestTest {

    @Test
    void detectsNoOverrideForSemanticParameters() {
        CapabilityRequest request = new CapabilityRequest(Map.of(
                "poNumber", "4500000001",
                "vendor", "V001",
                "plant", "1000",
                "material", "MAT-001"
        ));
        assertThat(request.technicalOverrideKeys()).isEmpty();
    }

    @Test
    void detectsNoOverrideForInventorySemanticParameters() {
        CapabilityRequest request = new CapabilityRequest(Map.of(
                "material", "MAT-001",
                "plant", "1000",
                "unit", "EA"
        ));
        assertThat(request.technicalOverrideKeys()).isEmpty();
    }

    @Test
    void detectsNullParametersAsNoOverride() {
        CapabilityRequest request = new CapabilityRequest(null);
        assertThat(request.technicalOverrideKeys()).isEmpty();
    }

    // --- existing JCo / REST / SQL overrides (regression) ---

    @Test
    void detectsRfcNameOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("rfcName", "Z_UNSAFE"));
        assertThat(request.technicalOverrideKeys()).containsExactly("rfcName");
    }

    @Test
    void detectsUrlOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("url", "http://evil"));
        assertThat(request.technicalOverrideKeys()).containsExactly("url");
    }

    @Test
    void detectsCredentialRefOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("credentialRef", "sap-prod"));
        assertThat(request.technicalOverrideKeys()).containsExactly("credentialRef");
    }

    // --- OData-specific override detection ---

    @Test
    void detectsDollarFilterOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("$filter", "PurchaseOrder eq '1'"));
        assertThat(request.technicalOverrideKeys()).containsExactly("$filter");
    }

    @Test
    void detectsFilterStringOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("filterString", "fake"));
        assertThat(request.technicalOverrideKeys()).containsExactly("filterString");
    }

    @Test
    void detectsServicePathOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("servicePath", "/sap/opu/odata"));
        assertThat(request.technicalOverrideKeys()).containsExactly("servicePath");
    }

    @Test
    void detectsServicePathWithUnderscoresOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("service_path", "/sap/opu/odata"));
        assertThat(request.technicalOverrideKeys()).containsExactly("service_path");
    }

    @Test
    void detectsEntitySetOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("entitySet", "PurchaseOrder"));
        assertThat(request.technicalOverrideKeys()).containsExactly("entitySet");
    }

    @Test
    void detectsServiceRefOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("serviceRef", "API_PURCHASEORDER_PROCESS_SRV"));
        assertThat(request.technicalOverrideKeys()).containsExactly("serviceRef");
    }

    @Test
    void detectsSelectFieldsOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("selectFields", "PurchaseOrder,Supplier"));
        assertThat(request.technicalOverrideKeys()).containsExactly("selectFields");
    }

    @Test
    void detectsTopLimitOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("topLimit", 999));
        assertThat(request.technicalOverrideKeys()).containsExactly("topLimit");
    }

    @Test
    void detectsCredentialsOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("credentials", "user:pass"));
        assertThat(request.technicalOverrideKeys()).containsExactly("credentials");
    }

    @Test
    void detectsMultipleOverridesPreservingInsertionOrder() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("poNumber", "4500000001");
        params.put("$filter", "fake");
        params.put("entitySet", "PurchaseOrder");
        params.put("rfcName", "Z_UNSAFE");
        CapabilityRequest request = new CapabilityRequest(params);

        Set<String> overrides = request.technicalOverrideKeys();
        assertThat(overrides).containsExactly("$filter", "entitySet", "rfcName");
    }

    // --- IMPORTANT-1: OData system query options ($select/$top/$skip/$expand/$count) ---

    @Test
    void detectsDollarSelectOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("$select", "sensitive_field"));
        assertThat(request.technicalOverrideKeys()).containsExactly("$select");
    }

    @Test
    void detectsDollarTopOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("$top", 999));
        assertThat(request.technicalOverrideKeys()).containsExactly("$top");
    }

    @Test
    void detectsDollarSkipOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("$skip", 100));
        assertThat(request.technicalOverrideKeys()).containsExactly("$skip");
    }

    @Test
    void detectsDollarExpandOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("$expand", "Vendor"));
        assertThat(request.technicalOverrideKeys()).containsExactly("$expand");
    }

    @Test
    void detectsDollarCountOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("$count", true));
        assertThat(request.technicalOverrideKeys()).containsExactly("$count");
    }

    @Test
    void detectsDollarSystemOptionsAlongsideSemanticParameter() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("poNumber", "4500000001");
        params.put("$select", "sensitive_field");
        params.put("$top", 999);
        CapabilityRequest request = new CapabilityRequest(params);

        Set<String> overrides = request.technicalOverrideKeys();
        assertThat(overrides).containsExactly("$select", "$top");
    }

    // --- MINOR-1: technical security fields (baseUrl/sapClient/csrf/token/authorization/destination) ---

    @Test
    void detectsBaseUrlOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("baseUrl", "http://evil"));
        assertThat(request.technicalOverrideKeys()).containsExactly("baseUrl");
    }

    @Test
    void detectsSapClientOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("sapClient", "100"));
        assertThat(request.technicalOverrideKeys()).containsExactly("sapClient");
    }

    @Test
    void detectsCsrfOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("csrf", "token-value"));
        assertThat(request.technicalOverrideKeys()).containsExactly("csrf");
    }

    @Test
    void detectsTokenOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("token", "bearer-xyz"));
        assertThat(request.technicalOverrideKeys()).containsExactly("token");
    }

    @Test
    void detectsAuthorizationOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("authorization", "Basic xyz"));
        assertThat(request.technicalOverrideKeys()).containsExactly("authorization");
    }

    @Test
    void detectsDestinationOverride() {
        CapabilityRequest request = new CapabilityRequest(Map.of("destination", "sap-prod"));
        assertThat(request.technicalOverrideKeys()).containsExactly("destination");
    }

    @Test
    void detectsTechnicalSecurityFieldsAlongsideSemanticParameter() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("vendor", "V001");
        params.put("baseUrl", "http://evil");
        params.put("token", "bearer-xyz");
        CapabilityRequest request = new CapabilityRequest(params);

        Set<String> overrides = request.technicalOverrideKeys();
        assertThat(overrides).containsExactly("baseUrl", "token");
    }
}

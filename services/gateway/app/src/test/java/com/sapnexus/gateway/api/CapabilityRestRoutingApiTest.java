package com.sapnexus.gateway.api;

import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.rest.Rest2RfcProperties;
import com.sapnexus.gateway.rest.RestJsonTechnicalAdapter;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Integration slice verifying the REST_JSON route coexists with the existing
 * JCo/OData routes: FI.AP.GetOpenItems (REST_JSON) traverses the full controller
 * path (validation -> dispatcher -> adapter) and calls the rest2rfc endpoint.
 */
@WebMvcTest(CapabilityController.class)
@Import(CapabilityRestRoutingApiTest.Config.class)
class CapabilityRestRoutingApiTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void apOpenItemsRouteThroughRestJsonAdapter() throws Exception {
        Config.mockServer.expect(requestTo(
                        "http://localhost:8090/sap/bc/rest2rfc?RFC=BAPI_AP_ACC_GETOPENITEMS&sap-client=800"))
                .andExpect(method(org.springframework.http.HttpMethod.POST))
                .andRespond(withSuccess(
                        "{\"lineitems\":[{\"comp_code\":\"1000\",\"doc_no\":\"5100000001\","
                                + "\"amt_doccur\":125.500,\"currency\":\"CNY\"}],\"return\":[]}",
                        MediaType.APPLICATION_JSON));

        mockMvc.perform(post("/capabilities/{capabilityId}/execute", "FI.AP.GetOpenItems")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"parameters\":{\"vendor\":\"0000100000\",\"companyCode\":\"1000\"}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success", is(true)))
                .andExpect(jsonPath("$.capabilityId", is("FI.AP.GetOpenItems")))
                .andExpect(jsonPath("$.executor.type", is("REST_JSON")))
                .andExpect(jsonPath("$.data.openItems[0].compCode", is("1000")))
                .andExpect(jsonPath("$.data.openItems[0].docNo", is("5100000001")))
                .andExpect(jsonPath("$.data.openItems[0].amtDoccur", is("125.500")));

        Config.mockServer.verify();
    }

    @TestConfiguration
    static class Config {
        static MockRestServiceServer mockServer;

        @Bean
        CapabilityRegistry capabilityRegistry() {
            return new CapabilityRegistry(1, List.of(apOpenItems()));
        }

        @Bean
        BindingRegistry bindingRegistry() {
            return new BindingRegistry(1, List.of(restBinding()));
        }

        @Bean
        com.sapnexus.gateway.approval.ApprovalStore approvalStore() {
            return new com.sapnexus.gateway.approval.InMemoryApprovalStore();
        }

        @Bean
        com.sapnexus.gateway.approval.ApprovalGuard approvalGuard() {
            return new com.sapnexus.gateway.approval.ApprovalGuard();
        }

        @Bean
        Rest2RfcProperties rest2RfcProperties() {
            Rest2RfcProperties.Endpoint endpoint = new Rest2RfcProperties.Endpoint();
            endpoint.setBaseUrl("http://localhost:8090");
            endpoint.setClient("800");
            endpoint.setUser("rest-user");
            endpoint.setPassword("rest-password");
            Rest2RfcProperties properties = new Rest2RfcProperties();
            properties.setSystems(Map.of("sap-sat", endpoint));
            return properties;
        }

        @Bean
        TechnicalExecutionDispatcher technicalExecutionDispatcher(
                CapabilityRegistry registry,
                BindingRegistry bindingRegistry,
                Rest2RfcProperties properties
        ) {
            RestClient.Builder builder = RestClient.builder();
            mockServer = MockRestServiceServer.bindTo(builder).build();
            RestJsonTechnicalAdapter adapter = new RestJsonTechnicalAdapter(
                    registry, bindingRegistry, properties, builder);
            return new TechnicalExecutionDispatcher(Map.of("REST_JSON", adapter));
        }

        private static CapabilityDefinition apOpenItems() {
            return new CapabilityDefinition(
                    "FI.AP.GetOpenItems",
                    "Vendor Open Items",
                    "Read vendor open items.",
                    CapabilityStatus.active,
                    CapabilityKind.Function,
                    "FI",
                    "VendorOpenItem",
                    "sapnexus:FI_AP_GetOpenItems",
                    "sapnexus:VendorOpenItemsReadFunction",
                    List.of(
                            new CapabilityDefinition.InputField(
                                    "vendor", "supplier", "sapnexus:Supplier",
                                    true, "string", 1, 10, "VENDOR"),
                            new CapabilityDefinition.InputField(
                                    "companyCode", "companyCode", "sapnexus:CompanyCode",
                                    true, "string", 1, 4, "COMPANYCODE")
                    ),
                    List.of(),
                    new CapabilityDefinition.Executor(
                            "REST_JSON", "BAPI_AP_ACC_GETOPENITEMS",
                            Map.of("vendor", "VENDOR", "companyCode", "COMPANYCODE",
                                    "keydate", "KEYDATE"),
                            Map.of("openItems", "LINEITEMS", "returnMessages", "RETURN")),
                    new CapabilityDefinition.ExecutorBinding(
                            "REST_JSON", "sap.fi.ap.get-open-items-rest2rfc"),
                    new CapabilityDefinition.Governance(
                            SideEffect.none, false, "not_required", "internal", true)
            );
        }

        private static BindingDefinition restBinding() {
            return new BindingDefinition(
                    "sap.fi.ap.get-open-items-rest2rfc", "REST_JSON",
                    null, null, "POST",
                    Map.of(), null, List.of(),
                    Map.of("sideEffect", "none", "timeoutMs", 30000),
                    "sap-sat", "/sap/bc/rest2rfc",
                    Map.of("mode", "dynamic"),
                    Map.of("mode", "dynamic"),
                    Map.of("type", "basic", "credentialRef", "sap-rest2rfc")
            );
        }
    }
}

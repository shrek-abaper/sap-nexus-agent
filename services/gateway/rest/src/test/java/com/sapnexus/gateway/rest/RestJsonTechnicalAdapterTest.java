package com.sapnexus.gateway.rest;

import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

@SuppressWarnings("unchecked")
class RestJsonTechnicalAdapterTest {

    private static final String BASE_URL = "http://localhost:8090";
    private static final String EXPECTED_URI =
            BASE_URL + "/sap/bc/rest2rfc?RFC=BAPI_AP_ACC_GETOPENITEMS&sap-client=800";
    private static final String CAPABILITY_ID = "FI.AP.GetOpenItems";
    private static final String BINDING_ID = "sap.fi.ap.get-open-items-rest2rfc";
    private static final String SYSTEM_REF = "sap-sat";

    private CapabilityRegistry registry;
    private Rest2RfcProperties properties;
    private RestClient.Builder builder;
    private MockRestServiceServer server;
    private RestJsonTechnicalAdapter adapter;

    @BeforeEach
    void setUp() {
        CapabilityDefinition capability = capability();
        registry = mock(CapabilityRegistry.class);
        when(registry.findEnabled(CAPABILITY_ID)).thenReturn(Optional.of(capability));

        BindingDefinition binding = binding();
        BindingRegistry bindingRegistry = new BindingRegistry(1, List.of(binding));

        properties = new Rest2RfcProperties();
        Rest2RfcProperties.Endpoint endpoint = new Rest2RfcProperties.Endpoint();
        endpoint.setBaseUrl(BASE_URL);
        endpoint.setClient("800");
        endpoint.setUser("rest-user");
        endpoint.setPassword("rest-password");
        properties.setSystems(Map.of(SYSTEM_REF, endpoint));

        builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        adapter = new RestJsonTechnicalAdapter(registry, bindingRegistry, properties, builder);
    }

    private TechnicalExecutionRequest request() {
        return new TechnicalExecutionRequest(
                "trace-001", CAPABILITY_ID, BINDING_ID,
                "REST_JSON", "execute",
                Map.of("vendor", "0000100000", "companyCode", "1000"),
                Map.of(), Map.of()
        );
    }

    // --- success path ---

    @Test
    void openItemsReturnSuccessWithJcoShapeNormalization() {
        server.expect(requestTo(EXPECTED_URI))
                .andExpect(method(HttpMethod.POST))
                .andExpect(header("Authorization", org.hamcrest.Matchers.startsWith("Basic ")))
                .andExpect(jsonPath("$.VENDOR", org.hamcrest.Matchers.is("0000100000")))
                .andExpect(jsonPath("$.COMPANYCODE", org.hamcrest.Matchers.is("1000")))
                .andRespond(withSuccess(
                        "{\"lineitems\":[{"
                                + "\"comp_code\":\"1000\","
                                + "\"doc_no\":\"5100000001\","
                                + "\"amt_doccur\":125.500,"
                                + "\"currency\":\"CNY\","
                                + "\"net_due_date\":\"2026-10-20\","
                                + "\"vendor\":\"0000100000\""
                                + "}],\"return\":[{"
                                + "\"type\":\"\","
                                + "\"id\":\"\","
                                + "\"number\":\"000000\","
                                + "\"message\":\"\","
                                + "\"field\":\"\""
                                + "}]}",
                        MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isTrue();
        assertThat(result.errorType()).isEqualTo(ErrorType.NONE);
        assertThat(result.capabilityId()).isEqualTo(CAPABILITY_ID);
        assertThat(result.bindingId()).isEqualTo(BINDING_ID);
        assertThat(result.executorType()).isEqualTo("REST_JSON");
        assertThat(result.redactionApplied()).isTrue();

        List<Map<String, Object>> openItems =
                (List<Map<String, Object>>) result.data().get("openItems");
        assertThat(openItems).hasSize(1);
        Map<String, Object> row = openItems.get(0);
        assertThat(row.get("compCode")).isEqualTo("1000");
        assertThat(row.get("docNo")).isEqualTo("5100000001");
        assertThat(row.get("amtDoccur")).isEqualTo("125.500");
        assertThat(row.get("netDueDate")).isEqualTo("2026-10-20");

        List<Map<String, Object>> returnMessages =
                (List<Map<String, Object>>) result.data().get("returnMessages");
        assertThat(returnMessages).hasSize(1);

        // rfcName is redacted by the shared redactor contract (same as the JCo path).
        assertThat(result.adapterMetadata().get("rfcName")).isEqualTo("***");
        assertThat(result.adapterMetadata().get("systemRef")).isEqualTo(SYSTEM_REF);
        server.verify();
    }

    @Test
    void emptyLineItemsReturnSuccessWithEmptyList() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withSuccess(
                        "{\"lineitems\":[],\"return\":[]}", MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isTrue();
        assertThat((List<?>) result.data().get("openItems")).isEmpty();
    }

    // --- business errors ---

    @Test
    void http200WithReturnTypeEReturnsBusinessError() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withSuccess(
                        "{\"lineitems\":[],\"return\":[{"
                                + "\"type\":\"E\","
                                + "\"id\":\"F5\","
                                + "\"number\":\"301\","
                                + "\"message\":\"Vendor not found\","
                                + "\"field\":\"VENDOR\""
                                + "}]}",
                        MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
        assertThat(result.messages()).hasSize(1);
        assertThat(result.messages().get(0).message()).contains("Vendor not found");
    }

    @Test
    void http400EmptyBodyReturnsInvalidParameter() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withStatus(HttpStatus.BAD_REQUEST));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.INVALID_PARAMETER);
        assertThat(result.messages().get(0).message()).contains("400");
    }

    @Test
    void http401EmptyBodyReturnsAuthError() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_AUTH_ERROR);
    }

    @Test
    void http404EmptyBodyReturnsCommunicationError() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withStatus(HttpStatus.NOT_FOUND));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMUNICATION_ERROR);
    }

    @Test
    void http422EmptyBodyReturnsBusinessError() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withStatus(HttpStatus.UNPROCESSABLE_ENTITY));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
    }

    @Test
    void http500EmptyBodyReturnsBusinessError() {
        server.expect(requestTo(EXPECTED_URI))
                .andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
    }

    // --- infrastructure ---

    @Test
    void endpointUnreachableReturnsCommunicationError() {
        Rest2RfcProperties.Endpoint endpoint = new Rest2RfcProperties.Endpoint();
        endpoint.setBaseUrl("http://localhost:1");
        endpoint.setUser("rest-user");
        endpoint.setPassword("rest-password");
        Rest2RfcProperties badProps = new Rest2RfcProperties();
        badProps.setSystems(Map.of(SYSTEM_REF, endpoint));

        RestJsonTechnicalAdapter badAdapter = new RestJsonTechnicalAdapter(
                registry,
                new BindingRegistry(1, List.of(binding())),
                badProps, RestClient.builder());

        TechnicalExecutionResult result = badAdapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMUNICATION_ERROR);
    }

    @Test
    void missingBaseUrlFailsClosedWithoutAnyRequest() {
        RestJsonTechnicalAdapter unconfiguredAdapter = new RestJsonTechnicalAdapter(
                registry,
                new BindingRegistry(1, List.of(binding())),
                new Rest2RfcProperties(), RestClient.builder());

        TechnicalExecutionResult result = unconfiguredAdapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMUNICATION_ERROR);
        assertThat(result.messages().get(0).message()).contains("base URL");
    }

    @Test
    void missingCredentialsFailClosedWithoutAnyRequest() {
        Rest2RfcProperties.Endpoint endpoint = new Rest2RfcProperties.Endpoint();
        endpoint.setBaseUrl(BASE_URL);
        Rest2RfcProperties partialProps = new Rest2RfcProperties();
        partialProps.setSystems(Map.of(SYSTEM_REF, endpoint));

        RestJsonTechnicalAdapter partialAdapter = new RestJsonTechnicalAdapter(
                registry,
                new BindingRegistry(1, List.of(binding())),
                partialProps, RestClient.builder());

        TechnicalExecutionResult result = partialAdapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_AUTH_ERROR);
    }

    private static CapabilityDefinition capability() {
        return new CapabilityDefinition(
                CAPABILITY_ID,
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
                new CapabilityDefinition.ExecutorBinding("REST_JSON", BINDING_ID),
                new CapabilityDefinition.Governance(
                        SideEffect.none, false, "not_required", "internal", true)
        );
    }

    private static BindingDefinition binding() {
        return new BindingDefinition(
                BINDING_ID, "REST_JSON", null, null, "POST",
                Map.of(), null, List.of(),
                Map.of("sideEffect", "none", "timeoutMs", 30000),
                SYSTEM_REF, "/sap/bc/rest2rfc",
                Map.of("mode", "dynamic"),
                Map.of("mode", "dynamic"),
                Map.of("type", "basic", "credentialRef", "sap-rest2rfc")
        );
    }
}

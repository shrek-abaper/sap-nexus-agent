package com.sapnexus.gateway.odata;

import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityRegistry;
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
import static org.hamcrest.Matchers.is;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

@SuppressWarnings("unchecked")
class ODataHttpProxyAdapterTest {

    private static final String PROXY_URL = "http://localhost:8081";
    private static final String CAPABILITY_ID = "MM.PurchaseOrder.GetList";
    private static final String BINDING_ID = "sap.mm.purchaseorder.list-odata";

    private CapabilityRegistry registry;
    private BindingRegistry bindingRegistry;
    private ODataProxyProperties properties;
    private RestClient.Builder builder;
    private MockRestServiceServer server;
    private ODataHttpProxyAdapter adapter;

    @BeforeEach
    void setUp() {
        registry = mock(CapabilityRegistry.class);
        when(registry.findEnabled(CAPABILITY_ID))
                .thenReturn(Optional.of(mock(CapabilityDefinition.class)));

        BindingDefinition binding = new BindingDefinition(
                BINDING_ID, "ODATA",
                "API_PURCHASEORDER_PROCESS_SRV", "PurchaseOrder", "GET",
                Map.of("poNumber", "PurchaseOrder", "vendor", "Supplier",
                        "plant", "Plant", "material", "Material"),
                50,
                List.of("PurchaseOrder", "Supplier", "Plant", "Material",
                        "OrderQuantity", "PurchaseOrderUnit"),
                Map.of("sideEffect", "none", "timeoutMs", 30000)
        );
        bindingRegistry = new BindingRegistry(1, List.of(binding));

        properties = new ODataProxyProperties();
        builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        adapter = new ODataHttpProxyAdapter(registry, bindingRegistry, properties, builder);
    }

    private TechnicalExecutionRequest request() {
        return new TechnicalExecutionRequest(
                "trace-001", CAPABILITY_ID, BINDING_ID,
                "ODATA", "execute",
                Map.of("poNumber", "4500000001"),
                Map.of(), Map.of()
        );
    }

    // --- success path ---

    @Test
    void normalListReturnsSuccessWithPurchaseOrders() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess(
                        "{\"success\":true,\"purchaseOrders\":[{\"purchaseOrder\":\"4500000001\",\"supplier\":\"V001\"}],\"totalCount\":1,\"traceId\":\"trace-001\"}",
                        MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isTrue();
        assertThat(result.errorType()).isEqualTo(ErrorType.NONE);
        assertThat(result.capabilityId()).isEqualTo(CAPABILITY_ID);
        assertThat(result.bindingId()).isEqualTo(BINDING_ID);
        assertThat(result.executorType()).isEqualTo("ODATA");
        List<?> purchaseOrders = (List<?>) result.data().get("purchaseOrders");
        assertThat(purchaseOrders).hasSize(1);
        assertThat(result.data().get("totalCount")).isEqualTo(1);
        assertThat(result.redactionApplied()).isTrue();
        server.verify();
    }

    @Test
    void emptyListReturnsSuccessWithEmptyData() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"purchaseOrders\":[],\"totalCount\":0,\"traceId\":\"trace-001\"}",
                        MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isTrue();
        assertThat((List<?>) result.data().get("purchaseOrders")).isEmpty();
        assertThat(result.data().get("totalCount")).isEqualTo(0);
    }

    // --- error paths ---

    @Test
    void http400ReturnsFailureWithInvalidParameter() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andRespond(withStatus(HttpStatus.BAD_REQUEST)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"success\":false,\"purchaseOrders\":[],\"totalCount\":0,\"errorType\":\"BAD_REQUEST\",\"messages\":[{\"type\":\"E\",\"message\":\"Missing serviceRef\"}],\"traceId\":\"trace-001\"}"));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.INVALID_PARAMETER);
    }

    @Test
    void http502ReturnsFailureWithCommunicationError() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andRespond(withStatus(HttpStatus.BAD_GATEWAY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"success\":false,\"purchaseOrders\":[],\"totalCount\":0,\"errorType\":\"CONNECTION_ERROR\",\"messages\":[{\"type\":\"E\",\"message\":\"SAP unreachable\"}],\"traceId\":\"trace-001\"}"));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMUNICATION_ERROR);
    }

    @Test
    void sapBusinessErrorReturnsFailureWithBusinessError() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andRespond(withSuccess(
                        "{\"success\":false,\"purchaseOrders\":[],\"totalCount\":0,\"errorType\":\"ODATA_ERROR\",\"messages\":[{\"type\":\"E\",\"message\":\"SAP OData application error\"}],\"traceId\":\"trace-001\"}",
                        MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
        assertThat(result.messages()).hasSize(1);
        assertThat(result.messages().get(0).message()).contains("SAP OData application error");
    }

    @Test
    void malformedJsonReturnsNormalizationError() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andRespond(withSuccess("not valid json {{{", MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.NORMALIZATION_ERROR);
    }

    @Test
    void proxyUnreachableReturnsCommunicationError() {
        ODataProxyProperties unreachableProps = new ODataProxyProperties();
        unreachableProps.setProxyUrl("http://localhost:1");
        ODataHttpProxyAdapter unreachableAdapter = new ODataHttpProxyAdapter(
                registry, bindingRegistry, unreachableProps, RestClient.builder());

        TechnicalExecutionResult result = unreachableAdapter.execute(request());

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_COMMUNICATION_ERROR);
    }

    // --- redaction ---

    @Test
    void sensitiveFieldsInResponseAreRedacted() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"purchaseOrders\":[],\"totalCount\":0,\"destination\":\"S4H-DEV\",\"token\":\"secret123\",\"authorization\":\"Bearer xyz\",\"traceId\":\"trace-001\"}",
                        MediaType.APPLICATION_JSON));

        TechnicalExecutionResult result = adapter.execute(request());

        assertThat(result.success()).isTrue();
        assertThat(result.redactionApplied()).isTrue();
        assertThat(result.adapterMetadata().get("destination")).isEqualTo("***");
        assertThat(result.adapterMetadata().get("token")).isEqualTo("***");
        assertThat(result.adapterMetadata().get("authorization")).isEqualTo("***");
    }

    // --- payload verification ---

    @Test
    void forwardsCorrectPayloadToPythonService() {
        server.expect(requestTo(PROXY_URL + "/execute"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(jsonPath("$.serviceRef", is("API_PURCHASEORDER_PROCESS_SRV")))
                .andExpect(jsonPath("$.entitySet", is("PurchaseOrder")))
                .andExpect(jsonPath("$.filterMapping.poNumber", is("PurchaseOrder")))
                .andExpect(jsonPath("$.filterMapping.vendor", is("Supplier")))
                .andExpect(jsonPath("$.parameters.poNumber", is("4500000001")))
                .andExpect(jsonPath("$.topLimit", is(50)))
                .andExpect(jsonPath("$.selectFields[0]", is("PurchaseOrder")))
                .andExpect(jsonPath("$.traceId", is("trace-001")))
                .andRespond(withSuccess(
                        "{\"success\":true,\"purchaseOrders\":[],\"totalCount\":0,\"traceId\":\"trace-001\"}",
                        MediaType.APPLICATION_JSON));

        adapter.execute(request());

        server.verify();
    }
}

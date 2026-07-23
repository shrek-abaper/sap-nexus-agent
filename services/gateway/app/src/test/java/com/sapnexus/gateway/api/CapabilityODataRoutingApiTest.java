package com.sapnexus.gateway.api;

import com.sapnexus.gateway.execution.JcoRfcTechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.jco.JcoCapabilityExecutor;
import com.sapnexus.gateway.odata.ODataHttpProxyAdapter;
import com.sapnexus.gateway.odata.ODataProxyProperties;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnMessage;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Integration test verifying JCo and OData dispatcher routing coexist:
 * - MM.Inventory.GetAvailability (JCO_RFC) routes through JcoRfcTechnicalAdapter
 * - MM.PurchaseOrder.GetList (ODATA) routes through ODataHttpProxyAdapter (mock Python service)
 *
 * <p>Both go through the full controller path: validation -> guard -> dispatcher -> adapter.
 */
@WebMvcTest(CapabilityController.class)
@Import(CapabilityODataRoutingApiTest.Config.class)
class CapabilityODataRoutingApiTest {

    @Autowired
    private MockMvc mockMvc;

    @BeforeEach
    void resetFakeExecutor() {
        Config.jcoInvocations.set(0);
    }

    // --- JCo routing (regression) ---

    @Test
    void inventoryRoutesThroughJcoAdapter() throws Exception {
        mockMvc.perform(post("/capabilities/{capabilityId}/execute", "MM.Inventory.GetAvailability")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\"}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success", is(true)))
                .andExpect(jsonPath("$.capabilityId", is("MM.Inventory.GetAvailability")))
                .andExpect(jsonPath("$.executor.type", is("JCO_RFC")))
                .andExpect(jsonPath("$.executor.rfcName", is("BAPI_MATERIAL_STOCK_REQ_LIST")))
                .andExpect(jsonPath("$.data.availableQuantity", is(42)));

        org.assertj.core.api.Assertions.assertThat(Config.jcoInvocations.get()).isEqualTo(1);
    }

    // --- OData routing ---

    @Test
    void purchaseOrderRoutesThroughODataAdapterWithMockPythonService() throws Exception {
        Config.mockServer.expect(requestTo("http://localhost:8081/execute"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath("$.serviceRef", is("API_PURCHASEORDER_PROCESS_SRV")))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath("$.entitySet", is("PurchaseOrder")))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath("$.filterMapping.poNumber", is("PurchaseOrder")))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath("$.parameters.poNumber", is("4500000001")))
                .andExpect(org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath("$.topLimit", is(50)))
                .andRespond(withSuccess(
                        "{\"success\":true,\"purchaseOrders\":[{\"purchaseOrder\":\"4500000001\",\"supplier\":\"V001\"}],\"totalCount\":1,\"traceId\":\"trace-od\"}",
                        MediaType.APPLICATION_JSON));

        mockMvc.perform(post("/capabilities/{capabilityId}/execute", "MM.PurchaseOrder.GetList")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"parameters\":{\"poNumber\":\"4500000001\"}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success", is(true)))
                .andExpect(jsonPath("$.capabilityId", is("MM.PurchaseOrder.GetList")))
                .andExpect(jsonPath("$.executor.type", is("ODATA")))
                .andExpect(jsonPath("$.data.purchaseOrders[0].purchaseOrder", is("4500000001")))
                .andExpect(jsonPath("$.data.totalCount", is(1)));

        // JCo adapter must NOT have been called for OData capability
        org.assertj.core.api.Assertions.assertThat(Config.jcoInvocations.get()).isZero();

        Config.mockServer.verify();
    }

    // --- OData technical override guard (controller full path) ---

    @Test
    void purchaseOrderRejectsDollarFilterOverride() throws Exception {
        mockMvc.perform(post("/capabilities/{capabilityId}/execute", "MM.PurchaseOrder.GetList")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"parameters\":{\"poNumber\":\"4500000001\",\"$filter\":\"PurchaseOrder eq '1'\"}}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("INVALID_PARAMETER")));

        org.assertj.core.api.Assertions.assertThat(Config.jcoInvocations.get()).isZero();
    }

    @Test
    void purchaseOrderRejectsEntitySetOverride() throws Exception {
        mockMvc.perform(post("/capabilities/{capabilityId}/execute", "MM.PurchaseOrder.GetList")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"parameters\":{\"poNumber\":\"4500000001\",\"entitySet\":\"EvilEntity\"}}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("INVALID_PARAMETER")));
    }

    @TestConfiguration
    static class Config {
        static final AtomicInteger jcoInvocations = new AtomicInteger();
        static MockRestServiceServer mockServer;

        @Bean
        CapabilityRegistry capabilityRegistry() {
            return new CapabilityRegistry(1, List.of(inventory(), purchaseOrder()));
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
        BindingRegistry bindingRegistry() {
            BindingDefinition poBinding = new BindingDefinition(
                    "sap.mm.purchaseorder.list-odata", "ODATA",
                    "API_PURCHASEORDER_PROCESS_SRV", "PurchaseOrder", "GET",
                    Map.of("poNumber", "PurchaseOrder", "vendor", "Supplier",
                            "plant", "Plant", "material", "Material"),
                    50,
                    List.of("PurchaseOrder", "Supplier", "Plant", "Material",
                            "OrderQuantity", "PurchaseOrderUnit"),
                    Map.of("sideEffect", "none", "timeoutMs", 30000)
            );
            return new BindingRegistry(1, List.of(poBinding));
        }

        @Bean
        ODataProxyProperties oDataProxyProperties() {
            return new ODataProxyProperties();
        }

        @Bean
        JcoCapabilityExecutor jcoCapabilityExecutor() {
            return (capability, parameters, traceId) -> {
                jcoInvocations.incrementAndGet();
                return ExecutionResult.success(
                        traceId,
                        capability.capabilityId(),
                        capability.executor().type(),
                        capability.executor().rfcName(),
                        List.of(new SapReturnMessage("S", "", "", "OK", "")),
                        Map.of("availableQuantity", 42),
                        5
                );
            };
        }

        @Bean
        TechnicalExecutionDispatcher technicalExecutionDispatcher(
                CapabilityRegistry registry,
                BindingRegistry bindingRegistry,
                ODataProxyProperties properties,
                JcoCapabilityExecutor executor
        ) {
            JcoRfcTechnicalAdapter jcoAdapter = new JcoRfcTechnicalAdapter(List.of(executor), registry);

            RestClient.Builder builder = RestClient.builder();
            mockServer = MockRestServiceServer.bindTo(builder).build();
            ODataHttpProxyAdapter oDataAdapter = new ODataHttpProxyAdapter(
                    registry, bindingRegistry, properties, builder);

            return new TechnicalExecutionDispatcher(Map.of(
                    "JCO_RFC", jcoAdapter,
                    "ODATA", oDataAdapter
            ));
        }

        private static CapabilityDefinition inventory() {
            return new CapabilityDefinition(
                    "MM.Inventory.GetAvailability",
                    "Inventory Availability",
                    "Read material availability.",
                    CapabilityStatus.active,
                    CapabilityKind.Function,
                    "MM",
                    "InventoryStock",
                    "sapnexus:MM_Inventory_GetAvailability",
                    "sapnexus:InventoryAvailabilityReadFunction",
                    List.of(
                            new CapabilityDefinition.InputField("material", "materialNumber", "sapnexus:MaterialNumber", true, "string", 1, 40, "MATERIAL"),
                            new CapabilityDefinition.InputField("plant", "plant", "sapnexus:Plant", true, "string", 1, 4, "PLANT")
                    ),
                    List.of(),
                    new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_STOCK_REQ_LIST", Map.of("material", "MATERIAL", "plant", "PLANT"), Map.of()),
                    new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.inventory.md04-stock-req-list"),
                    new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
            );
        }

        private static CapabilityDefinition purchaseOrder() {
            return new CapabilityDefinition(
                    "MM.PurchaseOrder.GetList",
                    "Purchase Order List",
                    "Read purchase order list via OData.",
                    CapabilityStatus.active,
                    CapabilityKind.Function,
                    "MM",
                    "PurchaseOrder",
                    "sapnexus:MM_PurchaseOrder_GetList",
                    "sapnexus:PurchaseOrderListFunction",
                    List.of(
                            new CapabilityDefinition.InputField("poNumber", "purchaseOrderNumber", "sapnexus:PurchaseOrderNumber", false, "string", 1, 40, "PurchaseOrder"),
                            new CapabilityDefinition.InputField("vendor", "vendor", "sapnexus:Vendor", false, "string", 1, 10, "Supplier"),
                            new CapabilityDefinition.InputField("plant", "plant", "sapnexus:Plant", false, "string", 1, 4, "Plant"),
                            new CapabilityDefinition.InputField("material", "material", "sapnexus:MaterialNumber", false, "string", 1, 40, "Material")
                    ),
                    List.of(),
                    new CapabilityDefinition.Executor("ODATA", null, Map.of(), Map.of()),
                    new CapabilityDefinition.ExecutorBinding("ODATA", "sap.mm.purchaseorder.list-odata"),
                    new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
            );
        }
    }
}

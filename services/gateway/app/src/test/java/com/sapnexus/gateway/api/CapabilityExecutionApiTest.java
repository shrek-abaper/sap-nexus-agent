package com.sapnexus.gateway.api;

import com.sapnexus.gateway.execution.JcoRfcTechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.jco.JcoCapabilityExecutor;
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
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CapabilityController.class)
@Import(CapabilityExecutionApiTest.Config.class)
class CapabilityExecutionApiTest {
    @Autowired
    private MockMvc mockMvc;

    @BeforeEach
    void resetFakeExecutor() {
        Config.invocations.set(0);
        Config.executedRfc.set(null);
    }

    @Test
    void executeValidReadCapabilityUsesRegisteredRfcAndReturnsExecutionResult() throws Exception {
        execute("MM.Inventory.GetAvailability", "{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\"}}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success", is(true)))
                .andExpect(jsonPath("$.capabilityId", is("MM.Inventory.GetAvailability")))
                .andExpect(jsonPath("$.executor.rfcName", is("BAPI_MATERIAL_STOCK_REQ_LIST")))
                .andExpect(jsonPath("$.data.availableQuantity", is(42)))
                .andExpect(jsonPath("$.errorType", is("NONE")));

        org.assertj.core.api.Assertions.assertThat(Config.invocations.get()).isEqualTo(1);
        org.assertj.core.api.Assertions.assertThat(Config.executedRfc.get()).isEqualTo("BAPI_MATERIAL_STOCK_REQ_LIST");
    }

    @Test
    void executeRejectsCallerOwnedTechnicalOverrideBeforeAdapterExecution() throws Exception {
        execute("MM.Inventory.GetAvailability", "{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\",\"rfcName\":\"Z_UNSAFE_RFC\"}}")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("INVALID_PARAMETER")));

        org.assertj.core.api.Assertions.assertThat(Config.invocations.get()).isZero();
    }

    @Test
    void executeMissingParameterDoesNotInvokeExecutor() throws Exception {
        execute("MM.Inventory.GetAvailability", "{\"parameters\":{\"material\":\"MAT-001\"}}")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("MISSING_PARAMETER")));

        org.assertj.core.api.Assertions.assertThat(Config.invocations.get()).isZero();
    }

    @Test
    void executeUnknownCapabilityDoesNotInvokeExecutor() throws Exception {
        execute("MM.Unknown", "{\"parameters\":{}}")
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("CAPABILITY_NOT_FOUND")));

        org.assertj.core.api.Assertions.assertThat(Config.invocations.get()).isZero();
    }

    private org.springframework.test.web.servlet.ResultActions execute(String capabilityId, String body) throws Exception {
        return mockMvc.perform(post("/capabilities/{capabilityId}/execute", capabilityId)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body));
    }

    @TestConfiguration
    static class Config {
        static final AtomicInteger invocations = new AtomicInteger();
        static final AtomicReference<String> executedRfc = new AtomicReference<>();

        @Bean
        CapabilityRegistry capabilityRegistry() {
            return new CapabilityRegistry(1, List.of(inventory()));
        }

        @Bean
        JcoCapabilityExecutor jcoCapabilityExecutor() {
            return (capability, parameters, traceId) -> {
                invocations.incrementAndGet();
                executedRfc.set(capability.executor().rfcName());
                return ExecutionResult.success(
                        traceId,
                        capability.capabilityId(),
                        capability.executor().type(),
                        capability.executor().rfcName(),
                        List.of(new SapReturnMessage("S", "", "", "OK", "")),
                        Map.of("availableQuantity", 42),
                        7
                );
            };
        }

        @Bean
        TechnicalExecutionDispatcher technicalExecutionDispatcher(CapabilityRegistry registry, JcoCapabilityExecutor executor) {
            JcoRfcTechnicalAdapter adapter = new JcoRfcTechnicalAdapter(List.of(executor), registry);
            return new TechnicalExecutionDispatcher(Map.of("JCO_RFC", adapter));
        }

        @Bean
        com.sapnexus.gateway.approval.ApprovalStore approvalStore() {
            return new com.sapnexus.gateway.approval.InMemoryApprovalStore();
        }

        @Bean
        com.sapnexus.gateway.approval.ApprovalGuard approvalGuard() {
            return new com.sapnexus.gateway.approval.ApprovalGuard();
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
    }
}

package com.sapnexus.gateway.api;

import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CapabilityController.class)
@Import(CapabilityControllerTest.RegistryConfig.class)
class CapabilityControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @Test
    void capabilitiesReturnsEnabledCapabilitiesFromRegistry() throws Exception {
        mockMvc.perform(get("/capabilities"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)))
                .andExpect(jsonPath("$[0].capabilityId", is("MM.Inventory.GetAvailability")))
                .andExpect(jsonPath("$[0].kind", is("Function")))
                .andExpect(jsonPath("$[0].domain", is("MM")))
                .andExpect(jsonPath("$[0].businessObject", is("InventoryStock")))
                .andExpect(jsonPath("$[0].ontologyIri", is("sapnexus:MM_Inventory_GetAvailability")))
                .andExpect(jsonPath("$[0].executor.type", is("JCO_RFC")))
                .andExpect(jsonPath("$[0].governance.sideEffect", is("none")))
                .andExpect(jsonPath("$[0].governance.requiresApproval", is(false)));
    }

    @TestConfiguration
    static class RegistryConfig {
        @Bean
        CapabilityRegistry capabilityRegistry() {
            CapabilityDefinition capability = new CapabilityDefinition(
                    "MM.Inventory.GetAvailability",
                    "Inventory Availability",
                    "Read material availability.",
                    CapabilityStatus.active,
                    CapabilityKind.Function,
                    "MM",
                    "InventoryStock",
                    "sapnexus:MM_Inventory_GetAvailability",
                    "sapnexus:InventoryAvailabilityReadFunction",
                    List.of(),
                    List.of(),
                    new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_STOCK_REQ_LIST", Map.of(), Map.of()),
                    new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
            );
            CapabilityDefinition disabled = new CapabilityDefinition(
                    "MM.Disabled",
                    "Disabled",
                    "Disabled capability.",
                    CapabilityStatus.disabled,
                    CapabilityKind.Function,
                    "MM",
                    "InventoryStock",
                    "sapnexus:Disabled",
                    "sapnexus:Disabled",
                    List.of(),
                    List.of(),
                    new CapabilityDefinition.Executor("JCO_RFC", "BAPI_DISABLED", Map.of(), Map.of()),
                    new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
            );
            return new CapabilityRegistry(1, List.of(capability, disabled));
        }

        @Bean
        TechnicalExecutionDispatcher technicalExecutionDispatcher() {
            return new TechnicalExecutionDispatcher(Map.of());
        }

        @Bean
        com.sapnexus.gateway.approval.ApprovalStore approvalStore() {
            return new com.sapnexus.gateway.approval.InMemoryApprovalStore();
        }

        @Bean
        com.sapnexus.gateway.approval.ApprovalGuard approvalGuard() {
            return new com.sapnexus.gateway.approval.ApprovalGuard();
        }
    }
}

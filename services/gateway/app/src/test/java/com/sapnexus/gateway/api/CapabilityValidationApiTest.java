package com.sapnexus.gateway.api;

import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
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

import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.emptyString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CapabilityController.class)
@Import(CapabilityValidationApiTest.RegistryConfig.class)
class CapabilityValidationApiTest {
    @Autowired
    private MockMvc mockMvc;

    @Test
    void unknownCapabilityReturnsCapabilityNotFound() throws Exception {
        validate("MM.Unknown", "{\"parameters\":{}}")
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("CAPABILITY_NOT_FOUND")));
    }

    @Test
    void disabledCapabilityReturnsCapabilityDisabled() throws Exception {
        validate("MM.Disabled", "{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\"}}")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("CAPABILITY_DISABLED")));
    }

    @Test
    void missingMaterialReturnsMissingParameter() throws Exception {
        validate("MM.Inventory.GetAvailability", "{\"parameters\":{\"plant\":\"1000\"}}")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("MISSING_PARAMETER")));
    }

    @Test
    void invalidPlantReturnsInvalidParameter() throws Exception {
        validate("MM.Inventory.GetAvailability", "{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"10000\"}}")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.errorType", is("INVALID_PARAMETER")));
    }

    @Test
    void validRequestReturnsSuccessWithTraceId() throws Exception {
        validate("MM.Inventory.GetAvailability", "{\"parameters\":{\"material\":\"MAT-001\",\"plant\":\"1000\",\"unit\":\"EA\"}}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.traceId", not(emptyString())))
                .andExpect(jsonPath("$.capabilityId", is("MM.Inventory.GetAvailability")))
                .andExpect(jsonPath("$.success", is(true)))
                .andExpect(jsonPath("$.errorType", is("NONE")));
    }

    private org.springframework.test.web.servlet.ResultActions validate(String capabilityId, String body) throws Exception {
        return mockMvc.perform(post("/capabilities/{capabilityId}/validate", capabilityId)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body));
    }

    @TestConfiguration
    static class RegistryConfig {
        @Bean
        CapabilityRegistry capabilityRegistry() {
            return new CapabilityRegistry(1, List.of(inventory(CapabilityStatus.active), disabled()));
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

        private static CapabilityDefinition disabled() {
            return new CapabilityDefinition(
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
        }

        private static CapabilityDefinition inventory(CapabilityStatus status) {
            return new CapabilityDefinition(
                    "MM.Inventory.GetAvailability",
                    "Inventory Availability",
                    "Read material availability.",
                    status,
                    CapabilityKind.Function,
                    "MM",
                    "InventoryStock",
                    "sapnexus:MM_Inventory_GetAvailability",
                    "sapnexus:InventoryAvailabilityReadFunction",
                    List.of(
                            new CapabilityDefinition.InputField("material", "materialNumber", "sapnexus:MaterialNumber", true, "string", 1, 40, "MATERIAL"),
                            new CapabilityDefinition.InputField("plant", "plant", "sapnexus:Plant", true, "string", 1, 4, "PLANT"),
                            new CapabilityDefinition.InputField("unit", "unitOfMeasure", "sapnexus:UnitOfMeasure", false, "string", 1, 3, "UNIT")
                    ),
                    List.of(),
                    new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_STOCK_REQ_LIST", Map.of("material", "MATERIAL", "plant", "PLANT", "unit", "UNIT"), Map.of()),
                    new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true)
            );
        }
    }
}

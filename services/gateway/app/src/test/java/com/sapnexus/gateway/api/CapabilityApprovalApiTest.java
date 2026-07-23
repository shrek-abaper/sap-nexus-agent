package com.sapnexus.gateway.api;

import com.sapnexus.gateway.approval.ApprovalGuard;
import com.sapnexus.gateway.approval.ApprovalRecord;
import com.sapnexus.gateway.approval.ApprovalStore;
import com.sapnexus.gateway.approval.InMemoryApprovalStore;
import com.sapnexus.gateway.execution.TechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.SapReturnMessage;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Task 18: Approval registration channel (Agent -> Gateway).
 *
 * <p>Verifies that {@code POST /capabilities/{capabilityId}/approve} accepts an
 * {@link ApprovalRecord} body, persists it via {@link ApprovalStore#save}, and
 * returns the approvalId. This is the registration half of the Agent<->Gateway
 * approval bridge: the Agent creates the pending record, transitions it to
 * approved, then registers it with the Gateway so the fail-closed
 * {@link com.sapnexus.gateway.approval.ApprovalGuard} at the execute entry can
 * find it.
 */
@WebMvcTest(CapabilityController.class)
@Import(CapabilityApprovalApiTest.ApprovalTestConfig.class)
@TestPropertySource(properties = "SAP_NEXUS_APPROVAL_TOKEN=test-approval-token")
class CapabilityApprovalApiTest {

    private static final String PR_CAPABILITY_ID = "MM.PR.CreateDraft";
    private static final String APPROVAL_HEADER = "X-SAP-Nexus-Approval-Token";
    private static final String APPROVAL_TOKEN = "test-approval-token";
    private static final String VALID_PARAMETER_HASH =
            "sha256:96338af04221d451e96acc2c6fdb721de3c692b92f0c2bc1cc3634e4f2fb5ca8";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ApprovalStore approvalStore;

    @Test
    void approveEndpointRegistersApprovalRecordAndReturnsApprovalId() throws Exception {
        String body = approvedBody("appr-smoke-001", PR_CAPABILITY_ID, "approved");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.approvalId").value("appr-smoke-001"));

        ApprovalRecord saved = approvalStore.find("appr-smoke-001").orElse(null);
        assertTrue(saved != null, "ApprovalStore must contain the registered record after approve");
        assertEquals(PR_CAPABILITY_ID, saved.capabilityId());
        assertEquals(VALID_PARAMETER_HASH, saved.parameterSnapshotHash());
        assertEquals("approved", saved.status());
    }

    @Test
    void approveEndpointRejectsMissingServiceToken() throws Exception {
        String body = approvedBody("appr-no-token", PR_CAPABILITY_ID, "approved");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isForbidden());

        assertTrue(approvalStore.find("appr-no-token").isEmpty());
    }

    @Test
    void approveEndpointRejectsParameterHashThatDoesNotMatchSnapshot() throws Exception {
        String body = approvedBody("appr-bad-hash", PR_CAPABILITY_ID, "approved")
                .replace(VALID_PARAMETER_HASH, "sha256:forged");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isBadRequest());

        assertTrue(approvalStore.find("appr-bad-hash").isEmpty());
    }

    @Test
    void approveEndpointRejectsExpiredOrFutureDatedRecords() throws Exception {
        java.time.Instant now = java.time.Instant.now();
        String expired = approvedBodyAt(
                "appr-expired", PR_CAPABILITY_ID, "approved",
                now.minusSeconds(700), now.minusSeconds(100));
        String future = approvedBodyAt(
                "appr-future", PR_CAPABILITY_ID, "approved",
                now.plusSeconds(60), now.plusSeconds(660));

        for (String body : List.of(expired, future)) {
            mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                            .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isBadRequest());
        }

        assertTrue(approvalStore.find("appr-expired").isEmpty());
        assertTrue(approvalStore.find("appr-future").isEmpty());
    }

    @Test
    void approveEndpointRejectsPendingRejectedAndCrossCapabilityRecords() throws Exception {
        for (String state : List.of("pending", "rejected")) {
            String approvalId = "appr-" + state;
            mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                            .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                            .contentType("application/json")
                            .content(approvedBody(approvalId, PR_CAPABILITY_ID, state)))
                    .andExpect(status().isBadRequest());
            assertTrue(approvalStore.find(approvalId).isEmpty());
        }

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(approvedBody("appr-cross", "MM.Other.Write", "approved")))
                .andExpect(status().isBadRequest());
        assertTrue(approvalStore.find("appr-cross").isEmpty());
    }

    @Test
    void approveThenExecuteSucceedsEndToEnd() throws Exception {
        // Task 18 fix (IMPORTANT-1): end-to-end coverage of the Agent<->Gateway
        // approval registration channel. POST approve registers the record, then
        // POST execute carrying both approvalId AND parameterSnapshotHash must pass
        // the fail-closed ApprovalGuard (presence + TTL + version-match + duplicate)
        // and reach dispatch. This is the integration test that would have caught
        // CRITICAL-1 (Agent omitting parameterSnapshotHash from the execute body).
        String approveBody = approvedBody("appr-e2e-001", PR_CAPABILITY_ID, "approved");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(approveBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.approvalId").value("appr-e2e-001"));

        String executeBody = """
                {
                  "parameters": {"material": "M001"},
                  "approvalId": "appr-e2e-001",
                  "parameterSnapshotHash": "%s"
                }
                """.formatted(VALID_PARAMETER_HASH);

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/execute")
                        .contentType("application/json")
                        .content(executeBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.prNumber").value("0010001234"))
                .andExpect(jsonPath("$.commitStatus").value("committed"));

        ApprovalRecord afterExecute = approvalStore.find("appr-e2e-001").orElse(null);
        assertTrue(afterExecute != null, "registered approval must still be present after execute");
        assertEquals("executed", afterExecute.status(),
                "markExecuted must flip the registered approval to executed after a successful Action execute");
    }

    @Test
    void approveThenExecuteWithoutHashReturnsVersionMismatch() throws Exception {
        // CRITICAL-1 regression guard: if the Agent omits parameterSnapshotHash
        // from the execute body, the fail-closed ApprovalGuard must reject with
        // APPROVAL_VERSION_MISMATCH (record.hash "sha256:e2e-hash" != request.hash null).
        // This is the exact failure mode the Task 18 fix closes on the Agent side;
        // paired with approveThenExecuteSucceedsEndToEnd it proves the hash is the
        // key that opens the channel.
        String approveBody = approvedBody("appr-e2e-002", PR_CAPABILITY_ID, "approved");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(approveBody))
                .andExpect(status().isOk());

        String executeBody = """
                {
                  "parameters": {"material": "M001"},
                  "approvalId": "appr-e2e-002"
                }
                """;

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/execute")
                        .contentType("application/json")
                        .content(executeBody))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errorType").value("APPROVAL_VERSION_MISMATCH"));
    }

    @Test
    void approveEndpointCannotReviveAnExistingApprovalId() throws Exception {
        String body = approvedBody("appr-replay", PR_CAPABILITY_ID, "approved");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isOk());
        approvalStore.claimForExecution("appr-replay");
        approvalStore.markExecuted("appr-replay");

        mockMvc.perform(post("/capabilities/" + PR_CAPABILITY_ID + "/approve")
                        .header(APPROVAL_HEADER, APPROVAL_TOKEN)
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.errorType").value("APPROVAL_DUPLICATE"));

        assertEquals("executed", approvalStore.find("appr-replay").orElseThrow().status());
    }

    private static String approvedBody(String approvalId, String capabilityId, String status) {
        java.time.Instant approvedAt = java.time.Instant.now();
        return approvedBodyAt(
                approvalId, capabilityId, status, approvedAt, approvedAt.plusSeconds(600));
    }

    private static String approvedBodyAt(
            String approvalId,
            String capabilityId,
            String status,
            java.time.Instant approvedAt,
            java.time.Instant expiresAt
    ) {
        return """
                {
                  "approvalId": "%s",
                  "capabilityId": "%s",
                  "parameterSnapshotHash": "%s",
                  "parameters": {"material": "M001"},
                  "approver": "user",
                  "approvedAt": "%s",
                  "expiresAt": "%s",
                  "status": "%s"
                }
                """.formatted(
                        approvalId, capabilityId, VALID_PARAMETER_HASH,
                        approvedAt, expiresAt, status);
    }

    @TestConfiguration
    static class ApprovalTestConfig {
        @Bean
        CapabilityRegistry capabilityRegistry() {
            CapabilityDefinition pr = new CapabilityDefinition(
                    PR_CAPABILITY_ID,
                    "PR Create",
                    "Create purchase requisition draft.",
                    CapabilityStatus.active,
                    CapabilityKind.Action,
                    "MM",
                    "PurchaseRequisition",
                    "sapnexus:MM_PR_CreateDraft",
                    "sapnexus:PurchaseRequisitionCreateAction",
                    List.of(),
                    List.of(),
                    new CapabilityDefinition.Executor(
                            "JCO_RFC",
                            "BAPI_PR_CREATE",
                            Map.of("material", "PRITEM.MATERIAL"),
                            Map.of("prNumber", "EXPORTS.NUMBER", "returnMessages", "RETURN")),
                    new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.pr.create-draft"),
                    new CapabilityDefinition.Governance(SideEffect.sap_write, true, "human_required", "internal", true));
            return new CapabilityRegistry(1, List.of(pr));
        }

        @Bean
        TechnicalExecutionDispatcher technicalExecutionDispatcher() {
            TechnicalAdapter stubAdapter = req -> TechnicalExecutionResult.success(
                    req.traceId(),
                    req.capabilityId(),
                    req.bindingId(),
                    req.executorType(),
                    List.of(new SapReturnMessage("S", "", "", "OK", "")),
                    Map.of("prNumber", "0010001234", "commitStatus", "committed"),
                    0,
                    Map.of());
            return new TechnicalExecutionDispatcher(Map.of("JCO_RFC", stubAdapter));
        }

        @Bean
        ApprovalStore approvalStore() {
            return new InMemoryApprovalStore();
        }

        @Bean
        ApprovalGuard approvalGuard() {
            return new ApprovalGuard();
        }
    }
}

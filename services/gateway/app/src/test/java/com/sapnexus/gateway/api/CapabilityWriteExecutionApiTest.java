package com.sapnexus.gateway.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

import com.sapnexus.gateway.approval.ApprovalGuard;
import com.sapnexus.gateway.approval.ApprovalRecord;
import com.sapnexus.gateway.approval.InMemoryApprovalStore;
import com.sapnexus.gateway.approval.ParameterSnapshotHasher;
import com.sapnexus.gateway.execution.TechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ActionResult;
import com.sapnexus.gateway.result.CommitStatus;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.sapnexus.gateway.trace.TraceWriter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;

/**
 * Task 8: ApprovalGuard integration at the execute entry point.
 *
 * <p>Verifies the four fail-closed rejection scenarios for WRITE (Action) capabilities
 * and that READ (Function) capabilities bypass the guard and reach dispatch unchanged.
 * A stub {@link TechnicalAdapter} records whether SAP dispatch was invoked, so each
 * rejection case also asserts the SAP boundary is never crossed (design D3).
 */
class CapabilityWriteExecutionApiTest {

    private static final String PR_CAPABILITY_ID = "MM.PR.CreateDraft";
    private static final String READ_CAPABILITY_ID = "MM.Inventory.GetAvailability";

    private InMemoryApprovalStore approvalStore;
    private CapabilityController controller;
    private AtomicBoolean dispatchInvoked;
    private AtomicInteger dispatchCount;
    private CountDownLatch firstDispatchEntered;
    private CountDownLatch releaseFirstDispatch;
    private AtomicBoolean failDispatch;
    private Path traceFile;

    @TempDir
    Path tempDir;

    @BeforeEach
    void setUp() {
        approvalStore = new InMemoryApprovalStore();
        ApprovalGuard approvalGuard = new ApprovalGuard();
        dispatchInvoked = new AtomicBoolean(false);
        dispatchCount = new AtomicInteger();
        failDispatch = new AtomicBoolean(false);
        TechnicalAdapter stubAdapter = request -> {
            dispatchInvoked.set(true);
            int invocation = dispatchCount.incrementAndGet();
            if (failDispatch.get()) {
                throw new IllegalStateException("destination: SAP-PRD unavailable");
            }
            if (invocation == 1 && firstDispatchEntered != null) {
                firstDispatchEntered.countDown();
                try {
                    releaseFirstDispatch.await(5, TimeUnit.SECONDS);
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("Interrupted while holding first dispatch", exception);
                }
            }
            Map<String, Object> data = PR_CAPABILITY_ID.equals(request.capabilityId())
                    ? Map.of("prNumber", "10137471", "commitStatus", "committed")
                    : Map.of("availableQuantity", 42);
            return TechnicalExecutionResult.success(
                    request.traceId(),
                    request.capabilityId(),
                    request.bindingId(),
                    request.executorType(),
                    List.of(new SapReturnMessage("S", "", "", "OK", "")),
                    data,
                    0,
                    Map.of());
        };
        TechnicalExecutionDispatcher dispatcher =
                new TechnicalExecutionDispatcher(Map.of("JCO_RFC", stubAdapter));
        CapabilityRegistry registry = new CapabilityRegistry(1, List.of(prCreateDraft(), inventoryRead()));
        traceFile = tempDir.resolve("gateway-traces.jsonl");
        TraceWriter traceWriter = new TraceWriter(traceFile);
        @SuppressWarnings("unchecked")
        ObjectProvider<TraceWriter> traceProvider = org.mockito.Mockito.mock(ObjectProvider.class);
        org.mockito.Mockito.doAnswer(invocation -> {
            @SuppressWarnings("unchecked")
            Consumer<TraceWriter> consumer = invocation.getArgument(0, Consumer.class);
            consumer.accept(traceWriter);
            return null;
        }).when(traceProvider).ifAvailable(org.mockito.ArgumentMatchers.any());
        controller = new CapabilityController(
                registry, dispatcher, traceProvider, approvalStore, approvalGuard, "test-approval-token");
    }

    @Test
    void executeActionWithoutApprovalReturnsApprovalRequired() throws Exception {
        CapabilityRequest request = new CapabilityRequest(prParams(), null, null);

        var response = controller.execute(PR_CAPABILITY_ID, request);
        ActionResult body = (ActionResult) response.getBody();

        assertFalse(body.success());
        assertEquals(ErrorType.APPROVAL_REQUIRED, body.errorType());
        assertFalse(dispatchInvoked.get(), "SAP must not be invoked when approval is missing (fail-closed)");
        String trace = Files.readString(traceFile);
        assertTrue(trace.contains("\"commitStatus\":\"none\""));
        assertTrue(trace.contains("\"errorType\":\"APPROVAL_REQUIRED\""));
    }

    @Test
    void executeActionWithTechnicalOverrideReturnsReplayableActionFailure() throws Exception {
        Map<String, Object> parameters = new java.util.HashMap<>(prParams());
        parameters.put("destination", "SAP-PRD");

        var response = controller.execute(PR_CAPABILITY_ID, new CapabilityRequest(parameters));
        ActionResult body = (ActionResult) response.getBody();

        assertFalse(body.success());
        assertEquals(ErrorType.INVALID_PARAMETER, body.errorType());
        assertEquals(CommitStatus.none, body.commitStatus());
        assertFalse(dispatchInvoked.get());
        String trace = Files.readString(traceFile);
        assertTrue(trace.contains("\"commitStatus\":\"none\""));
        assertTrue(trace.contains("\"errorType\":\"INVALID_PARAMETER\""));
        assertFalse(trace.contains("SAP-PRD"));
    }

    @Test
    void executeActionWithExpiredApprovalReturnsExpired() {
        ApprovalRecord expired = new ApprovalRecord(
                "appr-001", PR_CAPABILITY_ID, "sha256:abc",
                Map.of("material", "M001"), "user",
                Instant.now().minusSeconds(700), Instant.now().minusSeconds(100), "approved");
        approvalStore.save(expired);

        CapabilityRequest request = new CapabilityRequest(prParams(), "appr-001", "sha256:abc");

        var response = controller.execute(PR_CAPABILITY_ID, request);
        ActionResult body = (ActionResult) response.getBody();

        assertEquals(ErrorType.APPROVAL_EXPIRED, body.errorType());
        assertFalse(dispatchInvoked.get(), "SAP must not be invoked for an expired approval");
    }

    @Test
    void executeActionWithVersionMismatchReturnsMismatch() {
        ApprovalRecord approved = new ApprovalRecord(
                "appr-002", PR_CAPABILITY_ID, "sha256:original",
                Map.of("material", "M001"), "user",
                Instant.now(), Instant.now().plusSeconds(600), "approved");
        approvalStore.save(approved);

        CapabilityRequest request = new CapabilityRequest(prParams(), "appr-002", "sha256:changed");

        var response = controller.execute(PR_CAPABILITY_ID, request);
        ActionResult body = (ActionResult) response.getBody();

        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, body.errorType());
        assertFalse(dispatchInvoked.get(), "SAP must not be invoked when the parameter snapshot hash differs");
    }

    @Test
    void executeActionWithChangedParametersAndOriginalHashReturnsMismatch() {
        ParameterSnapshotHasher hasher = new ParameterSnapshotHasher();
        Map<String, Object> approvedParameters = prParams();
        String approvedHash = hasher.hash(approvedParameters);
        ApprovalRecord approved = new ApprovalRecord(
                "appr-tampered", PR_CAPABILITY_ID, approvedHash,
                approvedParameters.entrySet().stream().collect(java.util.stream.Collectors.toMap(
                        Map.Entry::getKey, entry -> String.valueOf(entry.getValue()))),
                "user", Instant.now(), Instant.now().plusSeconds(600), "approved");
        approvalStore.save(approved);

        Map<String, Object> changedParameters = new java.util.HashMap<>(approvedParameters);
        changedParameters.put("quantity", "999");
        CapabilityRequest request = new CapabilityRequest(
                changedParameters, "appr-tampered", approvedHash);

        var response = controller.execute(PR_CAPABILITY_ID, request);
        ActionResult body = (ActionResult) response.getBody();

        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, body.errorType());
        assertFalse(dispatchInvoked.get(), "SAP must not be invoked when actual parameters differ from approval");
    }

    @Test
    void executeActionRejectsEveryPlanAwareBindingMismatchBeforeDispatch() {
        List<CapabilityRequest> mismatchedRequests = List.of(
                planAwareRequest("appr-snapshot", "snapshot-changed", "2.1.0", "sha256:subject"),
                planAwareRequest("appr-version", "snapshot-21", "2.2.0", "sha256:subject"),
                planAwareRequest("appr-subject", "snapshot-21", "2.1.0", "sha256:changed"));
        approvalStore.save(planAwareRecord("appr-snapshot"));
        approvalStore.save(planAwareRecord("appr-version"));
        approvalStore.save(planAwareRecord("appr-subject"));

        for (CapabilityRequest request : mismatchedRequests) {
            var response = controller.execute(PR_CAPABILITY_ID, request);
            ActionResult body = (ActionResult) response.getBody();

            assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, body.errorType());
        }
        assertEquals(0, dispatchCount.get(), "plan approval drift must be rejected before dispatch");
    }

    @Test
    void executeActionDispatchesOnceWhenEveryPlanAwareBindingMatches() {
        ApprovalRecord approved = planAwareRecord("appr-plan-match");
        approvalStore.save(approved);

        var response = controller.execute(
                PR_CAPABILITY_ID,
                planAwareRequest(
                        approved.approvalId(),
                        approved.registrySnapshotId(),
                        approved.capabilityVersion(),
                        approved.approvalSubjectHash()));
        ActionResult body = (ActionResult) response.getBody();

        assertTrue(body.success());
        assertEquals(ErrorType.NONE, body.errorType());
        assertEquals(1, dispatchCount.get());
    }

    @Test
    void approveRejectsPartialPlanAwareBindingBeforeItReachesTheStore() {
        Map<String, Object> parameters = prParams();
        String hash = new ParameterSnapshotHasher().hash(parameters);
        ApprovalRecord incomplete = new ApprovalRecord(
                "appr-plan-incomplete",
                PR_CAPABILITY_ID,
                hash,
                parameters.entrySet().stream().collect(java.util.stream.Collectors.toMap(
                        Map.Entry::getKey, entry -> String.valueOf(entry.getValue()))),
                "run-owner",
                Instant.now(),
                Instant.now().plusSeconds(600),
                "approved",
                "snapshot-21",
                null,
                "sha256:subject");

        var response = controller.approve(
                PR_CAPABILITY_ID,
                "test-approval-token",
                incomplete);

        assertEquals(org.springframework.http.HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertTrue(approvalStore.find(incomplete.approvalId()).isEmpty());
    }

    @Test
    void executeActionDuplicateReturnsDuplicate() {
        ApprovalRecord executed = new ApprovalRecord(
                "appr-003", PR_CAPABILITY_ID, "sha256:abc",
                Map.of("material", "M001"), "user",
                Instant.now(), Instant.now().plusSeconds(600), "executed");
        approvalStore.save(executed);

        CapabilityRequest request = new CapabilityRequest(prParams(), "appr-003", "sha256:abc");

        var response = controller.execute(PR_CAPABILITY_ID, request);
        ActionResult body = (ActionResult) response.getBody();

        assertEquals(ErrorType.APPROVAL_DUPLICATE, body.errorType());
        assertFalse(dispatchInvoked.get(), "SAP must not be invoked for an already-executed approval");
    }

    @Test
    void executeReadCapabilitySkipsApprovalGuardAndDispatches() {
        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "MAT-001", "plant", "1000"), null, null);

        var response = controller.execute(READ_CAPABILITY_ID, request);
        ExecutionResult body = (ExecutionResult) response.getBody();

        assertTrue(body.success());
        assertEquals(ErrorType.NONE, body.errorType());
        assertTrue(dispatchInvoked.get(), "Read (Function) capability must bypass the approval guard and reach dispatch");
    }

    @Test
    void executeApprovedActionReturnsCommittedActionResult() throws Exception {
        String approvedHash = new ParameterSnapshotHasher().hash(prParams());
        ApprovalRecord approved = new ApprovalRecord(
                "appr-success", PR_CAPABILITY_ID, approvedHash,
                Map.of(
                        "material", "M001",
                        "plant", "1000",
                        "quantity", "10",
                        "unit", "EA",
                        "delivery_date", "2026-08-01"),
                "user", Instant.now(), Instant.now().plusSeconds(600), "approved");
        approvalStore.save(approved);

        CapabilityRequest request = new CapabilityRequest(
                prParams(), "appr-success", approvedHash);

        var response = controller.execute(PR_CAPABILITY_ID, request);
        ActionResult body = (ActionResult) response.getBody();

        assertTrue(body.success());
        assertEquals("10137471", body.prNumber());
        assertEquals(CommitStatus.committed, body.commitStatus());
        assertEquals("executed", approvalStore.find("appr-success").orElseThrow().status());
        String trace = Files.readString(traceFile);
        assertTrue(trace.contains("\"prNumber\":\"10137471\""));
        assertTrue(trace.contains("\"commitStatus\":\"committed\""));
        assertTrue(trace.contains("\"message\":\"OK\""));
    }

    @Test
    void concurrentExecuteRequestsDispatchExactlyOnce() throws Exception {
        ParameterSnapshotHasher hasher = new ParameterSnapshotHasher();
        Map<String, Object> parameters = prParams();
        String hash = hasher.hash(parameters);
        ApprovalRecord approved = new ApprovalRecord(
                "appr-race", PR_CAPABILITY_ID, hash,
                parameters.entrySet().stream().collect(java.util.stream.Collectors.toMap(
                        Map.Entry::getKey, entry -> String.valueOf(entry.getValue()))),
                "user", Instant.now(), Instant.now().plusSeconds(600), "approved");
        approvalStore.save(approved);
        CapabilityRequest request = new CapabilityRequest(parameters, "appr-race", hash);
        firstDispatchEntered = new CountDownLatch(1);
        releaseFirstDispatch = new CountDownLatch(1);
        var executor = Executors.newSingleThreadExecutor();

        try {
            var first = executor.submit(() -> controller.execute(PR_CAPABILITY_ID, request));
            assertTrue(firstDispatchEntered.await(5, TimeUnit.SECONDS));
            var replayedApproval = controller.approve(
                    PR_CAPABILITY_ID, "test-approval-token", approved);
            assertEquals(org.springframework.http.HttpStatus.CONFLICT, replayedApproval.getStatusCode());
            var second = controller.execute(PR_CAPABILITY_ID, request);
            ActionResult secondBody = (ActionResult) second.getBody();

            assertEquals(ErrorType.APPROVAL_DUPLICATE, secondBody.errorType());
            assertEquals(1, dispatchCount.get());

            releaseFirstDispatch.countDown();
            ActionResult firstBody = (ActionResult) first.get(5, TimeUnit.SECONDS).getBody();
            assertTrue(firstBody.success());
        } finally {
            releaseFirstDispatch.countDown();
            executor.shutdownNow();
        }
    }

    @Test
    void dispatchExceptionReturnsReplayableFailureAndConsumesApproval() throws Exception {
        Map<String, Object> parameters = prParams();
        String hash = new ParameterSnapshotHasher().hash(parameters);
        ApprovalRecord approved = new ApprovalRecord(
                "appr-dispatch-error", PR_CAPABILITY_ID, hash,
                parameters.entrySet().stream().collect(java.util.stream.Collectors.toMap(
                        Map.Entry::getKey, entry -> String.valueOf(entry.getValue()))),
                "user", Instant.now(), Instant.now().plusSeconds(600), "approved");
        approvalStore.save(approved);
        failDispatch.set(true);

        var response = controller.execute(
                PR_CAPABILITY_ID,
                new CapabilityRequest(parameters, approved.approvalId(), hash));
        ActionResult body = (ActionResult) response.getBody();

        assertFalse(body.success());
        assertEquals(ErrorType.SAP_COMMUNICATION_ERROR, body.errorType());
        assertEquals(CommitStatus.none, body.commitStatus());
        assertEquals("executed", approvalStore.find(approved.approvalId()).orElseThrow().status());
        String trace = Files.readString(traceFile);
        assertTrue(trace.contains("\"errorType\":\"SAP_COMMUNICATION_ERROR\""));
        assertTrue(trace.contains("\"commitStatus\":\"none\""));
        assertFalse(trace.contains("SAP-PRD"));

        var replay = controller.execute(
                PR_CAPABILITY_ID,
                new CapabilityRequest(parameters, approved.approvalId(), hash));
        assertEquals(
                ErrorType.APPROVAL_DUPLICATE,
                ((ActionResult) replay.getBody()).errorType());
        assertEquals(1, dispatchCount.get());
    }

    private static Map<String, Object> prParams() {
        return Map.of(
                "material", "M001",
                "plant", "1000",
                "quantity", "10",
                "unit", "EA",
                "delivery_date", "2026-08-01");
    }

    private static CapabilityRequest planAwareRequest(
            String approvalId,
            String registrySnapshotId,
            String capabilityVersion,
            String subjectHash
    ) {
        return new CapabilityRequest(
                prParams(),
                approvalId,
                new ParameterSnapshotHasher().hash(prParams()),
                registrySnapshotId,
                capabilityVersion,
                subjectHash);
    }

    private static ApprovalRecord planAwareRecord(String approvalId) {
        return new ApprovalRecord(
                approvalId,
                PR_CAPABILITY_ID,
                new ParameterSnapshotHasher().hash(prParams()),
                prParams().entrySet().stream().collect(java.util.stream.Collectors.toMap(
                        Map.Entry::getKey, entry -> String.valueOf(entry.getValue()))),
                "run-owner",
                Instant.now(),
                Instant.now().plusSeconds(600),
                "approved",
                "snapshot-21",
                "2.1.0",
                "sha256:subject");
    }

    private static CapabilityDefinition prCreateDraft() {
        return new CapabilityDefinition(
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
                        Map.of("material", "PRITEM.MATERIAL", "plant", "PRITEM.PLANT"),
                        Map.of("prNumber", "EXPORTS.NUMBER", "returnMessages", "RETURN")),
                new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.pr.create-draft"),
                new CapabilityDefinition.Governance(SideEffect.sap_write, true, "human_required", "internal", true));
    }

    private static CapabilityDefinition inventoryRead() {
        return new CapabilityDefinition(
                READ_CAPABILITY_ID,
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
                        new CapabilityDefinition.InputField("plant", "plant", "sapnexus:Plant", true, "string", 1, 4, "PLANT")),
                List.of(),
                new CapabilityDefinition.Executor("JCO_RFC", "BAPI_MATERIAL_STOCK_REQ_LIST", Map.of("material", "MATERIAL", "plant", "PLANT"), Map.of()),
                new CapabilityDefinition.ExecutorBinding("JCO_RFC", "sap.mm.inventory.md04-stock-req-list"),
                new CapabilityDefinition.Governance(SideEffect.none, false, "not_required", "internal", true));
    }
}

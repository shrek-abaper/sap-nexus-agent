package com.sapnexus.gateway.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import com.sapnexus.gateway.approval.ApprovalGuard;
import com.sapnexus.gateway.approval.ApprovalStore;
import com.sapnexus.gateway.approval.InMemoryApprovalStore;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityRegistryLoader;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ActionResult;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.trace.TraceWriter;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

/**
 * Task 9: READ/WRITE path isolation regression tests.
 *
 * <p>Locks in the hard boundary established in Task 7/8 so future changes cannot
 * silently break it:
 * <ul>
 *   <li>READ (Function) capabilities bypass the approval guard and never return
 *       an APPROVAL_* error type, even when the dispatcher is empty.</li>
 *   <li>WRITE (Action) capabilities are blocked at the approval guard before
 *       reaching dispatch when no approval is supplied.</li>
 * </ul>
 * The test loads the real registry (registry/capabilities.yaml) and uses an empty
 * dispatcher, so the read path resolves to UNSUPPORTED_EXECUTOR (proving it
 * skipped the guard) rather than APPROVAL_REQUIRED.
 */
class ReadWriteIsolationTest {

    @Test
    void readPathSkipsApprovalGuard() {
        CapabilityController controller = newController();

        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000"),
                null,
                null
        );
        var response = controller.execute("MM.Inventory.GetAvailability", request);
        var body = (ExecutionResult) response.getBody();
        // Function path does not return APPROVAL_* even without approvalId.
        assertTrue(body.errorType() != ErrorType.APPROVAL_REQUIRED
                && body.errorType() != ErrorType.APPROVAL_EXPIRED
                && body.errorType() != ErrorType.APPROVAL_VERSION_MISMATCH
                && body.errorType() != ErrorType.APPROVAL_DUPLICATE,
                "Function path must not trigger approval guard, got: " + body.errorType());
    }

    @Test
    void writePathBlocksWithoutApproval() {
        CapabilityController controller = newController();

        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000",
                        "quantity", "10", "unit", "EA", "delivery_date", "2026-08-01",
                        "purchasing_group", "601"),
                null,
                null
        );
        var response = controller.execute("MM.PR.CreateDraft", request);
        var body = (ActionResult) response.getBody();
        assertEquals(ErrorType.APPROVAL_REQUIRED, body.errorType());
    }

    private static CapabilityController newController() {
        ApprovalStore approvalStore = new InMemoryApprovalStore();
        CapabilityRegistry registry = loadRegistry();
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of());
        @SuppressWarnings("unchecked")
        ObjectProvider<TraceWriter> traceProvider = org.mockito.Mockito.mock(ObjectProvider.class);
        return new CapabilityController(
                registry, dispatcher, traceProvider, approvalStore, new ApprovalGuard(), "test-approval-token");
    }

    private static CapabilityRegistry loadRegistry() {
        Path dir = Path.of(System.getProperty("user.dir"));
        while (dir != null && !Files.exists(dir.resolve("registry/capabilities.yaml"))) {
            dir = dir.getParent();
        }
        if (dir == null) {
            throw new IllegalStateException(
                    "registry/capabilities.yaml not found from " + System.getProperty("user.dir"));
        }
        return new CapabilityRegistryLoader().load(dir.resolve("registry/capabilities.yaml"));
    }
}

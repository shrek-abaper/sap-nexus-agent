package com.sapnexus.gateway.execution;

import com.sapnexus.gateway.jco.JcoCapabilityExecutor;
import com.sapnexus.gateway.jco.PrCreateDraftExecutor;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.result.ExecutionResult;
import org.springframework.stereotype.Component;

import java.util.List;

@Component("JCO_RFC")
public class JcoRfcTechnicalAdapter implements TechnicalAdapter {
    private static final String PR_CREATE_DRAFT = "MM.PR.CreateDraft";

    private final List<JcoCapabilityExecutor> executors;
    private final CapabilityRegistry registry;

    public JcoRfcTechnicalAdapter(List<JcoCapabilityExecutor> executors, CapabilityRegistry registry) {
        this.executors = executors == null ? List.of() : executors;
        this.registry = registry;
    }

    @Override
    public TechnicalExecutionResult execute(TechnicalExecutionRequest request) {
        CapabilityDefinition capability = registry.findEnabled(request.capabilityId())
                .orElseThrow(() -> new IllegalStateException("Capability not found or disabled: " + request.capabilityId()));
        JcoCapabilityExecutor executor = selectExecutor(capability);
        ExecutionResult result = executor.execute(capability, request.parameters(), request.traceId());
        return TechnicalExecutionResult.fromExecutionResult(request.bindingId(), result);
    }

    /**
     * Routes by capabilityId to enforce READ/WRITE isolation.
     * WRITE (MM.PR.CreateDraft) -> PrCreateDraftExecutor (internal commit/rollback guard).
     * READ (everything else) -> a read-only executor that never commits or rolls back.
     */
    private JcoCapabilityExecutor selectExecutor(CapabilityDefinition capability) {
        if (PR_CREATE_DRAFT.equals(capability.capabilityId())) {
            return executors.stream()
                    .filter(e -> e instanceof PrCreateDraftExecutor)
                    .findFirst()
                    .orElseThrow(() -> new IllegalStateException(
                            "PrCreateDraftExecutor not found for " + capability.capabilityId()));
        }
        return executors.stream()
                .filter(e -> !(e instanceof PrCreateDraftExecutor))
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("No read JcoCapabilityExecutor available"));
    }
}

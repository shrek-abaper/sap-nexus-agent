package com.sapnexus.gateway.execution;

import com.sapnexus.gateway.result.ErrorType;

import java.util.Map;

public class TechnicalExecutionDispatcher {
    private final Map<String, TechnicalAdapter> adapters;

    public TechnicalExecutionDispatcher(Map<String, TechnicalAdapter> adapters) {
        this.adapters = adapters == null ? Map.of() : Map.copyOf(adapters);
    }

    public TechnicalExecutionResult dispatch(TechnicalExecutionRequest request) {
        TechnicalAdapter adapter = adapters.get(request.executorType());
        if (adapter == null) {
            return TechnicalExecutionResult.failure(
                    request.traceId(),
                    request.capabilityId(),
                    request.bindingId(),
                    request.executorType(),
                    ErrorType.UNSUPPORTED_EXECUTOR,
                    "Unsupported executor type: " + request.executorType(),
                    0
            );
        }
        return adapter.execute(request);
    }
}

package com.sapnexus.gateway.execution;

import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class TechnicalExecutionDispatcherTest {
    @Test
    void dispatchesJcoRfcBindingToRegisteredAdapter() {
        TechnicalAdapter adapter = request -> TechnicalExecutionResult.success(
                request.traceId(),
                request.capabilityId(),
                request.bindingId(),
                request.executorType(),
                List.of(),
                Map.of("availableQuantity", 42),
                5,
                Map.of("rfcName", "BAPI_MATERIAL_STOCK_REQ_LIST")
        );
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of("JCO_RFC", adapter));

        TechnicalExecutionResult result = dispatcher.dispatch(new TechnicalExecutionRequest(
                "trace-1",
                "MM.Inventory.GetAvailability",
                "sap.mm.inventory.md04-stock-req-list",
                "JCO_RFC",
                "execute",
                Map.of("material", "MAT-001", "plant", "1000"),
                Map.of("sideEffect", "none"),
                Map.of()
        ));

        assertThat(result.success()).isTrue();
        assertThat(result.bindingId()).isEqualTo("sap.mm.inventory.md04-stock-req-list");
    }

    @Test
    void failsClosedForUnsupportedExecutorType() {
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of());

        TechnicalExecutionResult result = dispatcher.dispatch(new TechnicalExecutionRequest(
                "trace-1",
                "MM.Inventory.GetAvailability",
                "sap.mm.inventory.odata",
                "ODATA",
                "execute",
                Map.of(),
                Map.of(),
                Map.of()
        ));

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.UNSUPPORTED_EXECUTOR);
    }
}

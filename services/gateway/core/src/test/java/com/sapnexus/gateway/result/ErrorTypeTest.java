package com.sapnexus.gateway.result;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import com.sapnexus.gateway.registry.SideEffect;
import org.junit.jupiter.api.Test;

class ErrorTypeTest {

    @Test
    void approvalErrorTypesExist() {
        assertNotNull(ErrorType.valueOf("APPROVAL_REQUIRED"));
        assertNotNull(ErrorType.valueOf("APPROVAL_EXPIRED"));
        assertNotNull(ErrorType.valueOf("APPROVAL_VERSION_MISMATCH"));
        assertNotNull(ErrorType.valueOf("APPROVAL_DUPLICATE"));
        assertNotNull(ErrorType.valueOf("SAP_COMMIT_ERROR"));
    }

    @Test
    void commitStatusValuesExist() {
        assertEquals("committed", CommitStatus.committed.name());
        assertEquals("rolled_back", CommitStatus.rolled_back.name());
        assertEquals("rollback_failed", CommitStatus.rollback_failed.name());
        assertEquals("none", CommitStatus.none.name());
    }

    @Test
    void sideEffectSapWriteExists() {
        assertNotNull(SideEffect.valueOf("sap_write"));
    }
}

package com.sapnexus.gateway.result;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class ActionResultTest {

    @Test
    void successFactoryProducesCommittedResult() {
        List<SapReturnMessage> messages = List.of(new SapReturnMessage("S", "M06", "017", "PR created", ""));
        ActionResult result = ActionResult.success(
                "trace-001",
                "MM.PR.CreateDraft",
                "0010001234",
                messages,
                150L
        );
        assertTrue(result.success());
        assertEquals("0010001234", result.prNumber());
        assertEquals(CommitStatus.committed, result.commitStatus());
        assertEquals(ErrorType.NONE, result.errorType());
        assertEquals(150L, result.durationMs());
    }

    @Test
    void genericFailureFactoryDoesNotInventRollback() {
        ActionResult result = ActionResult.failure(
                "trace-002",
                "MM.PR.CreateDraft",
                ErrorType.SAP_BUSINESS_ERROR,
                "BAPI returned E",
                80L
        );
        assertEquals(false, result.success());
        assertEquals("", result.prNumber());
        assertEquals(CommitStatus.none, result.commitStatus());
        assertEquals(ErrorType.SAP_BUSINESS_ERROR, result.errorType());
    }

    @Test
    void executionResultUsesExplicitRollbackOutcome() {
        ExecutionResult execution = new ExecutionResult(
                "trace-rollback", "MM.PR.CreateDraft", false,
                new ExecutionResult.ExecutorMetadata("JCO_RFC", "BAPI_PR_CREATE"),
                List.of(new SapReturnMessage("E", "M06", "001", "Rejected", "")),
                Map.of("commitStatus", "rolled_back"), 12L,
                ErrorType.SAP_BUSINESS_ERROR);

        ActionResult result = ActionResult.fromExecutionResult(execution);

        assertEquals(CommitStatus.rolled_back, result.commitStatus());
    }

    @Test
    void preSapFailureHasNoTransactionOutcome() {
        ExecutionResult execution = ExecutionResult.failure(
                "trace-pre-sap", "MM.PR.CreateDraft", "JCO_RFC", "BAPI_PR_CREATE",
                ErrorType.SAP_AUTH_ERROR, "Logon failed", 5L);

        ActionResult result = ActionResult.fromExecutionResult(execution);

        assertEquals(CommitStatus.none, result.commitStatus());
    }

    @Test
    void successfulExecutionWithoutExplicitOutcomeDoesNotInventCommit() {
        ExecutionResult execution = ExecutionResult.success(
                "trace-success", "MM.PR.CreateDraft", "JCO_RFC", "BAPI_PR_CREATE",
                List.of(), Map.of("prNumber", "10137471"), 10L);

        ActionResult result = ActionResult.fromExecutionResult(execution);

        assertEquals(CommitStatus.none, result.commitStatus());
    }

    @Test
    void approvalFailureProducesNoneCommitStatus() {
        ActionResult result = ActionResult.failure(
                "trace-003",
                "MM.PR.CreateDraft",
                ErrorType.APPROVAL_REQUIRED,
                "No approval record",
                1L
        );
        assertEquals(CommitStatus.none, result.commitStatus());
        assertEquals(ErrorType.APPROVAL_REQUIRED, result.errorType());
    }
}

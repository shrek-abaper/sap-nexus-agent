package com.sapnexus.gateway.trace;

import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ActionResult;
import com.sapnexus.gateway.result.CommitStatus;
import com.sapnexus.gateway.result.SapReturnMessage;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class TraceWriterTest {
    @TempDir
    Path tempDir;

    @Test
    void writesJsonlTraceRecordWithRequiredFields() throws Exception {
        Path traceFile = tempDir.resolve("runtime/gateway-jco/traces.jsonl");
        TraceWriter writer = new TraceWriter(traceFile);

        writer.write(TraceRecord.of("trace-1", "validate", "MM.Inventory.GetAvailability", Map.of("material", "MAT-001", "plant", "1000"), true, 12, ErrorType.NONE));

        String content = Files.readString(traceFile);
        assertThat(content).contains("\"traceId\":\"trace-1\"");
        assertThat(content).contains("\"operation\":\"validate\"");
        assertThat(content).contains("\"capabilityId\":\"MM.Inventory.GetAvailability\"");
        assertThat(content).contains("\"success\":true");
        assertThat(content).contains("\"durationMs\":12");
        assertThat(content).contains("\"errorType\":\"NONE\"");
        assertThat(content).contains("\"resultSummary\":{}");
    }

    @Test
    void writeTraceReplaysSanitizedActionResult() throws Exception {
        Path traceFile = tempDir.resolve("write-traces.jsonl");
        TraceWriter writer = new TraceWriter(traceFile);
        ActionResult result = new ActionResult(
                "trace-write",
                "MM.PR.CreateDraft",
                true,
                "10137471",
                CommitStatus.committed,
                List.of(new SapReturnMessage(
                        "S", "06", "017", "Purchase requisition created", "")),
                42,
                ErrorType.NONE);

        writer.write(TraceRecord.ofAction(
                "trace-write",
                "execute",
                "MM.PR.CreateDraft",
                Map.of("material", "M001", "plant", "1000"),
                result));

        String content = Files.readString(traceFile);
        assertThat(content).contains("\"prNumber\":\"10137471\"");
        assertThat(content).contains("\"commitStatus\":\"committed\"");
        assertThat(content).contains("\"message\":\"Purchase requisition created\"");
    }

    @Test
    void writeTraceReplaysFailureWithoutLeakingSecrets() throws Exception {
        Path traceFile = tempDir.resolve("failed-write-traces.jsonl");
        TraceWriter writer = new TraceWriter(traceFile);
        ActionResult result = new ActionResult(
                "trace-failed-write",
                "MM.PR.CreateDraft",
                false,
                "",
                CommitStatus.rolled_back,
                List.of(new SapReturnMessage(
                        "E", "06", "001",
                        "Rejected password=super-secret destination SAP-PRD unavailable "
                                + "token: abc123 Authorization: Bearer bearer-secret "
                                + "\"secret\":\"json-secret\"",
                        "MATERIAL")),
                18,
                ErrorType.SAP_BUSINESS_ERROR);

        writer.write(TraceRecord.ofAction(
                "trace-failed-write",
                "execute",
                "MM.PR.CreateDraft",
                Map.of("material", "M001", "SAP_PASSWORD", "super-secret"),
                result));

        String content = Files.readString(traceFile);
        assertThat(content).contains("\"commitStatus\":\"rolled_back\"");
        assertThat(content).contains("\"errorType\":\"SAP_BUSINESS_ERROR\"");
        assertThat(content).doesNotContain("super-secret");
        assertThat(content).doesNotContain("SAP-PRD");
        assertThat(content).doesNotContain("abc123");
        assertThat(content).doesNotContain("bearer-secret");
        assertThat(content).doesNotContain("json-secret");
        assertThat(content).doesNotContain("SAP_PASSWORD");
    }

    @Test
    void writeTraceReplaysCommitFailure() throws Exception {
        Path traceFile = tempDir.resolve("commit-failure-traces.jsonl");
        TraceWriter writer = new TraceWriter(traceFile);
        ActionResult result = new ActionResult(
                "trace-commit-failure",
                "MM.PR.CreateDraft",
                false,
                "",
                CommitStatus.rolled_back,
                List.of(new SapReturnMessage(
                        "E", "00", "001", "Commit failed", "")),
                21,
                ErrorType.SAP_COMMIT_ERROR);

        writer.write(TraceRecord.ofAction(
                result.traceId(),
                "execute",
                result.capabilityId(),
                Map.of("material", "M001"),
                result));

        String content = Files.readString(traceFile);
        assertThat(content).contains("\"commitStatus\":\"rolled_back\"");
        assertThat(content).contains("\"message\":\"Commit failed\"");
        assertThat(content).contains("\"errorType\":\"SAP_COMMIT_ERROR\"");
    }

    @Test
    void traceDoesNotContainSecretsOrRawSapDestinationDetails() throws Exception {
        Path traceFile = tempDir.resolve("traces.jsonl");
        TraceWriter writer = new TraceWriter(traceFile);

        writer.write(TraceRecord.of("trace-2", "execute", "MM.Inventory.GetAvailability", Map.of(
                "SAP_PASSWORD", "secret",
                "password", "secret",
                "token", "abc",
                "material", "MAT-001"
        ), false, 3, ErrorType.INVALID_PARAMETER));

        String content = Files.readString(traceFile);
        assertThat(content).doesNotContain("secret");
        assertThat(content).doesNotContain("SAP_PASSWORD");
        assertThat(content).doesNotContain("token");
        assertThat(content).contains("\"material\":\"MAT-001\"");
    }
    @Test
    void traceRecursivelyDropsUnsafeNestedParameters() throws Exception {
        Path traceFile = tempDir.resolve("nested-traces.jsonl");
        TraceWriter writer = new TraceWriter(traceFile);

        writer.write(TraceRecord.of("trace-3", "execute", "MM.Inventory.GetAvailability", Map.of(
                "material", "MAT-001",
                "rfcName", "Z_UNSAFE_RFC",
                "destination", Map.of("SAP_PASSWORD", "secret", "ashost", "sap.example.local"),
                "env", Map.of("token", "abc"),
                "config", Map.of("password", "secret")
        ), false, 5, ErrorType.INVALID_PARAMETER));

        String content = Files.readString(traceFile);
        assertThat(content).contains("\"material\":\"MAT-001\"");
        assertThat(content).doesNotContain("Z_UNSAFE_RFC");
        assertThat(content).doesNotContain("destination");
        assertThat(content).doesNotContain("env");
        assertThat(content).doesNotContain("config");
        assertThat(content).doesNotContain("SAP_PASSWORD");
        assertThat(content).doesNotContain("secret");
        assertThat(content).doesNotContain("token");
    }

}

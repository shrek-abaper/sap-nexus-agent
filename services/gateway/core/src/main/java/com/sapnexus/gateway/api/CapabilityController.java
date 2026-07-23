package com.sapnexus.gateway.api;

import com.sapnexus.gateway.approval.ApprovalGuard;
import com.sapnexus.gateway.approval.ApprovalGuardResult;
import com.sapnexus.gateway.approval.ApprovalRecord;
import com.sapnexus.gateway.approval.ApprovalStore;
import com.sapnexus.gateway.approval.ParameterSnapshotHasher;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.ActionResult;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.trace.TraceRecord;
import com.sapnexus.gateway.trace.TraceWriter;
import com.sapnexus.gateway.validation.CapabilityValidationService;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@RestController
public class CapabilityController {
    private final CapabilityRegistry registry;
    private final CapabilityValidationService validationService;
    private final TechnicalExecutionDispatcher dispatcher;
    private final ObjectProvider<TraceWriter> traceWriter;
    private final ApprovalStore approvalStore;
    private final ApprovalGuard approvalGuard;
    private final String approvalToken;
    private final ParameterSnapshotHasher parameterSnapshotHasher = new ParameterSnapshotHasher();

    public CapabilityController(CapabilityRegistry registry, TechnicalExecutionDispatcher dispatcher,
                                ObjectProvider<TraceWriter> traceWriter,
                                ApprovalStore approvalStore, ApprovalGuard approvalGuard,
                                @Value("${SAP_NEXUS_APPROVAL_TOKEN:}") String approvalToken) {
        this.registry = registry;
        this.validationService = new CapabilityValidationService(registry);
        this.dispatcher = dispatcher;
        this.traceWriter = traceWriter;
        this.approvalStore = approvalStore;
        this.approvalGuard = approvalGuard;
        this.approvalToken = approvalToken == null ? "" : approvalToken;
    }

    @GetMapping("/capabilities")
    public List<CapabilityCatalogItem> capabilities() {
        return registry.enabledCapabilities().stream()
                .map(CapabilityCatalogItem::from)
                .toList();
    }

    @PostMapping("/capabilities/{capabilityId}/validate")
    public ResponseEntity<CapabilityResponse> validate(
            @PathVariable String capabilityId,
            @RequestBody(required = false) CapabilityRequest request
    ) {
        java.util.Map<String, Object> parameters = request == null ? java.util.Map.of() : request.safeParameters();
        long started = System.nanoTime();
        CapabilityResponse response = validationService.validate(capabilityId, parameters);
        writeTrace(response.traceId(), "validate", capabilityId, parameters, response.success(), elapsedMs(started), response.errorType());
        return ResponseEntity.status(statusFor(response.errorType())).body(response);
    }


    @PostMapping("/capabilities/{capabilityId}/approve")
    public ResponseEntity<java.util.Map<String, String>> approve(
            @PathVariable String capabilityId,
            @RequestHeader(value = "X-SAP-Nexus-Approval-Token", required = false) String providedToken,
            @RequestBody ApprovalRecord record
    ) {
        if (!isAuthorizedApprovalService(providedToken)) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body(Map.of("errorType", "APPROVAL_SERVICE_FORBIDDEN"));
        }
        if (!isValidApprovedRecord(capabilityId, record)) {
            return ResponseEntity.badRequest()
                    .body(Map.of("errorType", "INVALID_APPROVAL_RECORD"));
        }
        if (!approvalStore.save(record)) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("errorType", ErrorType.APPROVAL_DUPLICATE.name()));
        }
        return ResponseEntity.ok(java.util.Map.of("approvalId", record.approvalId()));
    }

    private boolean isAuthorizedApprovalService(String providedToken) {
        if (approvalToken.isBlank() || providedToken == null || providedToken.isBlank()) {
            return false;
        }
        return MessageDigest.isEqual(
                approvalToken.getBytes(StandardCharsets.UTF_8),
                providedToken.getBytes(StandardCharsets.UTF_8));
    }

    private boolean isValidApprovedRecord(String capabilityId, ApprovalRecord record) {
        if (record == null
                || !capabilityId.equals(record.capabilityId())
                || !"approved".equals(record.status())
                || record.approvalId() == null
                || record.approvalId().isBlank()
                || record.approvedAt() == null
                || record.expiresAt() == null
                || record.parameterSnapshotHash() == null
                || !record.parameterSnapshotHash().equals(
                        parameterSnapshotHasher.hash(record.parameters()))
                || record.expiresAt().isBefore(record.approvedAt())) {
            return false;
        }
        long ttlSeconds = Duration.between(record.approvedAt(), record.expiresAt()).getSeconds();
        Instant now = Instant.now();
        return ttlSeconds > 0
                && ttlSeconds <= 600
                && !record.approvedAt().isAfter(now.plusSeconds(5))
                && record.expiresAt().isAfter(now);
    }


    @PostMapping("/capabilities/{capabilityId}/execute")
    public ResponseEntity<?> execute(
            @PathVariable String capabilityId,
            @RequestBody(required = false) CapabilityRequest request
    ) {
        Set<String> technicalOverrides = request == null ? Set.of() : request.technicalOverrideKeys();
        if (!technicalOverrides.isEmpty()) {
            String traceId = UUID.randomUUID().toString();
            String message = "Technical override fields are not allowed: "
                    + String.join(", ", technicalOverrides);
            if (isActionCapability(capabilityId)) {
                ActionResult response = ActionResult.failure(
                        traceId, capabilityId, ErrorType.INVALID_PARAMETER, message, 0);
                writeActionTrace(capabilityId, Map.of(), response);
                return ResponseEntity.status(statusFor(response.errorType())).body(response);
            }
            CapabilityResponse response = CapabilityResponse.failure(
                    traceId, capabilityId, ErrorType.INVALID_PARAMETER, message);
            writeTrace(response.traceId(), "execute", capabilityId, Map.of(), false, 0, response.errorType());
            return ResponseEntity.status(statusFor(response.errorType())).body(response);
        }

        java.util.Map<String, Object> parameters = request == null ? java.util.Map.of() : request.safeParameters();
        CapabilityResponse validation = validationService.validate(capabilityId, parameters);
        if (!validation.success()) {
            if (isActionCapability(capabilityId)) {
                ActionResult response = ActionResult.failure(
                        validation.traceId(), capabilityId, validation.errorType(),
                        validation.messages().isEmpty()
                                ? validation.errorType().name()
                                : validation.messages().get(0),
                        0);
                writeActionTrace(capabilityId, parameters, response);
                return ResponseEntity.status(statusFor(response.errorType())).body(response);
            }
            writeTrace(validation.traceId(), "execute", capabilityId, parameters, false, 0, validation.errorType());
            return ResponseEntity.status(statusFor(validation.errorType())).body(validation);
        }
        CapabilityDefinition capability = registry.findEnabled(capabilityId).orElseThrow();

        if (capability.kind() == CapabilityKind.Action) {
            String approvalId = request.approvalId();
            String parameterHash = request.parameterSnapshotHash();
            ApprovalRecord record = approvalId == null ? null : approvalStore.find(approvalId).orElse(null);
            ApprovalGuardResult guardResult = approvalGuard.check(
                    record, capabilityId, parameters, parameterHash, Instant.now());
            if (guardResult.rejected()) {
                String executorType = capability.executor() != null
                        ? capability.executor().type() : capability.executorBinding().type();
                String rfcName = capability.executor() != null ? capability.executor().rfcName() : null;
                ExecutionResult rejection = ExecutionResult.failure(
                        validation.traceId(),
                        capabilityId,
                        executorType,
                        rfcName,
                        guardResult.errorType(),
                        guardResult.errorType().name(),
                        0
                );
                ActionResult actionResult = ActionResult.fromExecutionResult(rejection);
                writeActionTrace(capabilityId, parameters, actionResult);
                return ResponseEntity.status(statusFor(rejection.errorType()))
                        .body(actionResult);
            }
            if (approvalStore.claimForExecution(approvalId).isEmpty()) {
                String executorType = capability.executor() != null
                        ? capability.executor().type() : capability.executorBinding().type();
                String rfcName = capability.executor() != null ? capability.executor().rfcName() : null;
                ExecutionResult rejection = ExecutionResult.failure(
                        validation.traceId(),
                        capabilityId,
                        executorType,
                        rfcName,
                        ErrorType.APPROVAL_DUPLICATE,
                        ErrorType.APPROVAL_DUPLICATE.name(),
                        0
                );
                ActionResult actionResult = ActionResult.fromExecutionResult(rejection);
                writeActionTrace(capabilityId, parameters, actionResult);
                return ResponseEntity.status(statusFor(rejection.errorType())).body(actionResult);
            }
        }

        TechnicalExecutionRequest technicalRequest = new TechnicalExecutionRequest(
                validation.traceId(),
                capability.capabilityId(),
                capability.executorBinding().bindingId(),
                capability.executorBinding().type(),
                "execute",
                parameters,
                Map.of("sideEffect", capability.governance().sideEffect().name()),
                Map.of()
        );
        TechnicalExecutionResult technicalResult;
        try {
            technicalResult = dispatcher.dispatch(technicalRequest);
        } catch (RuntimeException exception) {
            if (capability.kind() != CapabilityKind.Action) {
                throw exception;
            }
            technicalResult = TechnicalExecutionResult.failure(
                    validation.traceId(),
                    capabilityId,
                    capability.executorBinding().bindingId(),
                    capability.executorBinding().type(),
                    ErrorType.SAP_COMMUNICATION_ERROR,
                    exception.getMessage() == null ? "Action dispatch failed" : exception.getMessage(),
                    0);
        } finally {
            if (capability.kind() == CapabilityKind.Action && request.approvalId() != null) {
                approvalStore.markExecuted(request.approvalId());
            }
        }
        ExecutionResult result = technicalResult.toExecutionResult(capability);
        if (capability.kind() == CapabilityKind.Action) {
            ActionResult actionResult = ActionResult.fromExecutionResult(result);
            writeActionTrace(capabilityId, parameters, actionResult);
            return ResponseEntity.status(statusFor(result.errorType())).body(actionResult);
        }
        writeTrace(result.traceId(), "execute", capabilityId, parameters, result.success(), result.durationMs(), result.errorType());
        return ResponseEntity.status(statusFor(result.errorType())).body(result);
    }


    private void writeTrace(String traceId, String operation, String capabilityId, java.util.Map<String, Object> parameters, boolean success, long durationMs, ErrorType errorType) {
        traceWriter.ifAvailable(writer -> writer.write(TraceRecord.of(traceId, operation, capabilityId, parameters, success, durationMs, errorType)));
    }

    private void writeActionTrace(String capabilityId, Map<String, Object> parameters, ActionResult result) {
        traceWriter.ifAvailable(writer -> writer.write(TraceRecord.ofAction(
                result.traceId(), "execute", capabilityId, parameters, result)));
    }

    private boolean isActionCapability(String capabilityId) {
        return registry.findEnabled(capabilityId)
                .map(capability -> capability.kind() == CapabilityKind.Action)
                .orElse(false);
    }

    private long elapsedMs(long started) {
        return (System.nanoTime() - started) / 1_000_000;
    }

    private HttpStatus statusFor(ErrorType errorType) {
        return switch (errorType) {
            case NONE -> HttpStatus.OK;
            case CAPABILITY_NOT_FOUND -> HttpStatus.NOT_FOUND;
            default -> HttpStatus.BAD_REQUEST;
        };
    }

    public record CapabilityCatalogItem(
            String capabilityId,
            String kind,
            String domain,
            String businessObject,
            String ontologyIri,
            ExecutorView executor,
            GovernanceView governance
    ) {
        static CapabilityCatalogItem from(CapabilityDefinition capability) {
            return new CapabilityCatalogItem(
                    capability.capabilityId(),
                    capability.kind().name(),
                    capability.domain(),
                    capability.businessObject(),
                    capability.ontologyIri(),
                    new ExecutorView(capability.executor().type()),
                    new GovernanceView(
                            capability.governance().sideEffect().name(),
                            capability.governance().requiresApproval()
                    )
            );
        }
    }

    public record ExecutorView(String type) {
    }

    public record GovernanceView(String sideEffect, boolean requiresApproval) {
    }
}

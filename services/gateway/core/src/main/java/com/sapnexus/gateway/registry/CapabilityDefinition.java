package com.sapnexus.gateway.registry;

import java.util.List;
import java.util.Map;

public record CapabilityDefinition(
        String capabilityId,
        String name,
        String description,
        CapabilityStatus status,
        CapabilityKind kind,
        String domain,
        String businessObject,
        String ontologyIri,
        String semanticType,
        List<InputField> inputs,
        List<OutputField> outputs,
        Executor executor,
        ExecutorBinding executorBinding,
        Governance governance
) {
    public CapabilityDefinition(
            String capabilityId,
            String name,
            String description,
            CapabilityStatus status,
            CapabilityKind kind,
            String domain,
            String businessObject,
            String ontologyIri,
            String semanticType,
            List<InputField> inputs,
            List<OutputField> outputs,
            Executor executor,
            Governance governance
    ) {
        this(
                capabilityId,
                name,
                description,
                status,
                kind,
                domain,
                businessObject,
                ontologyIri,
                semanticType,
                inputs,
                outputs,
                executor,
                new ExecutorBinding(executor == null ? null : executor.type(), null),
                governance
        );
    }

    public record InputField(
            String name,
            String semanticName,
            String semanticType,
            boolean required,
            String type,
            Integer minLength,
            Integer maxLength,
            String sapParameter,
            String pattern
    ) {
        public InputField(
                String name,
                String semanticName,
                String semanticType,
                boolean required,
                String type,
                Integer minLength,
                Integer maxLength,
                String sapParameter
        ) {
            this(name, semanticName, semanticType, required, type, minLength, maxLength, sapParameter, null);
        }
    }

    public record OutputField(
            String name,
            String semanticType,
            String type,
            String evidenceRole
    ) {
    }

    public record Executor(
            String type,
            String rfcName,
            Map<String, String> inputMapping,
            Map<String, String> outputMapping
    ) {
    }

    public record ExecutorBinding(
            String type,
            String bindingId
    ) {
    }

    public record Governance(
            SideEffect sideEffect,
            boolean requiresApproval,
            String approvalPolicy,
            String dataClassification,
            boolean auditRequired
    ) {
    }
}

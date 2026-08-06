package com.sapnexus.gateway.registry;

import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class CapabilityRegistryLoader {
    private final CapabilityRegistryValidator validator;

    public CapabilityRegistryLoader() {
        this(new CapabilityRegistryValidator());
    }

    public CapabilityRegistryLoader(CapabilityRegistryValidator validator) {
        this.validator = validator;
    }

    public CapabilityRegistry load(Path path) {
        try (Reader reader = Files.newBufferedReader(path)) {
            Object loaded = new Yaml().load(reader);
            if (!(loaded instanceof Map<?, ?> root)) {
                throw new RegistryValidationException("registry root object is required");
            }
            CapabilityRegistry registry = parseRegistry(root);
            validator.validate(registry);
            return registry;
        } catch (IOException e) {
            throw new RegistryValidationException("Unable to read registry: " + path);
        }
    }

    private CapabilityRegistry parseRegistry(Map<?, ?> root) {
        int version = asInt(root.get("version"));
        List<CapabilityDefinition> capabilities = asList(root.get("capabilities")).stream()
                .map(this::asMap)
                .map(this::parseCapability)
                .toList();
        return new CapabilityRegistry(version, capabilities);
    }

    private CapabilityDefinition parseCapability(Map<String, Object> raw) {
        return new CapabilityDefinition(
                asString(raw.get("capabilityId")),
                asString(raw.get("name")),
                asString(raw.get("description")),
                asEnum(CapabilityStatus.class, raw.get("status")),
                asEnum(CapabilityKind.class, raw.get("kind")),
                asString(raw.get("domain")),
                asString(raw.get("businessObject")),
                asString(raw.get("ontologyIri")),
                asString(raw.get("semanticType")),
                parseInputs(asList(raw.get("inputs"))),
                parseOutputs(asList(raw.get("outputs"))),
                parseExecutor(asMap(raw.get("executor"))),
                parseExecutorBinding(asMap(raw.get("executorBinding")), asMap(raw.get("executor"))),
                parseGovernance(asMap(raw.get("governance")))
        );
    }

    private List<CapabilityDefinition.InputField> parseInputs(List<Object> rawInputs) {
        List<CapabilityDefinition.InputField> inputs = new ArrayList<>();
        for (Object item : rawInputs) {
            Map<String, Object> raw = asMap(item);
            inputs.add(new CapabilityDefinition.InputField(
                    asString(raw.get("name")),
                    asString(raw.get("semanticName")),
                    asString(raw.get("semanticType")),
                    Boolean.TRUE.equals(raw.get("required")),
                    asString(raw.get("type")),
                    asNullableInt(raw.get("minLength")),
                    asNullableInt(raw.get("maxLength")),
                    asString(raw.get("sapParameter")),
                    asString(raw.get("pattern"))
            ));
        }
        return inputs;
    }

    private List<CapabilityDefinition.OutputField> parseOutputs(List<Object> rawOutputs) {
        List<CapabilityDefinition.OutputField> outputs = new ArrayList<>();
        for (Object item : rawOutputs) {
            Map<String, Object> raw = asMap(item);
            outputs.add(new CapabilityDefinition.OutputField(
                    asString(raw.get("name")),
                    asString(raw.get("semanticType")),
                    asString(raw.get("type")),
                    asString(raw.get("evidenceRole"))
            ));
        }
        return outputs;
    }

    private CapabilityDefinition.Executor parseExecutor(Map<String, Object> raw) {
        return new CapabilityDefinition.Executor(
                asString(raw.get("type")),
                asString(raw.get("rfcName")),
                asStringMap(raw.get("inputMapping")),
                asStringMap(raw.get("outputMapping"))
        );
    }

    private CapabilityDefinition.ExecutorBinding parseExecutorBinding(Map<String, Object> raw, Map<String, Object> executor) {
        String type = asString(raw.get("type"));
        if (type == null) {
            type = asString(executor.get("type"));
        }
        return new CapabilityDefinition.ExecutorBinding(
                type,
                asString(raw.get("bindingId"))
        );
    }

    private CapabilityDefinition.Governance parseGovernance(Map<String, Object> raw) {
        return new CapabilityDefinition.Governance(
                asEnum(SideEffect.class, raw.get("sideEffect")),
                Boolean.TRUE.equals(raw.get("requiresApproval")),
                asString(raw.get("approvalPolicy")),
                asString(raw.get("dataClassification")),
                Boolean.TRUE.equals(raw.get("auditRequired"))
        );
    }

    private String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private int asInt(Object value) {
        return value instanceof Number number ? number.intValue() : 0;
    }

    private Integer asNullableInt(Object value) {
        return value instanceof Number number ? number.intValue() : null;
    }

    private <E extends Enum<E>> E asEnum(Class<E> enumType, Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Enum.valueOf(enumType, String.valueOf(value));
        } catch (IllegalArgumentException e) {
            throw new RegistryValidationException(enumType.getSimpleName() + " has invalid value: " + value);
        }
    }

    private List<Object> asList(Object value) {
        return value instanceof List<?> list ? new ArrayList<>(list) : List.of();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        if (!(value instanceof Map<?, ?> map)) {
            return Map.of();
        }
        Map<String, Object> result = new LinkedHashMap<>();
        map.forEach((key, mapValue) -> result.put(String.valueOf(key), mapValue));
        return result;
    }

    private Map<String, String> asStringMap(Object value) {
        Map<String, Object> raw = asMap(value);
        Map<String, String> result = new LinkedHashMap<>();
        raw.forEach((key, mapValue) -> result.put(key, asString(mapValue)));
        return result;
    }
}

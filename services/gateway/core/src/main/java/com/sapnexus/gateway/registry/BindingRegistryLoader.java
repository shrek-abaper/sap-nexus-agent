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

/**
 * Loads {@link BindingRegistry} from {@code executor-bindings.yaml} using snakeyaml,
 * mirroring {@link CapabilityRegistryLoader}.
 */
public class BindingRegistryLoader {

    public BindingRegistry load(Path path) {
        try (Reader reader = Files.newBufferedReader(path)) {
            Object loaded = new Yaml().load(reader);
            if (!(loaded instanceof Map<?, ?> root)) {
                throw new RegistryValidationException("executor-bindings root object is required");
            }
            int version = asInt(root.get("version"));
            List<BindingDefinition> bindings = asList(root.get("bindings")).stream()
                    .map(this::asMap)
                    .map(this::parseBinding)
                    .toList();
            return new BindingRegistry(version, bindings);
        } catch (IOException e) {
            throw new RegistryValidationException("Unable to read executor bindings: " + path);
        }
    }

    @SuppressWarnings("unchecked")
    private BindingDefinition parseBinding(Map<String, Object> raw) {
        return new BindingDefinition(
                asString(raw.get("bindingId")),
                asString(raw.get("type")),
                asString(raw.get("serviceRef")),
                asString(raw.get("entitySet")),
                asString(raw.get("method")),
                asStringMap(raw.get("filterMapping")),
                asNullableInt(raw.get("topLimit")),
                asStringList(raw.get("selectFields")),
                asObjectMap(raw.get("constraints"))
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

    private Map<String, Object> asObjectMap(Object value) {
        return asMap(value);
    }

    private List<String> asStringList(Object value) {
        List<Object> raw = asList(value);
        List<String> result = new ArrayList<>();
        for (Object item : raw) {
            result.add(asString(item));
        }
        return result;
    }
}

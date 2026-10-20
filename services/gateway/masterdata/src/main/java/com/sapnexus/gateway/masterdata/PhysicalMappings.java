package com.sapnexus.gateway.masterdata;

import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

/**
 * Loads the trusted server-side physical mapping
 * ({@code master-data/physical-mappings.yaml}). Binds each registry
 * {@code queryTemplateId} to its object type, the whitelisted logical
 * columns, and the organizational filter field. Query text itself is fixed
 * in {@link MasterdataQueries}; this file never contributes SQL fragments.
 */
public record PhysicalMappings(Map<String, Template> templates) {

    public record Template(
            String objectType,
            String identifierField,
            Map<String, String> columns,
            String orgFilterField
    ) {
    }

    public static PhysicalMappings load(Path path) {
        try (Reader reader = Files.newBufferedReader(path)) {
            Object loaded = new Yaml().load(reader);
            if (!(loaded instanceof Map<?, ?> root)) {
                throw new IllegalStateException("physical-mappings root object is required");
            }
            Object rawTemplates = root.get("queryTemplates");
            if (!(rawTemplates instanceof Map<?, ?> map)) {
                throw new IllegalStateException("physical-mappings queryTemplates are required");
            }
            Map<String, Template> templates = new java.util.LinkedHashMap<>();
            map.forEach((key, value) -> {
                if (!(value instanceof Map<?, ?> raw)) {
                    throw new IllegalStateException("invalid template: " + key);
                }
                templates.put(String.valueOf(key), new Template(
                        stringOf(raw.get("objectType")),
                        stringOf(raw.get("identifierField")),
                        stringMapOf(raw.get("columns")),
                        stringOf(raw.get("orgFilterField"))
                ));
            });
            return new PhysicalMappings(templates);
        } catch (IOException e) {
            throw new IllegalStateException("Unable to read physical mappings: " + path, e);
        }
    }

    public Template require(String queryTemplateId) {
        Template template = templates.get(queryTemplateId);
        if (template == null) {
            throw new IllegalArgumentException("unknown query template: " + queryTemplateId);
        }
        return template;
    }

    private static String stringOf(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static Map<String, String> stringMapOf(Object value) {
        if (!(value instanceof Map<?, ?> map)) {
            return Map.of();
        }
        Map<String, String> result = new java.util.LinkedHashMap<>();
        map.forEach((key, mapValue) -> result.put(String.valueOf(key), String.valueOf(mapValue)));
        return result;
    }
}

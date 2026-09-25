package com.sapnexus.gateway.rest;

import com.sapnexus.gateway.execution.TechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

import java.math.BigDecimal;
import java.net.URI;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Executes READ capabilities through the pure-ABAP rest2rfc SICF gateway using
 * plain outbound HTTP/JSON. The request body and response extraction are driven
 * entirely by the capability executor inputMapping/outputMapping; connection
 * values and credentials are resolved from {@link Rest2RfcProperties} and the
 * environment, never from the registry.
 */
@Component("REST_JSON")
public class RestJsonTechnicalAdapter implements TechnicalAdapter {

    private static final String DEFAULT_PATH = "/sap/bc/rest2rfc";

    private final CapabilityRegistry registry;
    private final BindingRegistry bindingRegistry;
    private final Rest2RfcProperties properties;
    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    public RestJsonTechnicalAdapter(CapabilityRegistry registry,
                                    BindingRegistry bindingRegistry,
                                    Rest2RfcProperties properties,
                                    RestClient.Builder restClientBuilder) {
        this.registry = registry;
        this.bindingRegistry = bindingRegistry;
        this.properties = properties;
        this.restClient = restClientBuilder.build();
        this.objectMapper = new ObjectMapper()
                .configure(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS, true);
    }

    @Override
    public TechnicalExecutionResult execute(TechnicalExecutionRequest request) {
        long start = System.currentTimeMillis();
        String traceId = request.traceId();

        CapabilityDefinition capability = registry.findEnabled(request.capabilityId())
                .orElseThrow(() -> new IllegalStateException(
                        "Capability not found or disabled: " + request.capabilityId()));

        BindingDefinition binding = bindingRegistry.find(request.bindingId())
                .orElseThrow(() -> new IllegalStateException(
                        "Binding not found: " + request.bindingId()));

        TargetEndpoint endpoint = resolveEndpoint(binding);
        if (endpoint.baseUrl() == null) {
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.SAP_COMMUNICATION_ERROR,
                    "REST_JSON endpoint base URL is not configured", 0);
        }
        if (endpoint.user() == null || endpoint.password() == null) {
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.SAP_AUTH_ERROR,
                    "REST_JSON endpoint credentials are not configured", 0);
        }

        Map<String, Object> body = buildBody(capability, request.parameters());
        URI uri = buildUri(endpoint, capability.executor().rfcName());

        Map<String, Object> response;
        try {
            String requestBody = objectMapper.writeValueAsString(body);
            String responseBody = restClient.post()
                    .uri(uri)
                    .headers(headers -> headers.setBasicAuth(endpoint.user(), endpoint.password()))
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .body(requestBody)
                    .retrieve()
                    .body(String.class);
            response = parseJson(responseBody);
        } catch (RestClientResponseException e) {
            long duration = System.currentTimeMillis() - start;
            // The gateway returns an empty body for non-200 responses; the error
            // text is only available in the status line reason phrase.
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), classifyStatus(e.getStatusCode()),
                    "REST_JSON call failed: " + e.getStatusCode().value()
                            + " " + safeReason(e.getStatusText()),
                    duration);
        } catch (ResourceAccessException e) {
            long duration = System.currentTimeMillis() - start;
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.SAP_COMMUNICATION_ERROR,
                    "REST_JSON endpoint unreachable: " + e.getMessage(), duration);
        } catch (JsonProcessingException e) {
            long duration = System.currentTimeMillis() - start;
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.NORMALIZATION_ERROR,
                    "Unable to serialize REST_JSON request body", duration);
        }

        long duration = System.currentTimeMillis() - start;

        if (response == null) {
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.NORMALIZATION_ERROR,
                    "Empty or invalid JSON response from REST_JSON endpoint", duration);
        }

        SapReturnMessage businessError = findBusinessError(response.get("return"));
        if (businessError != null) {
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.SAP_BUSINESS_ERROR,
                    "REST_JSON business error: " + businessError.message(), duration);
        }

        Map<String, Object> data = extractData(capability, response);
        List<SapReturnMessage> messages = mapMessages(response.get("return"));
        Map<String, Object> adapterMetadata = new LinkedHashMap<>();
        adapterMetadata.put("rfcName", capability.executor().rfcName());
        adapterMetadata.put("systemRef", binding.systemRef());
        adapterMetadata.put("durationMs", duration);

        return TechnicalExecutionResult.success(
                traceId, request.capabilityId(), request.bindingId(),
                request.executorType(), messages, data, duration, adapterMetadata);
    }

    private TargetEndpoint resolveEndpoint(BindingDefinition binding) {
        Rest2RfcProperties.Endpoint configured = binding.systemRef() == null
                ? null : properties.getSystems().get(binding.systemRef());
        String configuredBaseUrl = configured == null ? null : configured.getBaseUrl();
        String configuredClient = configured == null ? null : configured.getClient();
        String configuredUser = configured == null ? null : configured.getUser();
        String configuredPassword = configured == null ? null : configured.getPassword();
        String configuredPath = configured == null ? null : configured.getPath();

        String baseUrl = firstNonBlank(configuredBaseUrl,
                System.getenv("SAP_REST2RFC_BASE_URL"), sharedHttpBaseUrl());
        String client = firstNonBlank(configuredClient,
                System.getenv("SAP_REST2RFC_CLIENT"), System.getenv("SAP_CLIENT"));
        String user = firstNonBlank(configuredUser,
                System.getenv("SAP_REST2RFC_USER"), System.getenv("SAP_USER"));
        String password = firstNonBlank(configuredPassword,
                System.getenv("SAP_REST2RFC_PASSWORD"), System.getenv("SAP_PASSWORD"));
        String path = firstNonBlank(binding.pathTemplate(), configuredPath, DEFAULT_PATH);
        return new TargetEndpoint(baseUrl, path, client, user, password);
    }

    private URI buildUri(TargetEndpoint endpoint, String rfcName) {
        UriComponentsBuilder builder = UriComponentsBuilder
                .fromHttpUrl(endpoint.baseUrl())
                .path(endpoint.path())
                .queryParam("RFC", rfcName);
        if (endpoint.client() != null) {
            builder.queryParam("sap-client", endpoint.client());
        }
        return builder.build().encode().toUri();
    }

    private Map<String, Object> buildBody(CapabilityDefinition capability,
                                          Map<String, Object> parameters) {
        Map<String, Object> body = new LinkedHashMap<>();
        Map<String, String> inputMapping = capability.executor().inputMapping();
        inputMapping.forEach((logicalName, sapName) -> {
            Object value = parameters.get(logicalName);
            if (value != null) {
                // Comma-separated SAP names share one value (same convention as
                // the JCo executor, e.g. MATERIAL_LONG,MATERIAL).
                for (String targetName : sapName.split(",")) {
                    body.put(targetName.trim(), String.valueOf(value));
                }
            }
        });
        return body;
    }

    private Map<String, Object> extractData(CapabilityDefinition capability,
                                            Map<String, Object> response) {
        Map<String, Object> data = new LinkedHashMap<>();
        capability.executor().outputMapping().forEach((logicalName, sapName) -> {
            Object value = response.get(sapName.toLowerCase());
            data.put(logicalName, normalize(value));
        });
        return data;
    }

    /**
     * Converts the envelope-free rest2rfc response into the same shape the JCo
     * path produces: row/field names as camelCase, all elementary values as text.
     */
    private Object normalize(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            map.forEach((key, nested) ->
                    result.put(toCamelCase(String.valueOf(key)), normalize(nested)));
            return result;
        }
        if (value instanceof List<?> list) {
            List<Object> result = new ArrayList<>();
            for (Object item : list) {
                result.add(normalize(item));
            }
            return result;
        }
        if (value instanceof BigDecimal decimal) {
            return decimal.toPlainString();
        }
        return value == null ? "" : String.valueOf(value);
    }

    private SapReturnMessage findBusinessError(Object rawReturn) {
        if (!(rawReturn instanceof List<?> list)) {
            return null;
        }
        for (Object item : list) {
            if (item instanceof Map<?, ?> map) {
                String type = String.valueOf(map.get("type"));
                if (type.length() == 1 && "EAX".contains(type)) {
                    return new SapReturnMessage(
                            type,
                            String.valueOf(map.get("id")),
                            String.valueOf(map.get("number")),
                            String.valueOf(map.get("message")),
                            String.valueOf(map.get("field"))
                    );
                }
            }
        }
        return null;
    }

    private List<SapReturnMessage> mapMessages(Object rawReturn) {
        if (!(rawReturn instanceof List<?> list)) {
            return List.of();
        }
        List<SapReturnMessage> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof Map<?, ?> map) {
                result.add(new SapReturnMessage(
                        String.valueOf(map.get("type")),
                        String.valueOf(map.get("id")),
                        String.valueOf(map.get("number")),
                        String.valueOf(map.get("message")),
                        String.valueOf(map.get("field"))
                ));
            }
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseJson(String body) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(body, Map.class);
        } catch (Exception e) {
            return null;
        }
    }

    private ErrorType classifyStatus(HttpStatusCode status) {
        int code = status.value();
        if (code == 400) {
            return ErrorType.INVALID_PARAMETER;
        }
        if (code == 401 || code == 403) {
            return ErrorType.SAP_AUTH_ERROR;
        }
        if (code == 404 || code == 405) {
            return ErrorType.SAP_COMMUNICATION_ERROR;
        }
        if (code == 422 || status.is5xxServerError()) {
            return ErrorType.SAP_BUSINESS_ERROR;
        }
        return ErrorType.NORMALIZATION_ERROR;
    }

    private static String toCamelCase(String sapName) {
        StringBuilder builder = new StringBuilder(sapName.length());
        boolean upperNext = false;
        for (int i = 0; i < sapName.length(); i++) {
            char c = sapName.charAt(i);
            if (c == '_') {
                upperNext = true;
            } else if (upperNext) {
                builder.append(Character.toUpperCase(c));
                upperNext = false;
            } else {
                builder.append(c);
            }
        }
        return builder.toString();
    }

    /**
     * Derives the SICF base URL from the shared SAP destination when no
     * rest2rfc-specific URL is configured: the ICM HTTP port is shared by
     * OData and SICF on the same application server.
     */
    private static String sharedHttpBaseUrl() {
        String host = System.getenv("SAP_ASHOST");
        String port = System.getenv("SAP_HTTP_PORT");
        if (host == null || host.isBlank() || port == null || port.isBlank()) {
            return null;
        }
        return "http://" + host + ":" + port;
    }

    private static String firstNonBlank(String... candidates) {
        for (String candidate : candidates) {
            if (candidate != null && !candidate.isBlank()) {
                return candidate;
            }
        }
        return null;
    }

    private static String safeReason(String reasonPhrase) {
        return reasonPhrase == null || reasonPhrase.isBlank()
                ? "no reason phrase" : reasonPhrase;
    }

    private record TargetEndpoint(String baseUrl, String path, String client,
                                  String user, String password) {
    }
}

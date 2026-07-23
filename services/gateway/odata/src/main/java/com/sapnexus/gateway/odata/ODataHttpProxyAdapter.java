package com.sapnexus.gateway.odata;

import com.sapnexus.gateway.execution.TechnicalAdapter;
import com.sapnexus.gateway.execution.TechnicalExecutionRequest;
import com.sapnexus.gateway.execution.TechnicalExecutionResult;
import com.sapnexus.gateway.registry.BindingDefinition;
import com.sapnexus.gateway.registry.BindingRegistry;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Thin reverse-proxy adapter that forwards ODATA execution to the Python
 * OData service (:8081) and normalises the JSON response into a
 * {@link TechnicalExecutionResult}.
 *
 * <p>Registered as Spring bean {@code "ODATA"} so the dispatcher can route
 * by executor type. Does NOT assemble {@code $filter} or contact SAP directly.
 *
 * <p>Constructs {@link TechnicalExecutionResult} directly via {@code success}/{@code failure}
 * factories -- does NOT use {@code fromExecutionResult} (R-2 NPE guard: that method
 * calls {@code Map.of("rfcName", ...)} which NPEs when rfcName is null for OData).
 */
@Component("ODATA")
public class ODataHttpProxyAdapter implements TechnicalAdapter {

    private static final List<String> KNOWN_RESPONSE_KEYS = List.of(
            "success", "purchaseOrders", "totalCount", "messages", "errorType", "traceId"
    );

    private final CapabilityRegistry registry;
    private final BindingRegistry bindingRegistry;
    private final ODataProxyProperties properties;
    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    public ODataHttpProxyAdapter(CapabilityRegistry registry,
                                 BindingRegistry bindingRegistry,
                                 ODataProxyProperties properties,
                                 RestClient.Builder restClientBuilder) {
        this.registry = registry;
        this.bindingRegistry = bindingRegistry;
        this.properties = properties;
        this.restClient = restClientBuilder.build();
        this.objectMapper = new ObjectMapper();
    }

    @Override
    public TechnicalExecutionResult execute(TechnicalExecutionRequest request) {
        long start = System.currentTimeMillis();
        String traceId = request.traceId();

        registry.findEnabled(request.capabilityId())
                .orElseThrow(() -> new IllegalStateException(
                        "Capability not found or disabled: " + request.capabilityId()));

        BindingDefinition binding = bindingRegistry.find(request.bindingId())
                .orElseThrow(() -> new IllegalStateException(
                        "Binding not found: " + request.bindingId()));

        Map<String, Object> payload = buildPayload(request, binding);

        Map<String, Object> response;
        try {
            String requestBody = objectMapper.writeValueAsString(payload);
            String body = restClient.post()
                    .uri(properties.getProxyUrl() + "/execute")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(requestBody)
                    .retrieve()
                    .body(String.class);
            response = parseJson(body);
        } catch (RestClientResponseException e) {
            response = parseJson(e.getResponseBodyAsString());
        } catch (ResourceAccessException e) {
            long duration = System.currentTimeMillis() - start;
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.SAP_COMMUNICATION_ERROR,
                    "OData proxy unreachable: " + e.getMessage(), duration);
        } catch (JsonProcessingException e) {
            long duration = System.currentTimeMillis() - start;
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.NORMALIZATION_ERROR,
                    "Unable to serialize OData proxy request", duration);
        }

        long duration = System.currentTimeMillis() - start;

        if (response == null) {
            return TechnicalExecutionResult.failure(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(), ErrorType.NORMALIZATION_ERROR,
                    "Empty or invalid JSON response from OData proxy", duration);
        }

        return buildResult(request, response, duration);
    }

    private TechnicalExecutionResult buildResult(TechnicalExecutionRequest request,
                                                  Map<String, Object> response,
                                                  long duration) {
        String traceId = request.traceId();
        boolean success = Boolean.TRUE.equals(response.get("success"));

        if (success) {
            Map<String, Object> data = new HashMap<>();
            Object purchaseOrders = response.get("purchaseOrders");
            data.put("purchaseOrders", purchaseOrders != null ? purchaseOrders : List.of());
            Object totalCount = response.get("totalCount");
            data.put("totalCount", totalCount != null ? totalCount : 0);

            Map<String, Object> adapterMetadata = buildAdapterMetadata(response, duration);

            return TechnicalExecutionResult.success(
                    traceId, request.capabilityId(), request.bindingId(),
                    request.executorType(),
                    mapMessages(response.get("messages")),
                    data, duration, adapterMetadata);
        }

        String errorTypeStr = stringOrEmpty(response.get("errorType"));
        String message = extractFirstMessage(response.get("messages"));
        return TechnicalExecutionResult.failure(
                traceId, request.capabilityId(), request.bindingId(),
                request.executorType(), mapErrorType(errorTypeStr), message, duration);
    }

    private Map<String, Object> buildPayload(TechnicalExecutionRequest request,
                                              BindingDefinition binding) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("serviceRef", binding.serviceRef());
        payload.put("entitySet", binding.entitySet());
        payload.put("filterMapping", binding.filterMapping());
        payload.put("parameters", request.parameters());
        payload.put("topLimit", binding.topLimit());
        payload.put("selectFields", binding.selectFields());
        payload.put("traceId", request.traceId());
        return payload;
    }

    private Map<String, Object> buildAdapterMetadata(Map<String, Object> response, long duration) {
        Map<String, Object> metadata = new HashMap<>();
        metadata.put("totalCount", response.get("totalCount"));
        metadata.put("durationMs", duration);
        // Defensively pass through any unknown response fields (e.g. destination/token)
        // so TechnicalRedactor can redact them.
        response.forEach((key, value) -> {
            if (!KNOWN_RESPONSE_KEYS.contains(key)) {
                metadata.put(key, value);
            }
        });
        return metadata;
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

    private ErrorType mapErrorType(String pythonErrorType) {
        if (pythonErrorType == null || pythonErrorType.isBlank()) {
            return ErrorType.NORMALIZATION_ERROR;
        }
        return switch (pythonErrorType) {
            case "CONNECTION_ERROR" -> ErrorType.SAP_COMMUNICATION_ERROR;
            case "BAD_REQUEST" -> ErrorType.INVALID_PARAMETER;
            case "ODATA_ERROR", "ODATA_HTTP_ERROR" -> ErrorType.SAP_BUSINESS_ERROR;
            case "INVALID_RESPONSE" -> ErrorType.NORMALIZATION_ERROR;
            default -> ErrorType.NORMALIZATION_ERROR;
        };
    }

    private List<SapReturnMessage> mapMessages(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<SapReturnMessage> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof Map<?, ?> map) {
                result.add(new SapReturnMessage(
                        stringOrEmpty(map.get("type")),
                        stringOrEmpty(map.get("id")),
                        stringOrEmpty(map.get("number")),
                        stringOrEmpty(map.get("message")),
                        stringOrEmpty(map.get("field"))
                ));
            }
        }
        return result;
    }

    private String extractFirstMessage(Object raw) {
        if (raw instanceof List<?> list && !list.isEmpty()) {
            Object first = list.get(0);
            if (first instanceof Map<?, ?> map) {
                String message = stringOrEmpty(map.get("message"));
                if (!message.isEmpty()) {
                    return message;
                }
            }
        }
        return "OData execution failed";
    }

    private static String stringOrEmpty(Object value) {
        return value == null ? "" : String.valueOf(value);
    }
}

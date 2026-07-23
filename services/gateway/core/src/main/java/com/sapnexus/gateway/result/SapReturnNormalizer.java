package com.sapnexus.gateway.result;

import java.util.List;

public class SapReturnNormalizer {
    public Result normalize(List<SapReturnMessage> messages) {
        List<SapReturnMessage> safeMessages = messages == null ? List.of() : messages;
        boolean hasBusinessError = safeMessages.stream()
                .map(SapReturnMessage::type)
                .anyMatch(type -> "E".equalsIgnoreCase(type) || "A".equalsIgnoreCase(type));
        return new Result(!hasBusinessError, hasBusinessError ? ErrorType.SAP_BUSINESS_ERROR : ErrorType.NONE, safeMessages);
    }

    public record Result(boolean success, ErrorType errorType, List<SapReturnMessage> messages) {
    }
}

package com.sapnexus.gateway.result;

public record SapReturnMessage(
        String type,
        String id,
        String number,
        String message,
        String field
) {
}

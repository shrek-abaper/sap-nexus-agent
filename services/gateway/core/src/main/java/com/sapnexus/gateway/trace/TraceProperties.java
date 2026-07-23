package com.sapnexus.gateway.trace;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "sapnexus.trace")
public class TraceProperties {
    private String path = "../runtime/gateway-jco/traces.jsonl";

    public String getPath() {
        return path;
    }

    public void setPath(String path) {
        this.path = path;
    }
}

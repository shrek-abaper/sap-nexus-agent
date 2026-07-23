package com.sapnexus.gateway.registry;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "sapnexus.registry")
public class RegistryProperties {
    private String path = "../registry/capabilities.yaml";
    private String bindingsPath = "../registry/executor-bindings.yaml";

    public String getPath() {
        return path;
    }

    public void setPath(String path) {
        this.path = path;
    }

    public String getBindingsPath() {
        return bindingsPath;
    }

    public void setBindingsPath(String bindingsPath) {
        this.bindingsPath = bindingsPath;
    }
}

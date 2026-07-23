package com.sapnexus.gateway.odata;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Configuration for the Python OData proxy service address.
 *
 * <p>Property: {@code sap.gateway.odata.proxy-url} (default {@code http://localhost:8081}).
 */
@ConfigurationProperties(prefix = "sap.gateway.odata")
public class ODataProxyProperties {

    private String proxyUrl = "http://localhost:8081";

    public String getProxyUrl() {
        return proxyUrl;
    }

    public void setProxyUrl(String proxyUrl) {
        this.proxyUrl = proxyUrl;
    }
}

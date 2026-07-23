package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoDestinationManager;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.ext.DestinationDataProvider;
import com.sap.conn.jco.ext.Environment;

import java.util.Map;
import java.util.Properties;

public class JcoDestinationFactory {
    static final String DESTINATION_NAME = "SAP_NEXUS_DEST";
    private static final InMemoryDestinationDataProvider PROVIDER = new InMemoryDestinationDataProvider();

    public JCoDestination getDestination() throws JCoException {
        configureNativeLibraryPath();
        registerProviderIfNeeded();
        PROVIDER.changeProperties(DESTINATION_NAME, propertiesFromEnvironment(System.getenv()));
        return JCoDestinationManager.getDestination(DESTINATION_NAME);
    }

    Properties propertiesFromEnvironment(Map<String, String> env) {
        JcoDestinationProperties readiness = JcoDestinationProperties.from(env);
        if (!readiness.sapEnvironmentPresent()) {
            throw new IllegalStateException("Missing SAP environment keys: " + readiness.missingRequiredKeys());
        }

        Properties properties = new Properties();
        properties.setProperty(DestinationDataProvider.JCO_ASHOST, env.get("SAP_ASHOST"));
        properties.setProperty(DestinationDataProvider.JCO_SYSNR, env.get("SAP_SYSNR"));
        properties.setProperty(DestinationDataProvider.JCO_CLIENT, env.get("SAP_CLIENT"));
        properties.setProperty(DestinationDataProvider.JCO_USER, env.get("SAP_USER"));
        properties.setProperty(DestinationDataProvider.JCO_PASSWD, env.get("SAP_PASSWORD"));
        properties.setProperty(DestinationDataProvider.JCO_LANG, env.getOrDefault("SAP_LANG", "EN"));
        copyOptional(env, properties, "SAP_SAPROUTER", DestinationDataProvider.JCO_SAPROUTER);
        properties.setProperty(DestinationDataProvider.JCO_POOL_CAPACITY, "5");
        properties.setProperty(DestinationDataProvider.JCO_PEAK_LIMIT, "10");
        return properties;
    }

    private void configureNativeLibraryPath() {
        String libPath = System.getenv("SAP_JCO_LIB_PATH");
        if (libPath != null && !libPath.isBlank()) {
            System.setProperty("java.library.path", libPath);
        }
    }

    private void registerProviderIfNeeded() {
        if (!Environment.isDestinationDataProviderRegistered()) {
            Environment.registerDestinationDataProvider(PROVIDER);
        }
    }

    private void copyOptional(Map<String, String> env, Properties properties, String envName, String jcoName) {
        String value = env.get(envName);
        if (value != null && !value.isBlank()) {
            properties.setProperty(jcoName, value);
        }
    }
}

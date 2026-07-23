package com.sapnexus.gateway.jco;

import com.sap.conn.jco.ext.DataProviderException;
import com.sap.conn.jco.ext.DestinationDataEventListener;
import com.sap.conn.jco.ext.DestinationDataProvider;

import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

class InMemoryDestinationDataProvider implements DestinationDataProvider {
    private final Map<String, Properties> destinations = new HashMap<>();
    private DestinationDataEventListener eventListener;

    @Override
    public Properties getDestinationProperties(String destinationName) {
        Properties properties = destinations.get(destinationName);
        if (properties != null && properties.isEmpty()) {
            throw new DataProviderException(
                    DataProviderException.Reason.INVALID_CONFIGURATION,
                    "destination configuration is incorrect",
                    null
            );
        }
        return properties;
    }

    @Override
    public void setDestinationDataEventListener(DestinationDataEventListener eventListener) {
        this.eventListener = eventListener;
    }

    @Override
    public boolean supportsEvents() {
        return true;
    }

    void changeProperties(String destinationName, Properties properties) {
        synchronized (destinations) {
            if (properties == null) {
                if (destinations.remove(destinationName) != null && eventListener != null) {
                    eventListener.deleted(destinationName);
                }
                return;
            }
            destinations.put(destinationName, properties);
            if (eventListener != null) {
                eventListener.updated(destinationName);
            }
        }
    }
}

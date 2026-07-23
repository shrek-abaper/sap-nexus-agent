package com.sapnexus.gateway.result;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SapReturnNormalizerTest {
    @Test
    void successAndWarningMessagesDoNotCreateBusinessError() {
        SapReturnNormalizer.Result result = new SapReturnNormalizer().normalize(List.of(
                new SapReturnMessage("S", "M3", "000", "OK", ""),
                new SapReturnMessage("W", "M3", "001", "Low stock", "MATERIAL")
        ));

        assertThat(result.success()).isTrue();
        assertThat(result.errorType()).isEqualTo(ErrorType.NONE);
    }

    @Test
    void errorOrAbortMessagesCreateSapBusinessError() {
        SapReturnNormalizer.Result result = new SapReturnNormalizer().normalize(List.of(
                new SapReturnMessage("E", "M3", "001", "Material not found", "MATERIAL")
        ));

        assertThat(result.success()).isFalse();
        assertThat(result.errorType()).isEqualTo(ErrorType.SAP_BUSINESS_ERROR);
        assertThat(result.messages()).extracting(SapReturnMessage::message).contains("Material not found");
    }
}

package com.sapnexus.gateway.approval;

import com.sapnexus.gateway.result.ErrorType;

public record ApprovalGuardResult(ErrorType errorType, boolean rejected) {
    public static ApprovalGuardResult rejected(ErrorType errorType) {
        return new ApprovalGuardResult(errorType, true);
    }

    public boolean passed() {
        return !rejected;
    }
}

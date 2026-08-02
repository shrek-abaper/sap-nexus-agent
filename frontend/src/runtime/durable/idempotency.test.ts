import { describe, expect, it } from "vitest";
import { idempotencyKey } from "./idempotency";

describe("idempotencyKey", () => {
  it("is stable for equal inputs regardless of key order", () => {
    const a = idempotencyKey("run-1", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    const b = idempotencyKey("run-1", "approval_approve", { approvalRecordId: "apr-1", decision: "approve" });
    expect(a).toBe(b);
  });

  it("differs by continuationType (different types not idempotent to each other)", () => {
    const approve = idempotencyKey("run-1", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    const reject = idempotencyKey("run-1", "approval_reject", { decision: "reject", approvalRecordId: "apr-1" });
    const batch = idempotencyKey("run-1", "batch_confirm", { combinations: [{ a: "1" }] });
    expect(new Set([approve, reject, batch]).size).toBe(3);
  });

  it("differs by runId", () => {
    const a = idempotencyKey("run-1", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    const b = idempotencyKey("run-2", "approval_approve", { decision: "approve", approvalRecordId: "apr-1" });
    expect(a).not.toBe(b);
  });

  it("format is runId:type:hash", () => {
    const key = idempotencyKey("run-1", "batch_confirm", { combinations: [] });
    expect(key.startsWith("run-1:batch_confirm:")).toBe(true);
  });
});

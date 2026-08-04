// frontend/src/runtime/plan-executor/node-state-machine.test.ts
import { describe, expect, it } from "vitest";
import { NodeState } from "./types";
import { isLegalTransition, assertTransition, IllegalTransitionError } from "./node-state-machine";

describe("node state machine", () => {
  describe("legal transitions", () => {
    it("BLOCKED_DEPENDENCY -> READY", () => {
      expect(isLegalTransition(NodeState.BLOCKED_DEPENDENCY, NodeState.READY)).toBe(true);
    });
    it("READY -> VALIDATING", () => {
      expect(isLegalTransition(NodeState.READY, NodeState.VALIDATING)).toBe(true);
    });
    it("VALIDATING -> EXECUTING", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.EXECUTING)).toBe(true);
    });
    it("VALIDATING -> FAILED", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.FAILED)).toBe(true);
    });
    it("EXECUTING -> SUCCEEDED", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.SUCCEEDED)).toBe(true);
    });
    it("EXECUTING -> FAILED", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.FAILED)).toBe(true);
    });
    it("EXECUTING -> TIMED_OUT", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.TIMED_OUT)).toBe(true);
    });
    it("READY -> CANCELLED", () => {
      expect(isLegalTransition(NodeState.READY, NodeState.CANCELLED)).toBe(true);
    });
    it("VALIDATING -> CANCELLED", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.CANCELLED)).toBe(true);
    });
    it("VALIDATING -> TIMED_OUT (validate timeout, spec: timed-out node SHALL transition to TIMED_OUT)", () => {
      expect(isLegalTransition(NodeState.VALIDATING, NodeState.TIMED_OUT)).toBe(true);
    });
    it("EXECUTING -> CANCELLED", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.CANCELLED)).toBe(true);
    });
    it("FAILED -> READY (explicit retry, new attempt)", () => {
      expect(isLegalTransition(NodeState.FAILED, NodeState.READY)).toBe(true);
    });
    it("initial -> BLOCKED_DEPENDENCY", () => {
      expect(isLegalTransition(null, NodeState.BLOCKED_DEPENDENCY)).toBe(true);
    });
    it("initial -> READY", () => {
      expect(isLegalTransition(null, NodeState.READY)).toBe(true);
    });
    it("initial -> BLOCKED_APPROVAL", () => {
      expect(isLegalTransition(null, NodeState.BLOCKED_APPROVAL)).toBe(true);
    });
    it("initial -> CANCELLED (never-started node cancelled, spec: uncompleted nodes SHALL transition to CANCELLED)", () => {
      expect(isLegalTransition(null, NodeState.CANCELLED)).toBe(true);
    });
  });

  describe("illegal transitions (fail-closed)", () => {
    it("SUCCEEDED -> EXECUTING is illegal", () => {
      expect(isLegalTransition(NodeState.SUCCEEDED, NodeState.EXECUTING)).toBe(false);
    });
    it("SUCCEEDED -> READY is illegal", () => {
      expect(isLegalTransition(NodeState.SUCCEEDED, NodeState.READY)).toBe(false);
    });
    it("CANCELLED -> READY is illegal", () => {
      expect(isLegalTransition(NodeState.CANCELLED, NodeState.READY)).toBe(false);
    });
    it("TIMED_OUT -> EXECUTING is illegal", () => {
      expect(isLegalTransition(NodeState.TIMED_OUT, NodeState.EXECUTING)).toBe(false);
    });
    it("EXECUTING -> READY is illegal (no rewind)", () => {
      expect(isLegalTransition(NodeState.EXECUTING, NodeState.READY)).toBe(false);
    });
    it("READY -> SUCCEEDED is illegal (must validate+execute first)", () => {
      expect(isLegalTransition(NodeState.READY, NodeState.SUCCEEDED)).toBe(false);
    });
  });

  describe("assertTransition", () => {
    it("does not throw for legal transition", () => {
      expect(() => assertTransition(NodeState.READY, NodeState.VALIDATING)).not.toThrow();
    });
    it("throws IllegalTransitionError for illegal transition", () => {
      expect(() => assertTransition(NodeState.SUCCEEDED, NodeState.EXECUTING)).toThrow(IllegalTransitionError);
    });
    it("IllegalTransitionError carries from/to states", () => {
      try {
        assertTransition(NodeState.SUCCEEDED, NodeState.EXECUTING);
      } catch (e) {
        expect(e).toBeInstanceOf(IllegalTransitionError);
        const err = e as IllegalTransitionError;
        expect(err.fromState).toBe(NodeState.SUCCEEDED);
        expect(err.toState).toBe(NodeState.EXECUTING);
      }
    });
    // Safety-critical lockdown: Action nodes blocked on approval must never execute.
    it("BLOCKED_APPROVAL -> EXECUTING throws IllegalTransitionError (action nodes must never execute)", () => {
      expect(() => assertTransition(NodeState.BLOCKED_APPROVAL, NodeState.EXECUTING)).toThrow(IllegalTransitionError);
    });
    it("BLOCKED_APPROVAL -> CANCELLED does not throw (only legal exit from approval block)", () => {
      expect(() => assertTransition(NodeState.BLOCKED_APPROVAL, NodeState.CANCELLED)).not.toThrow();
    });
    it("TIMED_OUT -> READY does not throw (retry from timeout, parallel to FAILED -> READY)", () => {
      expect(() => assertTransition(NodeState.TIMED_OUT, NodeState.READY)).not.toThrow();
    });
  });
});

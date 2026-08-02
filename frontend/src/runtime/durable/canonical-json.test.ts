import { describe, expect, it } from "vitest";
import { canonicalJson, sha256Hex } from "./canonical-json";

describe("canonicalJson", () => {
  it("serializes objects with sorted keys and no whitespace", () => {
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
  });

  it("is order-independent for equal objects", () => {
    expect(canonicalJson({ a: 1, b: 2 })).toBe(canonicalJson({ b: 2, a: 1 }));
  });

  it("handles nested objects and arrays", () => {
    expect(canonicalJson({ z: [3, 1, 2], a: { y: 1, x: 2 } }))
      .toBe('{"a":{"x":2,"y":1},"z":[3,1,2]}');
  });

  it("handles null, booleans, numbers, strings", () => {
    expect(canonicalJson(null)).toBe("null");
    expect(canonicalJson(true)).toBe("true");
    expect(canonicalJson(42)).toBe("42");
    expect(canonicalJson("hi")).toBe('"hi"');
  });

  it("coerces non-finite numbers to null", () => {
    expect(canonicalJson(Number.POSITIVE_INFINITY)).toBe("null");
  });

  it("coerces undefined to null", () => {
    expect(canonicalJson(undefined)).toBe("null");
  });
});

describe("sha256Hex", () => {
  it("produces a stable 64-char hex digest", () => {
    const digest = sha256Hex('{"a":2,"b":1}');
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
    expect(sha256Hex('{"a":2,"b":1}')).toBe(digest);
  });
});

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { WorkbenchOutcome } from "./types";

describe("idempotent execution store", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "idem-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("lookupExecuted returns null when not recorded", async () => {
    const store = new JsonlRunStore(dir);
    expect(await store.lookupExecuted("run-1:approval_approve:abc")).toBeNull();
  });

  it("markExecuted records and lookupExecuted returns the result (cross-restart)", async () => {
    const store = new JsonlRunStore(dir);
    const result: WorkbenchOutcome = { status: "success", responseText: "done" };
    await store.markExecuted("run-1:approval_approve:abc", result);
    expect(await store.lookupExecuted("run-1:approval_approve:abc")).toEqual(result);
    const reopened = new JsonlRunStore(dir);
    expect(await reopened.lookupExecuted("run-1:approval_approve:abc")).toEqual(result);
  });
});

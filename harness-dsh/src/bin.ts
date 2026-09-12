#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  boot,
  installFailLoud,
  loadEnv,
  loadOptionalPatches,
  loadOverlayPatches,
  renderConfigDump,
} from "@deepseek-ai/dsh-app-boot";
import { runTurn } from "./runner.js";

const BIN_NAME = "sap-nexus-dsh";

const here = path.dirname(fileURLToPath(import.meta.url));
// src/bin.ts -> ../config ; lib/bin.js -> ../config
const configDir = path.resolve(here, "..", "config");
const rootConfig = path.join(configDir, "cordis.yml");
const bundlePatchFile = path.join(configDir, "cordis.bundle.patch.yml");
const devPatchFile = path.join(configDir, "cordis.patch.yml");

async function main(): Promise<void> {
  installFailLoud(BIN_NAME);
  loadEnv(BIN_NAME);

  const argv = process.argv.slice(2);
  const dumpConfig = argv.includes("--dump-config");
  const task = argv.filter((arg) => !arg.startsWith("--")).join(" ").trim();

  const bundlePatches = loadOverlayPatches(BIN_NAME, bundlePatchFile);
  const devPatches = loadOptionalPatches(BIN_NAME, devPatchFile) ?? [];

  if (dumpConfig) {
    process.stdout.write(renderConfigDump(BIN_NAME, rootConfig, [
      { label: bundlePatchFile, patches: bundlePatches },
      { label: devPatchFile, patches: devPatches },
    ]));
    return;
  }

  if (!task) {
    process.stderr.write(
      `usage: ${BIN_NAME} [--dump-config] "<business question in natural language>"\n`,
    );
    process.exitCode = 2;
    return;
  }

  const ctx = await boot(BIN_NAME, rootConfig, [...bundlePatches, ...devPatches]);
  try {
    const selection = ctx.get("agentDefaultModel")?.currentSelection();
    if (!selection) {
      throw new Error("agent default model is not configured");
    }
    const result = await runTurn(ctx, {
      task,
      provider: selection.provider,
      model: selection.model,
    });
    if (result.output) process.stdout.write(`${result.output}\n`);
    result.dispose();
    if (result.reason?.kind === "error") {
      const error = result.reason.error;
      process.stderr.write(`${BIN_NAME}: turn failed: ${error?.code ?? "ERROR"}: ${error?.message ?? ""}\n`);
      process.exitCode = 1;
    } else if (result.reason && result.reason.kind !== "completed" && !result.output) {
      process.exitCode = 1;
    }
  } finally {
    await ctx.fiber.dispose();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${BIN_NAME}: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});

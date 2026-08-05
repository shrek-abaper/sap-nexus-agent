import { runReleaseGateCli } from "./cli-runner";

async function main(): Promise<void> {
  try {
    const result = await runReleaseGateCli();
    process.exitCode = result.exitCode;
  } catch (error) {
    process.stderr.write(`Release gate failed: ${error instanceof Error ? error.message : "unknown error"}\n`);
    process.exitCode = 2;
  }
}

void main();

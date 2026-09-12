import { defineConfig } from "vitest/config";

// server-only throws outside a real RSC render; in unit tests alias it to a
// no-op (the boundary is still enforced at build time and asserted by tests).
export default defineConfig({
  resolve: {
    alias: {
      "server-only": new URL("./src/test/server-only-stub.ts", import.meta.url).pathname,
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});

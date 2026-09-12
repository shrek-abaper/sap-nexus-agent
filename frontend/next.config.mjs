/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  // Hide the floating Next.js dev-tools ("N") button in development.
  devIndicators: false,
  // The in-process dsh runtime (Cordis/dsh-* ESM packages) must stay external
  // to the server bundle; it is imported dynamically only in server code.
  serverExternalPackages: [
    "@deepseek-ai/cordis",
    "@deepseek-ai/cordis-plugin-timer",
    "@deepseek-ai/dsh-agent",
    "@deepseek-ai/dsh-agent-default-model",
    "@deepseek-ai/dsh-agent-loop",
    "@deepseek-ai/dsh-invariants",
    "@deepseek-ai/dsh-jobs-local",
    "@deepseek-ai/dsh-llm",
    "@deepseek-ai/dsh-llm-pi-ai",
    "@deepseek-ai/dsh-llm-retry",
    "@deepseek-ai/dsh-scope",
    "@deepseek-ai/dsh-session",
    "@deepseek-ai/dsh-session-projection",
    "@deepseek-ai/dsh-system-prompt",
    "@deepseek-ai/dsh-tools",
  ],
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // CLAUDE.md is the project's agent guidance, so next dev shouldn't add its own.
  agentRules: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

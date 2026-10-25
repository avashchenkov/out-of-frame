import type { NextConfig } from "next";

const config: NextConfig = {
  // The Docker image runs the self-contained server from .next/standalone.
  output: "standalone",
  poweredByHeader: false,
};

export default config;

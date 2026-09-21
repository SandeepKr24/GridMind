/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Stop `next dev` from writing AGENTS.md / CLAUDE.md into the project.
  agentRules: false,
};

export default nextConfig;

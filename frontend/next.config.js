/** @type {import("next").NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["*.vercel.run"],
  turbopack: {
    root: __dirname,
  },
};

module.exports = nextConfig;

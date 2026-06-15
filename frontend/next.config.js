/** @type {import("next").NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["*.vercel.run"],
  turbopack: {
    allowedDevOrigins: ["*.vercel.run"],
    root: __dirname,
  },
};

module.exports = nextConfig;

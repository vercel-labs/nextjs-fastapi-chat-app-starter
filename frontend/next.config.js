/** @type {import("next").NextConfig} */
const nextConfig = {
  turbopack: {
    allowedDevOrigins: ["*.vercel.run"],
    root: __dirname,
  },
};

module.exports = nextConfig;

/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const nextConfig = {
  async rewrites(){
    // In production, backend should be deployed separately (Railway/Render)
    // For Vercel-only deploy, these rewrites will 404 gracefully and frontend falls back to local logic
    if (process.env.VERCEL && !process.env.BACKEND_URL) return []
    return [
      { source: "/api/backtest", destination: `${BACKEND}/api/backtest` },
      { source: "/api/chart", destination: `${BACKEND}/api/chart` },
      { source: "/api/health", destination: `${BACKEND}/api/health` },
      { source: "/api/bot/:path*", destination: `${BACKEND}/api/bot/:path*` },
      { source: "/api/trades", destination: `${BACKEND}/api/trades` },
    ]
  },
  // Don't fail build if backend env missing
  env: {
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL || "https://bot-saros.vercel.app",
  }
}
module.exports = nextConfig

/** @type {import('next').NextConfig} */
// Security headers for every page. frame-ancestors/X-Frame-Options stop clickjacking
// (e.g. tricking an admin into clicking the LIVE toggle on /settings/keys inside a hidden iframe).
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://checkout.stripe.com; object-src 'none'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
]

const nextConfig = {
  // The frontend calls the backend directly (NEXT_PUBLIC_API_URL), so no rewrites/proxy here —
  // they were unused and Next 14 has open advisories for rewrites (SSRF / request smuggling).
  async headers(){
    return [{ source: "/:path*", headers: securityHeaders }]
  },
  // next/image isn't used; disabling the optimizer removes its advisories (DoS / AVIF RCE) from the attack surface
  images: { unoptimized: true },
  poweredByHeader: false,
  env: {
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL || "https://bot-saros.vercel.app",
  }
}
module.exports = nextConfig

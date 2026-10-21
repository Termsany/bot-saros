// Single source for the product name — change it here, not in pages.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://bot-saros.vercel.app"

export const BRAND = {
  name: "Raqm",
  nameAr: "رقم",
  nameCaps: "RAQM",
  subtitle: "AI CRYPTO TRADING",
  taglineAr: "بوت تداول العملات الرقمية بالذكاء الاصطناعي",
  // shown in footers; follows the real site URL so it updates when the domain changes
  domain: SITE_URL.replace(/^https?:\/\//, "").replace(/\/$/, ""),
  footer: "Raqm · رقم © 2026 — 4 بوتات مختبرة + متابعة مباشرة + Backtest",
  operational: "ENGINE ● OPERATIONAL",
} as const

export const stripePublishableKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY || ""

export const TIER_TO_PRICE_ENV: Record<string,string> = {
  starter: "STRIPE_STARTER_PRICE_ID",
  pro: "STRIPE_PRO_PRICE_ID",
  elite: "STRIPE_ELITE_PRICE_ID",
}

export const TIERS_ORDER = ["free","starter","pro","elite"] as const
export type TierId = typeof TIERS_ORDER[number]

export function canAccess(tier: TierId, required: TierId){
  return TIERS_ORDER.indexOf(tier) >= TIERS_ORDER.indexOf(required)
}

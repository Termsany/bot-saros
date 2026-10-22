import crypto from "crypto"

export const NOWPAYMENTS_TIERS: Record<string, number> = {
  starter: Number(process.env.CRYPTO_STARTER_USDT || process.env.NOWPAYMENTS_STARTER_USDT || 29),
  pro: Number(process.env.CRYPTO_PRO_USDT || process.env.NOWPAYMENTS_PRO_USDT || 59),
  elite: Number(process.env.CRYPTO_ELITE_USDT || process.env.NOWPAYMENTS_ELITE_USDT || 99),
}

export function siteUrl(){
  return (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "")
}

export function nowpaymentsConfigured(){
  return !!(process.env.NOWPAYMENTS_API_KEY && process.env.NOWPAYMENTS_IPN_SECRET)
}

// NOWPayments IPN signature: HMAC SHA512 of JSON.stringify(body, sorted keys) with IPN secret.
// See https://documenter.getpostman.com/view/7907941/S1a32n38#ipn
export function verifyNowpaymentsSig(rawBody: string, sig: string | null, secret: string): boolean {
  if(!sig || !secret) return false
  try{
    const body = JSON.parse(rawBody)
    const sorted = JSON.stringify(body, Object.keys(body).sort())
    const expected = crypto.createHmac("sha512", secret).update(sorted).digest("hex")
    // Use timingSafeEqual when lengths match
    if(expected.length !== sig.length) return false
    return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))
  }catch{ return false }
}

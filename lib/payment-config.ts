export const CRYPTO_TIERS: Record<string, number> = {
  starter: Number(process.env.CRYPTO_STARTER_USDT || 29),
  pro: Number(process.env.CRYPTO_PRO_USDT || 59),
  elite: Number(process.env.CRYPTO_ELITE_USDT || 99),
}

export type PaymentNetwork = { id: string; name: string; address: string; note: string }

export function paymentConfig(){
  const networks: PaymentNetwork[] = [
    { id: "plasma", name: "Plasma", address: process.env.CRYPTO_PLASMA_ADDRESS || "", note: "USDT على شبكة Plasma فقط" },
    { id: "bsc", name: "BNB Smart Chain (BEP20)", address: process.env.CRYPTO_BSC_ADDRESS || "", note: "USDT BEP20 فقط" },
    { id: "tron", name: "Tron (TRC20)", address: process.env.CRYPTO_TRON_ADDRESS || "", note: "USDT TRC20 فقط" },
    { id: "polygon", name: "Polygon PoS", address: process.env.CRYPTO_POLYGON_ADDRESS || "", note: "USDT على Polygon فقط" },
    { id: "arbitrum", name: "Arbitrum One", address: process.env.CRYPTO_ARBITRUM_ADDRESS || "", note: "USDT على Arbitrum فقط" },
  ].filter(n=>n.address)
  return {
    binancePay: { id: process.env.BINANCE_PAY_ID || "", nickname: process.env.BINANCE_PAY_NICKNAME || "" },
    networks,
    prices: CRYPTO_TIERS,
    nowpayments: !!(process.env.NOWPAYMENTS_API_KEY && process.env.NOWPAYMENTS_IPN_SECRET),
  }
}

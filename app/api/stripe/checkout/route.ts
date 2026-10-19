import { NextRequest, NextResponse } from "next/server"

export async function POST(req: NextRequest){
  const { tier, email } = await req.json().catch(()=>({}))
  if(!["starter","pro","elite"].includes(tier)){
    return NextResponse.json({ error: "invalid tier" }, { status: 400 })
  }
  const secret = process.env.STRIPE_SECRET_KEY
  if(!secret){
    return NextResponse.json({
      error: "Stripe غير مربوط — ضع STRIPE_SECRET_KEY في saros/.env.local و STRIPE_*_PRICE_ID",
      hint: "أنشئ منتجات في stripe.com/dashboard/products وخذ Price IDs"
    }, { status: 503 })
  }
  const priceMap: Record<string,string> = {
    starter: process.env.STRIPE_STARTER_PRICE_ID || "",
    pro: process.env.STRIPE_PRO_PRICE_ID || "",
    elite: process.env.STRIPE_ELITE_PRICE_ID || "",
  }
  const priceId = priceMap[tier]
  if(!priceId){
    return NextResponse.json({ error: `سعر ${tier} غير مربوط — ضع STRIPE_${tier.toUpperCase()}_PRICE_ID` }, { status: 503 })
  }
  // Stripe SDK dynamic import so build doesn't fail without keys
  const Stripe = (await import("stripe")).default
  const stripe = new Stripe(secret)

  const origin = req.headers.get("origin") || process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"
  try{
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${origin}/dashboard?checkout=success&tier=${tier}`,
      cancel_url: `${origin}/#pricing`,
      customer_email: email || undefined,
      metadata: { tier },
    })
    return NextResponse.json({ url: session.url })
  }catch(e:any){
    return NextResponse.json({ error: e.message }, { status: 500 })
  }
}

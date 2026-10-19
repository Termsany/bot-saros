import { NextRequest, NextResponse } from "next/server"

export async function POST(req: NextRequest){
  const { tier } = await req.json().catch(()=>({}))
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

  // The buyer must be signed in: the subscription is tied to their user id, not a typed email
  const token = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  if(!token || !supabaseUrl || !anonKey){
    return NextResponse.json({ error: "سجّل دخول الأول", login: "/auth" }, { status: 401 })
  }
  const { createClient } = await import("@supabase/supabase-js")
  const { data: { user } } = await createClient(supabaseUrl, anonKey).auth.getUser(token)
  if(!user){
    return NextResponse.json({ error: "سجّل دخول الأول", login: "/auth" }, { status: 401 })
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

  // fixed origin — the request's Origin header is attacker-controlled
  const origin = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"
  try{
    // One subscription per user: reuse the Stripe customer and refuse a second active subscription
    // (paying twice created two customers + two subscriptions for the same account)
    let customerId: string | undefined
    const serviceKey = process.env.SUPABASE_SERVICE_KEY
    if(serviceKey){
      const admin = createClient(supabaseUrl, serviceKey)
      const { data: prof } = await admin.from("profiles").select("stripe_customer_id").eq("id", user.id).maybeSingle()
      customerId = prof?.stripe_customer_id || undefined
    }
    if(customerId){
      const subs = await stripe.subscriptions.list({ customer: customerId, status: "active", limit: 1 })
      if(subs.data.length){
        return NextResponse.json({ error: "عندك اشتراك فعّال بالفعل — لتغيير الباقة الغِ الحالي الأول" }, { status: 409 })
      }
    }
    const meta = { tier, user_id: user.id }
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${origin}/dashboard?checkout=success`,
      cancel_url: `${origin}/#pricing`,
      ...(customerId ? { customer: customerId } : { customer_email: user.email || undefined }),
      client_reference_id: user.id,
      metadata: meta,
      subscription_data: { metadata: meta },
    })
    return NextResponse.json({ url: session.url })
  }catch(e:any){
    // Stripe errors can include account/price details — log them, don't send them to the browser
    console.error("stripe checkout:", e?.message)
    return NextResponse.json({ error: "تعذر إنشاء جلسة الدفع — حاول مرة أخرى" }, { status: 500 })
  }
}

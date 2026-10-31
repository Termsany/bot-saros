import { NextRequest, NextResponse } from "next/server"

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const PAID = ["starter","pro","elite"]
const NAMES: Record<string,string> = { starter: "Starter", pro: "Pro", elite: "Elite" }
// the backend's refusals for an invitation, as the invitee should read them
const INVITE_ERRORS: Record<number,string> = {
  403: "الدعوة دي لإيميل تاني، أو لسه ما أكدتش إيميلك",
  404: "الدعوة مش موجودة",
  409: "الدعوة دي مابقتش شغالة، أو انت مشترك في الباقة دي بالفعل",
}

export async function POST(req: NextRequest){
  const body = await req.json().catch(()=>({}))
  const invite = typeof body.invite === "string" && /^[A-Za-z0-9_-]{16,64}$/.test(body.invite) ? body.invite : null
  if(!invite && !PAID.includes(body.tier)){
    return NextResponse.json({ error: "invalid tier" }, { status: 400 })
  }
  const secret = process.env.STRIPE_SECRET_KEY
  if(!secret){
    return NextResponse.json({ error: "الدفع مش متاح دلوقتي (Stripe مش مربوط)" }, { status: 503 })
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

  // What to charge comes from the backend, never from the browser: the admin's current price for the plan, or an
  // invitation's plan and free days (the backend checks it belongs to this account)
  let tier: string = body.tier, price: number | undefined, trialDays: number | null = null
  try{
    if(invite){
      const r = await fetch(`${API}/api/invites/${invite}/checkout`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      if(!r.ok) return NextResponse.json({ error: INVITE_ERRORS[r.status] || "تعذر فتح الدعوة — حاول مرة أخرى" }, { status: r.status === 404 ? 404 : r.status === 403 ? 403 : 409 })
      const t = await r.json()
      tier = t.tier; price = t.price_usd; trialDays = t.trial_days || null
    } else {
      const r = await fetch(`${API}/api/plans`, { cache: "no-store" })
      if(r.ok) price = (await r.json()).prices?.[tier]
    }
  }catch{ /* handled below */ }
  if(!PAID.includes(tier) || !Number.isInteger(price) || !price || price < 1){
    return NextResponse.json({ error: "تعذر معرفة سعر الباقة دلوقتي — حاول بعد شوية" }, { status: 503 })
  }
  // an existing Stripe product per plan keeps the dashboard tidy; without one Stripe makes it from the name
  const productId = process.env[`STRIPE_${tier.toUpperCase()}_PRODUCT_ID`]
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
    const meta: Record<string,string> = { tier, user_id: user.id, ...(invite ? { invite } : {}) }
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ quantity: 1, price_data: {
        currency: "usd", unit_amount: price * 100, recurring: { interval: "month" },
        ...(productId ? { product: productId } : { product_data: { name: `RAQM ${NAMES[tier]}` } }),
      } }],
      success_url: `${origin}/dashboard?checkout=success`,
      cancel_url: `${origin}/#pricing`,
      ...(customerId ? { customer: customerId } : { customer_email: user.email || undefined }),
      client_reference_id: user.id,
      metadata: meta,
      subscription_data: { metadata: meta, ...(trialDays ? { trial_period_days: trialDays } : {}) },
    })
    return NextResponse.json({ url: session.url })
  }catch(e:any){
    // Stripe errors can include account/price details — log them, don't send them to the browser
    console.error("stripe checkout:", e?.message)
    return NextResponse.json({ error: "تعذر إنشاء جلسة الدفع — حاول مرة أخرى" }, { status: 500 })
  }
}

import { NextRequest, NextResponse } from "next/server"

export async function POST(req: NextRequest){
  const secret = process.env.STRIPE_SECRET_KEY
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET
  if(!secret || !webhookSecret){
    return NextResponse.json({ error: "webhook not configured" }, { status: 503 })
  }
  const Stripe = (await import("stripe")).default
  const stripe = new Stripe(secret)
  const sig = req.headers.get("stripe-signature") || ""
  const body = await req.text()
  let event: any
  try{
    event = stripe.webhooks.constructEvent(body, sig, webhookSecret)
  }catch(e:any){
    return NextResponse.json({ error: `signature: ${e.message}` }, { status: 400 })
  }

  // Map Stripe price -> tier by env
  const priceToTier: Record<string,string> = {}
  if(process.env.STRIPE_STARTER_PRICE_ID) priceToTier[process.env.STRIPE_STARTER_PRICE_ID]="starter"
  if(process.env.STRIPE_PRO_PRICE_ID) priceToTier[process.env.STRIPE_PRO_PRICE_ID]="pro"
  if(process.env.STRIPE_ELITE_PRICE_ID) priceToTier[process.env.STRIPE_ELITE_PRICE_ID]="elite"

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const serviceKey = process.env.SUPABASE_SERVICE_KEY
  async function updateTier(email: string, tier: string){
    if(!supabaseUrl || !serviceKey) return
    const { createClient } = await import("@supabase/supabase-js")
    const admin = createClient(supabaseUrl, serviceKey)
    // find user by email via auth admin
    const { data } = await admin.auth.admin.listUsers()
    const user = data.users.find((u:any)=> u.email===email)
    if(!user) return
    await admin.from("profiles").upsert({ id: user.id, email, tier }, { onConflict: "id" })
  }

  if(event.type==="checkout.session.completed"){
    const s = event.data.object
    const email = s.customer_email || s.customer_details?.email
    const tier = s.metadata?.tier || priceToTier[s.line_items?.data?.[0]?.price?.id] || "pro"
    if(email) await updateTier(email, tier)
  }
  if(event.type==="customer.subscription.deleted"){
    const sub = event.data.object
    const email = (sub as any).customer_email
    // downgrade to free on cancel — needs customer lookup
  }

  return NextResponse.json({ received: true })
}

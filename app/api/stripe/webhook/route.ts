import { NextRequest, NextResponse } from "next/server"

const PAID_TIERS = ["starter","pro","elite"]
const ACTIVE = ["active","trialing"]
const ENDED = ["canceled","unpaid","incomplete_expired"]

export async function POST(req: NextRequest){
  const secret = process.env.STRIPE_SECRET_KEY
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const serviceKey = process.env.SUPABASE_SERVICE_KEY
  if(!secret || !webhookSecret || !supabaseUrl || !serviceKey){
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

  const { createClient } = await import("@supabase/supabase-js")
  const admin = createClient(supabaseUrl, serviceKey)

  // Find the profile: user id from our metadata first, then Stripe customer id, then email
  async function findUserId(opts: { userId?: string, customer?: string, email?: string }): Promise<string|null>{
    if(opts.userId) return opts.userId
    if(opts.customer){
      const { data } = await admin.from("profiles").select("id").eq("stripe_customer_id", opts.customer).maybeSingle()
      if(data?.id) return data.id
    }
    if(opts.email){
      const { data } = await admin.from("profiles").select("id").eq("email", opts.email).maybeSingle()
      if(data?.id) return data.id
    }
    return null
  }
  async function setTier(userId: string, tier: string, customer?: string){
    const { data: existing } = await admin.from("profiles").select("id").eq("id", userId).maybeSingle()
    if(existing){
      const patch: any = { tier }
      if(customer) patch.stripe_customer_id = customer
      const { error } = await admin.from("profiles").update(patch).eq("id", userId)
      if(error) throw new Error(error.message)
    } else {
      // No profile yet (Stripe paid but Supabase has no row) — create it
      const { data: userData } = await admin.auth.admin.getUserById(userId)
      const email = customer ? undefined : userData?.user?.email
      const row: any = { id: userId, tier, email: email || null }
      if(customer) row.stripe_customer_id = customer
      const { error } = await admin.from("profiles").insert(row)
      if(error) throw new Error(error.message)
    }
  }

  try{
    if(event.type==="checkout.session.completed"){
      const s = event.data.object
      const tier = s.metadata?.tier
      const userId = await findUserId({ userId: s.client_reference_id || s.metadata?.user_id, email: s.customer_details?.email || s.customer_email })
      if(userId && PAID_TIERS.includes(tier)) await setTier(userId, tier, typeof s.customer === "string" ? s.customer : undefined)
      else console.warn("checkout.session.completed: no user/tier", s.id)
    }

    if(event.type==="customer.subscription.created" || event.type==="customer.subscription.updated" || event.type==="customer.subscription.deleted"){
      const sub = event.data.object
      const customer = typeof sub.customer === "string" ? sub.customer : sub.customer?.id
      const userId = await findUserId({ userId: sub.metadata?.user_id, customer })
      if(userId){
        if(event.type==="customer.subscription.deleted" || ENDED.includes(sub.status)){
          await setTier(userId, "free", customer)
        } else if(ACTIVE.includes(sub.status)){
          const tier = priceToTier[sub.items?.data?.[0]?.price?.id] || sub.metadata?.tier
          if(PAID_TIERS.includes(tier)) await setTier(userId, tier, customer)
        }
      } else console.warn(`${event.type}: no user for customer`, customer)
    }
  }catch(e:any){
    // 500 so Stripe retries the event
    return NextResponse.json({ error: e.message }, { status: 500 })
  }

  return NextResponse.json({ received: true })
}

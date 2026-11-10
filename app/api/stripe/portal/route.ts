import { NextRequest, NextResponse } from "next/server"

// The subscriber's own Stripe Customer Portal (cancel, card, invoices): the terms say "cancel anytime", so the site
// must give a way to. The customer comes from the signed-in user's profile (stripe_customer_id, written by the
// webhook) — never from the request. Needs the portal turned on in Stripe (Settings → Billing → Customer portal).
const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://bot-saros.vercel.app"

export async function POST(req: NextRequest){
  const token = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  const serviceKey = process.env.SUPABASE_SERVICE_KEY
  const secret = process.env.STRIPE_SECRET_KEY
  if(!token || !supabaseUrl || !anonKey) return NextResponse.json({ error: "سجّل دخول الأول", login: "/auth" }, { status: 401 })
  if(!serviceKey || !secret) return NextResponse.json({ error: "إدارة الاشتراك مش متاحة دلوقتي" }, { status: 503 })
  const { createClient } = await import("@supabase/supabase-js")
  const { data: { user } } = await createClient(supabaseUrl, anonKey).auth.getUser(token)
  if(!user) return NextResponse.json({ error: "سجّل دخول الأول", login: "/auth" }, { status: 401 })
  const { data: profile } = await createClient(supabaseUrl, serviceKey).from("profiles").select("stripe_customer_id").eq("id", user.id).maybeSingle()
  const customer = profile?.stripe_customer_id
  if(!customer) return NextResponse.json({ error: "مفيش اشتراك مدفوع على حسابك (الهدايا والباقات من الإدارة مابتتلغيش من هنا)" }, { status: 404 })
  try{
    const Stripe = (await import("stripe")).default
    const session = await new Stripe(secret).billingPortal.sessions.create({ customer, return_url: `${SITE}/dashboard` })
    return NextResponse.json({ url: session.url }, { headers: { "Cache-Control": "no-store" } })
  }catch(e: any){
    return NextResponse.json({ error: "صفحة إدارة الاشتراك مش متاحة دلوقتي — كلّمنا ونلغيه لك" }, { status: 502 })
  }
}

import { NextRequest, NextResponse } from "next/server"
import { adminClient, authenticatedUser } from "@/lib/server-auth"
import { NOWPAYMENTS_TIERS, nowpaymentsConfigured, siteUrl } from "@/lib/nowpayments"

const TIERS = new Set(["starter","pro","elite"])

export async function POST(req: NextRequest){
  const user = await authenticatedUser(req)
  if(!user) return NextResponse.json({ error: "سجّل دخول الأول", login: "/auth" }, { status: 401 })
  const body = await req.json().catch(()=>({}))
  const tier = String(body.tier || "").toLowerCase()
  const payCurrency = body.pay_currency ? String(body.pay_currency).toLowerCase().replace(/[^a-z0-9]/g,"") : undefined
  if(!TIERS.has(tier)) return NextResponse.json({ error: "invalid tier" }, { status: 400 })
  if(!nowpaymentsConfigured()) return NextResponse.json({ error: "بوابة الكريبتو غير مهيأة بعد" }, { status: 503 })

  const apiKey = process.env.NOWPAYMENTS_API_KEY!
  const price_amount = NOWPAYMENTS_TIERS[tier]
  const price_currency = "usd"
  const order_id = `${user.id.slice(0,8)}-${tier}-${Date.now()}`
  const ipn_callback_url = `${siteUrl()}/api/payments/nowpayments/ipn`
  const success_url = `${siteUrl()}/dashboard?checkout=success`
  const cancel_url = `${siteUrl()}/pay?cancel=1`

  // Create hosted invoice — NOWPayments shows coin selector, handles address, confirmations, and IPN.
  const payload: any = {
    price_amount, price_currency, order_id,
    order_description: `Bot Saros ${tier}`,
    ipn_callback_url, success_url, cancel_url,
    is_fixed_rate: true, is_fee_paid_by_user: false,
  }
  if(payCurrency) payload.pay_currency = payCurrency

  let invoice: any
  try{
    const r = await fetch("https://api.nowpayments.io/v1/invoice", {
      method: "POST",
      headers: { "x-api-key": apiKey, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
    const j = await r.json().catch(()=>({}))
    if(!r.ok) return NextResponse.json({ error: j.message || "تعذر إنشاء الفاتورة" }, { status: 502 })
    invoice = j
  }catch{
    return NextResponse.json({ error: "تعذر الاتصال ببوابة الدفع" }, { status: 502 })
  }

  // Persist mapping for IPN reconciliation
  try{
    const db = adminClient()
    await db.from("nowpayments_payments").insert({
      user_id: user.id, email: user.email || null, tier,
      price_amount, price_currency, pay_currency: payCurrency || null,
      order_id, invoice_id: String(invoice.id || ""), invoice_url: invoice.invoice_url || null,
      status: "waiting", raw: invoice,
    })
  }catch(e:any){
    // Don't block checkout on DB error, but log
    console.error("nowpayments insert:", e?.message)
  }

  return NextResponse.json({ invoice_url: invoice.invoice_url, invoice_id: invoice.id, order_id })
}

import { NextRequest, NextResponse } from "next/server"
import { adminClient } from "@/lib/server-auth"
import { verifyNowpaymentsSig } from "@/lib/nowpayments"

// NOWPayments IPN posts JSON with header x-nowpayments-sig.
// We verify HMAC SHA512(sorted JSON) with NOWPAYMENTS_IPN_SECRET, then grant tier on finished only.
export async function POST(req: NextRequest){
  const secret = process.env.NOWPAYMENTS_IPN_SECRET || ""
  const sig = req.headers.get("x-nowpayments-sig")
  const raw = await req.text()
  if(!secret) return NextResponse.json({ error: "ipn not configured" }, { status: 503 })
  if(!verifyNowpaymentsSig(raw, sig, secret)) return NextResponse.json({ error: "bad signature" }, { status: 401 })

  let body: any
  try{ body = JSON.parse(raw) }catch{ return NextResponse.json({ error: "bad json" }, { status: 400 }) }

  const payment_status = String(body.payment_status || body.status || "").toLowerCase()
  const order_id = String(body.order_id || "")
  const payment_id = body.payment_id != null ? String(body.payment_id) : null
  const invoice_id = body.invoice_id != null ? String(body.invoice_id) : (body.purchase_id != null ? String(body.purchase_id) : null)

  // Find our record by order_id, fallback to invoice/payment id
  const db = adminClient()
  let row: any = null
  if(order_id){
    const { data } = await db.from("nowpayments_payments").select("*").eq("order_id", order_id).maybeSingle()
    row = data
  }
  if(!row && payment_id){
    const { data } = await db.from("nowpayments_payments").select("*").eq("payment_id", payment_id).maybeSingle()
    row = data
  }
  if(!row && invoice_id){
    const { data } = await db.from("nowpayments_payments").select("*").eq("invoice_id", invoice_id).maybeSingle()
    row = data
  }
  if(!row){
    // Unknown order — still ack to avoid retries, but log
    console.warn("nowpayments ipn: unknown order", order_id, payment_id, invoice_id)
    return NextResponse.json({ received: true, unknown: true })
  }

  // Persist status update
  const patch: any = {
    status: payment_status || row.status,
    payment_id: payment_id || row.payment_id,
    invoice_id: invoice_id || row.invoice_id,
    pay_address: body.pay_address || row.pay_address,
    pay_amount: body.pay_amount ?? row.pay_amount,
    pay_currency: body.pay_currency || row.pay_currency,
    raw: body, updated_at: new Date().toISOString(),
  }
  await db.from("nowpayments_payments").update(patch).eq("id", row.id)

  // Only grant on terminal success. NOWPayments invoice IPN uses payment_status=finished.
  // States: waiting, confirming, confirmed, sending, partially_paid, finished, failed, refunded, expired
  if(payment_status === "finished"){
    // Idempotent: if already finished for this payment_id, skip
    const { data: existing } = await db.from("nowpayments_payments").select("id").eq("id", row.id).maybeSingle()
    if(existing){
      const { error } = await db.rpc("grant_nowpayments_tier", { p_user: row.user_id, p_tier: row.tier })
      if(error) {
        console.error("grant_nowpayments_tier:", error.message)
        return NextResponse.json({ error: error.message }, { status: 500 })
      }
    }
  }

  // Partially paid, failed, expired, etc. — no grant, just record
  return NextResponse.json({ received: true })
}

import { NextRequest, NextResponse } from "next/server"
import { adminClient, requireAdmin } from "@/lib/server-auth"

const PAID = new Set(["starter","pro","elite"])

export async function GET(req: NextRequest){
  if(!await requireAdmin(req)) return NextResponse.json({ error: "admin only" }, { status: 403 })
  try{
    const status = new URL(req.url).searchParams.get("status") || "pending"
    const q = adminClient().from("crypto_payment_requests").select("*").order("created_at", { ascending: false }).limit(100)
    const { data, error } = status === "all" ? await q : await q.eq("status", status)
    if(error) throw error
    return NextResponse.json({ payments: data || [] })
  }catch{
    return NextResponse.json({ error: "تعذر تحميل المدفوعات" }, { status: 503 })
  }
}

export async function PATCH(req: NextRequest){
  const admin = await requireAdmin(req)
  if(!admin) return NextResponse.json({ error: "admin only" }, { status: 403 })
  const body = await req.json().catch(()=>({}))
  const id = Number(body.id)
  const action = String(body.action || "")
  const adminNote = String(body.note || "").trim().slice(0, 500)
  if(!Number.isInteger(id) || !["approve","reject"].includes(action)) return NextResponse.json({ error: "bad request" }, { status: 400 })
  const db = adminClient()
  try{
    const { data: existing, error: loadError } = await db.from("crypto_payment_requests").select("*").eq("id", id).single()
    if(loadError || !existing) return NextResponse.json({ error: "الطلب غير موجود" }, { status: 404 })
    if(existing.status === "approved"){
      if(action === "approve") return NextResponse.json({ ok: true, payment: existing })
      return NextResponse.json({ error: "لا يمكن رفض دفعة تم اعتمادها" }, { status: 409 })
    }
    if(existing.status === "rejected"){
      if(action === "reject") return NextResponse.json({ ok: true, payment: existing })
      return NextResponse.json({ error: "لا يمكن اعتماد طلب مرفوض بدون إجراء استرجاع منفصل" }, { status: 409 })
    }
    if(action === "reject"){
      const { data, error } = await db.from("crypto_payment_requests").update({ status: "rejected", admin_note: adminNote, reviewed_at: new Date().toISOString(), reviewed_by: admin.id })
        .eq("id", id).eq("status", "pending").select("*").single()
      if(error) throw error
      return NextResponse.json({ ok: true, payment: data })
    }
    if(!PAID.has(existing.tier)) return NextResponse.json({ error: "invalid tier" }, { status: 400 })
    const { data, error } = await db.rpc("approve_crypto_payment", {
      p_id: id, p_reviewer: admin.id, p_note: adminNote,
    })
    if(error){
      const m = String(error.message || "")
      if(m.includes("external_subscription_active")) return NextResponse.json({ error: "الحساب عليه اشتراك خارجي نشط؛ راجعه قبل اعتماد دفعة يدوية" }, { status: 409 })
      if(m.includes("payment_not_pending")) return NextResponse.json({ error: "الطلب تمت مراجعته بالفعل" }, { status: 409 })
      throw error
    }
    return NextResponse.json(data)
  }catch{
    return NextResponse.json({ error: "تعذر اعتماد الدفع؛ لم يتم تفعيل الباقة" }, { status: 503 })
  }
}

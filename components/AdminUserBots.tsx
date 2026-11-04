"use client"
import { useEffect, useState } from "react"
import { apiAdminApproveUser, apiAdminUserBots } from "@/lib/api"
import { LABELS } from "@/components/LiveStrategies"
import { Card, CardHeader, Pill, btn, type Tone } from "@/components/ui"

const STATE: Record<string, [string, Tone]> = {
  running: ["شغّال", "profit"], waiting_approval: ["مستني موافقتك", "corona"], no_consent: ["ناقص الموافقة", "neutral"],
  no_keys: ["ناقص المفاتيح", "neutral"], no_place: ["مفيش مكان", "corona"], off: ["متوقف", "neutral"], refused: ["اترفض", "loss"],
  owner_key: ["مفتاحك انت", "loss"],
}

/** The users who asked for their own bots (Phase 2, Demo only) or that the owner approved: the approval, what the
 *  server's provisioner answered and how their bots are. Approving: the owner's gift invitation (accepting it approves
 *  the account) or the button here; the server's /etc/raqm-users/allow.list still counts too (plan 4.1). */
export function AdminUserBots(){
  const [d, setD] = useState<any|null|undefined>(undefined)
  const [busy, setBusy] = useState("")
  const [err, setErr] = useState("")
  const load = () => apiAdminUserBots().then(setD)
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t) }, [])
  if(!d || !(d.users || []).length) return null
  const running = d.users.filter((u: any) => u.provision?.state === "running").length
  async function approve(uid: string, on: boolean){
    if(!on && !window.confirm("توقف موافقة الحساب ده؟ مش هيفتح صفقات جديدة، والمفتوح بيخرج على قاعدته ووقفه.")) return
    setBusy(uid); setErr("")
    try { await apiAdminApproveUser(uid, on); await load() } catch(e: any) { setErr(e.message || "ما اتحفظش") } finally { setBusy("") }
  }
  return (
    <Card>
      <CardHeader title="بوتات المستخدمين (Demo)" sub={`${running} من ${d.max_users} أماكن مستخدمة · الدعوة الهدية بتوافق على الحساب لوحدها`} />
      {err && <p className="mb-2 text-[13px] text-loss">{err}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead className="text-[12px] text-faint"><tr>{["المستخدم", "الموافقة", "الحالة", "الاستراتيجيات", "صفقات مفتوحة", "مشاكل"].map(h => <th key={h} className="px-2 py-2 text-right font-semibold">{h}</th>)}</tr></thead>
          <tbody>
            {d.users.map((u: any) => {
              const [st, tone] = STATE[u.provision?.state] || ["لسه", "neutral"] as [string, Tone]
              const bots = Object.values(u.bots || {}) as any[]
              const problems = bots.filter(b => !b.running || b.review || b.unprotected || b.entry_block).length
              return (
                <tr key={u.user_id} className="border-t border-line">
                  <td className="px-2 py-2.5 font-mono text-[12px]" dir="ltr" style={{ textAlign: "right" }}>{u.user_id}</td>
                  <td className="px-2 py-2.5">
                    <button disabled={busy === u.user_id} onClick={() => approve(u.user_id, !u.approved)}
                      className={u.approved ? btn.secondary : btn.primary}>{u.approved ? "موافَق · شيل" : "وافق"}</button>
                  </td>
                  <td className="px-2 py-2.5">{u.provision ? <Pill tone={tone}>{st}</Pill> : <span className="text-faint">لسه ما طلبش بوتات</span>}</td>
                  <td className="px-2 py-2.5">{(u.desired?.strategies || []).map((s: string) => LABELS[s] || s).join("، ") || "—"}</td>
                  <td className="px-2 py-2.5 font-mono">{bots.reduce((a, b) => a + (b.positions || 0), 0)}</td>
                  <td className="px-2 py-2.5">{problems ? <Pill tone="loss">{problems}</Pill> : <span className="text-faint">—</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

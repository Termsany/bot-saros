"use client"
import { useEffect, useState } from "react"
import { apiAdminUserBots } from "@/lib/api"
import { LABELS } from "@/components/LiveStrategies"
import { Card, CardHeader, Pill, type Tone } from "@/components/ui"

const STATE: Record<string, [string, Tone]> = {
  running: ["شغّال", "profit"], waiting_approval: ["مستني موافقتك", "corona"], no_consent: ["ناقص الموافقة", "neutral"],
  no_keys: ["ناقص المفاتيح", "neutral"], no_place: ["مفيش مكان", "corona"], off: ["متوقف", "neutral"], refused: ["اترفض", "loss"],
}

/** The users who asked for their own bots (Phase 2, Demo only): what the server's provisioner answered and how their
 *  bots are. Approving a user is the allow-list on the server (/etc/raqm-users/allow.list), root's only. */
export function AdminUserBots(){
  const [d, setD] = useState<any|null|undefined>(undefined)
  useEffect(() => { const load = () => apiAdminUserBots().then(setD); load(); const t = setInterval(load, 60_000); return () => clearInterval(t) }, [])
  if(!d || !(d.users || []).length) return null
  const running = d.users.filter((u: any) => u.provision?.state === "running").length
  return (
    <Card>
      <CardHeader title="بوتات المستخدمين (Demo)" sub={`${running} من ${d.max_users} أماكن مستخدمة · الموافقة على مستخدم من قايمة السيرفر`} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead className="text-[12px] text-faint"><tr>{["المستخدم", "الحالة", "الاستراتيجيات", "صفقات مفتوحة", "مشاكل"].map(h => <th key={h} className="px-2 py-2 text-right font-semibold">{h}</th>)}</tr></thead>
          <tbody>
            {d.users.map((u: any) => {
              const [st, tone] = STATE[u.provision?.state] || ["لسه", "neutral"]
              const bots = Object.values(u.bots || {}) as any[]
              const problems = bots.filter(b => !b.running || b.review || b.unprotected || b.entry_block).length
              return (
                <tr key={u.user_id} className="border-t border-line">
                  <td className="px-2 py-2.5 font-mono text-[12px]" dir="ltr" style={{ textAlign: "right" }}>{u.user_id}</td>
                  <td className="px-2 py-2.5"><Pill tone={tone}>{st}</Pill></td>
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

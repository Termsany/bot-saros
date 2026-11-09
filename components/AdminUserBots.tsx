"use client"
import { useEffect, useState } from "react"
import { apiAdminApproveUser, apiAdminUserBots, apiAdminUsersLive, apiSetAdminUsersLive } from "@/lib/api"
import { LABELS } from "@/components/LiveStrategies"
import { Card, CardHeader, Pill, btn, type Tone } from "@/components/ui"

const STATE: Record<string, [string, Tone]> = {
  running: ["شغّال", "profit"], waiting_approval: ["مستني موافقتك", "corona"], no_consent: ["ناقص الموافقة", "neutral"],
  no_keys: ["ناقص المفاتيح", "neutral"], no_place: ["مفيش مكان", "corona"], off: ["متوقف", "neutral"], refused: ["اترفض", "loss"],
  owner_key: ["مفتاحك انت", "loss"], live_off: ["الفلوس الحقيقية مقفولة", "corona"], key_refused: ["المفتاح اترفض", "loss"],
}

/** The owner's switch for real money for invited users (owner, 2026-11-07: from the site, no server command). The
 *  server's provisioner also needs root's main lock (/etc/raqm-users/live.enabled), out of the site's reach. Off: no
 *  user's real-money bot starts, and the running ones stop opening new baskets; their trades still exit with stops. */
export function AdminUsersLive(){
  const [s, setS] = useState<{ on: boolean, by: string | null, at: string | null } | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const load = () => apiAdminUsersLive().then(setS)
  useEffect(() => { load() }, [])
  if(!s) return null
  async function flip(){
    const on = !s!.on
    const text = on
      ? "⚠️ فلوس حقيقية للمستخدمين المدعوين\n\nتفتحها؟ أي حساب انت دعيته، مفتاحه عدّى فحص السيرفر، ووافق على أرقامه، هيبدأ يتداول بفلوسه الحقيقية خلال دقيقة."
      : "تقفل الفلوس الحقيقية للمستخدمين؟\n\nمفيش بوت فلوس حقيقية هيبدأ، واللي شغّالين هيبطّلوا يفتحوا سلات جديدة. صفقاتهم المفتوحة بتخرج على قاعدتها ووقفها."
    if(!window.confirm(text)) return
    setBusy(true); setErr("")
    try { await apiSetAdminUsersLive(on); await load() } catch(e: any) { setErr(e.message || "ما اتحفظش") } finally { setBusy(false) }
  }
  return (
    <Card className={s.on ? "border-loss/45" : undefined}>
      <CardHeader title="فلوس حقيقية للمستخدمين المدعوين" action={<Pill tone={s.on ? "loss" : "neutral"}>{s.on ? "مفتوحة" : "مقفولة"}</Pill>}
        sub="momentum بس · كل واحد بمفاتيحه وأرقامه وموافقته · السيرفر بيشوف الزرار ده كل دقيقة" />
      {s.at && <p className="mb-2 text-[12px] text-faint" dir="ltr" style={{ textAlign: "right" }}>{s.by} · {s.at.slice(0, 16).replace("T", " ")} UTC</p>}
      {err && <p className="mb-2 text-[13px] text-loss">{err}</p>}
      <button onClick={flip} disabled={busy} data-testid="users-live-switch" className={s.on ? btn.secondary : btn.primary}>
        {s.on ? "اقفل الفلوس الحقيقية للمستخدمين" : "افتح الفلوس الحقيقية للمستخدمين"}</button>
    </Card>
  )
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
      <CardHeader title="بوتات المستخدمين" sub={`${running} من ${d.max_users} أماكن مستخدمة · الدعوة الهدية بتوافق على الحساب لوحدها`} />
      {err && <p className="mb-2 text-[13px] text-loss">{err}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead className="text-[12px] text-faint"><tr>{["المستخدم", "الموافقة", "الحالة", "الفلوس", "الاستراتيجيات", "صفقات مفتوحة", "مشاكل"].map(h => <th key={h} className="px-2 py-2 text-right font-semibold">{h}</th>)}</tr></thead>
          <tbody>
            {d.users.map((u: any) => {
              const [st, tone] = STATE[u.provision?.state] || ["لسه", "neutral"] as [string, Tone]
              const bots = Object.values(u.bots || {}) as any[]
              const problems = bots.filter(b => !b.running || b.review || b.unprotected || b.entry_block).length
              return (
                <tr key={u.user_id} className="border-t border-line">
                  <td className="px-2 py-2.5" dir="ltr" style={{ textAlign: "right" }} data-testid="user-bots-who">
                    {u.email ? <div className="text-[13px] font-semibold text-ink">{u.email}</div> : null}
                    <div className={`font-mono ${u.email ? "text-[11px] text-faint" : "text-[12px]"}`}>{u.email ? u.user_id.slice(0, 8) : u.user_id}</div>
                  </td>
                  <td className="px-2 py-2.5">
                    <button disabled={busy === u.user_id} onClick={() => approve(u.user_id, !u.approved)}
                      className={u.approved ? btn.secondary : btn.primary}>{u.approved ? "موافَق · شيل" : "وافق"}</button>
                  </td>
                  <td className="px-2 py-2.5">{u.provision ? <Pill tone={tone}>{st}</Pill> : <span className="text-faint">لسه ما طلبش بوتات</span>}</td>
                  <td className="px-2 py-2.5">{!u.desired ? "—" : u.desired.env === "live"
                    ? <Pill tone="loss">{`حقيقية · ${u.desired.capital_usdt}$ / ${u.desired.capital_margin_override_usdt}$`}</Pill>
                    : <Pill tone="neutral">Demo</Pill>}</td>
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

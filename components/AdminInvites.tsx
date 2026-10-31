"use client"
import { useCallback, useEffect, useState } from "react"
import { Check, Copy, Gift, Link2, Mail, Timer, X } from "lucide-react"
import { Card, CardHeader, Pill, btn, field, label, type Tone } from "@/components/ui"
import { authHeaders } from "@/lib/supabase"

/** Admin: invitations by email (a plan as a gift, a free trial before paying, or a payment link), and plan prices.
 *  Data: /api/admin/invites, /api/admin/plans (backend/app/plans_invites.py has the rules). */

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const PAID = ["starter", "pro", "elite"] as const
const NAME: Record<string, string> = { free: "Free", starter: "Starter", pro: "Pro", elite: "Elite" }
const KIND: Record<string, { title: string, sub: string, icon: typeof Gift }> = {
  gift: { title: "هدية", sub: "الباقة مجانًا لمدة محددة، وبعدها يرجع Free لوحده", icon: Gift },
  trial: { title: "تجربة ثم دفع", sub: "يدخل كارت على Stripe، والخصم بيبدأ بعد الأيام المجانية", icon: Timer },
  paid: { title: "رابط دفع", sub: "اشتراك شهري مباشر بالسعر الحالي", icon: Link2 },
}
const STATE: Record<string, [string, Tone]> = {
  pending: ["مستنية", "corona"], accepted: ["اتقبلت", "profit"], subscribed: ["اشترك", "profit"],
  revoked: ["اتلغت", "neutral"], expired: ["الرابط خلص", "neutral"],
}
const fmtDate = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString("ar-EG", { day: "numeric", month: "short" }) : "—"
const daysLeft = (iso?: string | null) => iso ? Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)) : 0

async function call(path: string, method = "GET", body?: any){
  const r = await fetch(API + path, { method, headers: { ...(await authHeaders()), "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, cache: "no-store" })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "الطلب ما اتنفذش")
  return j
}

function CopyLink({ link, compact = false }: { link: string, compact?: boolean }){
  const [done, setDone] = useState(false)
  const copy = async () => { try { await navigator.clipboard.writeText(link); setDone(true); setTimeout(() => setDone(false), 1500) } catch {} }
  if (compact) return <button onClick={copy} title={link} className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface2 px-2.5 py-1 text-[12px] font-semibold text-muted transition hover:text-ink">{done ? <Check size={13} className="text-profit"/> : <Copy size={13}/>}{done ? "اتنسخ" : "الرابط"}</button>
  return (
    <div className="flex items-center gap-2 rounded-xl border border-line bg-void p-1.5 pr-3">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted" dir="ltr">{link}</span>
      <button onClick={copy} className="inline-flex shrink-0 items-center gap-1.5 rounded-[9px] bg-surface2 px-3 py-1.5 text-[13px] font-semibold">{done ? <Check size={14} className="text-profit"/> : <Copy size={14}/>}{done ? "اتنسخ" : "انسخ"}</button>
    </div>
  )
}

/** The invite form (modal). Shows the link once created, whether or not the email went out. */
export function InviteDialog({ open, onClose, prices, emailConfigured, onCreated }: {
  open: boolean, onClose: () => void, prices: Record<string, number>, emailConfigured: boolean, onCreated: () => void,
}){
  const [email, setEmail] = useState("")
  const [tier, setTier] = useState<string>("pro")
  const [kind, setKind] = useState<string>("gift")
  const [days, setDays] = useState("30")
  const [note, setNote] = useState("")
  const [sendEmail, setSendEmail] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [done, setDone] = useState<{ link: string, emailed: boolean, email_error?: string } | null>(null)
  useEffect(() => { if (open) { setEmail(""); setTier("pro"); setKind("gift"); setDays("30"); setNote(""); setSendEmail(emailConfigured); setErr(""); setDone(null) } }, [open, emailConfigured])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])
  if (!open) return null
  const n = Number(days), needsDays = kind !== "paid"
  const price = prices[tier]
  const offer = kind === "gift" ? `باقة ${NAME[tier]} هدية لمدة ${n || "؟"} يوم`
    : kind === "trial" ? `باقة ${NAME[tier]} مجانًا ${n || "؟"} يوم، وبعدها $${price} في الشهر` : `اشتراك باقة ${NAME[tier]} بـ $${price} في الشهر`
  const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) && (!needsDays || (Number.isInteger(n) && n >= 1 && n <= 365))

  async function submit(){
    if (!confirm(`تبعت دعوة لـ ${email.trim()}:\n${offer}؟`)) return
    setBusy(true); setErr("")
    try {
      const j = await call("/api/admin/invites", "POST", { email: email.trim(), tier, kind, days: needsDays ? n : null, note: note.trim() || null, send_email: sendEmail, confirm: true })
      setDone({ link: j.invite.link, emailed: j.emailed, email_error: j.email_error }); onCreated()
    } catch (e: any) { setErr(e.message.includes("already a pending") ? "فيه دعوة مستنية للإيميل ده بالفعل — ابعتها تاني أو الغيها من الجدول" : e.message) }
    finally { setBusy(false) }
  }

  return (
    <div dir="rtl" className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-void/80 p-4 pt-16 backdrop-blur-sm" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label="ادعُ مستخدم" className="w-full max-w-[560px] rounded-2xl border border-line bg-surface p-6 shadow-2xl" onMouseDown={e => e.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div><h2 className="text-[20px] font-bold">ادعُ مستخدم</h2><p className="mt-0.5 text-[13px] text-muted">باقة هدية، أو تجربة مجانية، أو رابط دفع — لإيميل واحد</p></div>
          <button onClick={onClose} aria-label="إغلاق" className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-surface2 hover:text-ink"><X size={18}/></button>
        </div>

        {done ? (
          <div className="space-y-4">
            <div className={`rounded-xl border px-4 py-3 text-[14px] ${done.emailed ? "border-profit/30 bg-profit/10 text-profit" : "border-corona/30 bg-corona/10 text-corona"}`}>
              {done.emailed ? <>اتبعتت على <b dir="ltr">{email.trim()}</b> ✓</> : sendEmail ? "الدعوة اتعملت بس الإيميل ما اتبعتش — انسخ الرابط وابعته بنفسك." : "الدعوة اتعملت — انسخ الرابط وابعته بنفسك."}
            </div>
            <div><span className={label}>رابط الدعوة (شغال 14 يوم، ولنفس الإيميل بس)</span><CopyLink link={done.link}/></div>
            <div className="flex gap-2"><button onClick={onClose} className={`${btn.primary} flex-1`}>تمام</button></div>
          </div>
        ) : (
          <div className="space-y-5">
            <label className="block"><span className={label}>الإيميل</span>
              <input value={email} onChange={e => setEmail(e.target.value)} type="email" dir="ltr" placeholder="name@example.com" autoFocus className={field}/>
            </label>

            <div><span className={label}>الباقة</span>
              <div className="grid grid-cols-3 gap-2">
                {PAID.map(t => (
                  <button key={t} onClick={() => setTier(t)} className={`rounded-xl border px-3 py-2.5 text-right transition ${tier === t ? "border-corona/60 bg-corona/10" : "border-line bg-surface2 hover:border-corona/30"}`}>
                    <div className="text-[14px] font-bold">{NAME[t]}</div>
                    <div className="font-mono text-[12px] text-muted" dir="ltr" style={{ textAlign: "right" }}>${prices[t]}/mo</div>
                  </button>
                ))}
              </div>
            </div>

            <div><span className={label}>نوع الدعوة</span>
              <div className="space-y-2">
                {Object.entries(KIND).map(([k, v]) => { const Icon = v.icon; return (
                  <button key={k} onClick={() => setKind(k)} className={`flex w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-right transition ${kind === k ? "border-corona/60 bg-corona/10" : "border-line bg-surface2 hover:border-corona/30"}`}>
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${kind === k ? "bg-corona text-void" : "bg-surface text-muted"}`}><Icon size={18}/></span>
                    <span className="min-w-0"><span className="block text-[14px] font-bold">{v.title}</span><span className="block text-[12px] text-muted">{v.sub}</span></span>
                  </button>
                ) })}
              </div>
            </div>

            {needsDays && (
              <div><span className={label}>{kind === "gift" ? "مدة الهدية (يوم)" : "الأيام المجانية قبل أول خصم"}</span>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="w-24"><input value={days} onChange={e => setDays(e.target.value)} type="number" min={1} max={365} dir="ltr" className={`${field} font-mono`}/></div>
                  {[7, 14, 30, 90].map(d => <button key={d} onClick={() => setDays(String(d))} className={`rounded-full border px-3 py-1 text-[12px] font-semibold ${Number(days) === d ? "border-corona/40 bg-corona/10 text-corona" : "border-line text-muted hover:text-ink"}`}>{d} يوم</button>)}
                </div>
              </div>
            )}

            <label className="block"><span className={label}>ملاحظة لنفسك (اختياري)</span>
              <input value={note} onChange={e => setNote(e.target.value)} maxLength={200} placeholder="مثلا: صديق، مؤثر، عميل قديم" className={field}/>
            </label>

            <label className={`flex items-start gap-2.5 rounded-xl border border-line bg-surface2 px-3.5 py-3 ${emailConfigured ? "cursor-pointer" : "opacity-70"}`}>
              <input type="checkbox" checked={sendEmail} disabled={!emailConfigured} onChange={e => setSendEmail(e.target.checked)} className="mt-1 accent-corona"/>
              <span><span className="flex items-center gap-1.5 text-[14px] font-semibold"><Mail size={15}/>ابعت الدعوة على الإيميل</span>
                <span className="block text-[12px] text-muted">{emailConfigured ? "هيوصله إيميل فيه العرض وزرار يفتح الدعوة" : "إرسال الإيميل مش متظبط على السيرفر (RESEND_API_KEY) — هتاخد رابط تنسخه وتبعته بنفسك"}</span></span>
            </label>

            <div className="rounded-xl bg-surface2 px-3.5 py-3 text-[13px]"><span className="text-muted">هيوصله: </span><b>{offer}</b></div>
            {err && <div className="rounded-xl border border-loss/30 bg-loss/10 px-3.5 py-2.5 text-[13px] text-loss">{err}</div>}
            <div className="flex gap-2">
              <button onClick={submit} disabled={!valid || busy} className={`${btn.primary} flex-1`}>{busy ? "بيبعت…" : sendEmail ? "ابعت الدعوة" : "اعمل الدعوة"}</button>
              <button onClick={onClose} className={btn.secondary}>إلغاء</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export type InvitesData = { email_configured: boolean, invites: any[], grants: any[] }

/** The invitations list and the active gifts, with their actions. */
export function InvitesPanelView({ data, prices, onInvite, onAction, busy }: {
  data: InvitesData | null, prices: Record<string, number>, onInvite: () => void, onAction: (path: string, msg: string) => void, busy: boolean,
}){
  const gifts = (data?.grants || []).filter(g => g.active)
  return (
    <Card>
      <CardHeader title="الدعوات" sub={data ? (data.email_configured ? "الإيميلات بتتبعت من السيرفر" : "إرسال الإيميل مش متظبط — الدعوات بتتعمل وبتنسخ رابطها") : "بيحمّل…"}
        action={<button onClick={onInvite} className={btn.primary}><Mail size={16}/>ادعُ مستخدم</button>} />
      {gifts.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {gifts.map(g => (
            <span key={g.user_id} className="inline-flex items-center gap-2 rounded-xl border border-signal/30 bg-signal/10 py-1 pl-1 pr-3 text-[13px]">
              <Gift size={14} className="text-signal"/><span dir="ltr">{g.email}</span><b>{NAME[g.tier]}</b><span className="text-muted">· فاضل {daysLeft(g.expires_at)} يوم</span>
              <button disabled={busy} onClick={() => onAction(`/api/admin/grants/${g.user_id}/end`, `تنهي هدية ${g.email} دلوقتي؟`)} className="rounded-lg px-2 py-0.5 text-[12px] text-loss hover:bg-loss/10">إنهاء</button>
            </span>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] text-[13px]">
          <thead><tr>{["الإيميل", "العرض", "الحالة", "اتبعتت", "الرابط لحد", ""].map((h, i) => <th key={i} className="whitespace-nowrap px-2 py-2 text-right text-[12px] font-semibold text-faint">{h}</th>)}</tr></thead>
          <tbody>
            {(data?.invites || []).map(inv => {
              const [st, tone] = STATE[inv.state] || [inv.state, "neutral" as Tone]
              const live = inv.state === "pending"
              return (
                <tr key={inv.id} className="border-t border-line">
                  <td className="px-2 py-3"><div className="font-semibold" dir="ltr" style={{ textAlign: "right" }}>{inv.email}</div>{inv.note && <div className="text-[12px] text-faint">{inv.note}</div>}</td>
                  <td className="px-2 py-3"><Pill tone={inv.kind === "gift" ? "signal" : inv.kind === "trial" ? "umbra" : "corona"}>{KIND[inv.kind]?.title}</Pill><div className="mt-1 text-[12px] text-muted">{inv.offer}</div></td>
                  <td className="px-2 py-3"><Pill tone={tone}>{st}</Pill>{inv.opened_checkout_at && inv.state === "pending" && <div className="mt-1 text-[11px] text-faint">فتح صفحة الدفع</div>}</td>
                  <td className="px-2 py-3 text-muted">{inv.emailed_at ? fmtDate(inv.emailed_at) : <span className="text-faint" title={inv.email_error || ""}>رابط بس</span>}</td>
                  <td className="px-2 py-3 text-muted">{live ? fmtDate(inv.link_expires_at) : "—"}</td>
                  <td className="px-2 py-3">
                    {live && <div className="flex justify-end gap-1.5">
                      <CopyLink link={inv.link} compact/>
                      {data?.email_configured && <button disabled={busy} onClick={() => onAction(`/api/admin/invites/${inv.id}/resend`, `تبعت الدعوة تاني لـ ${inv.email}؟ (الرابط هيشتغل 14 يوم من النهارده)`)} className="rounded-lg border border-line bg-surface2 px-2.5 py-1 text-[12px] font-semibold text-muted hover:text-ink">ابعت تاني</button>}
                      <button disabled={busy} onClick={() => onAction(`/api/admin/invites/${inv.id}/revoke`, `تلغي دعوة ${inv.email}؟ الرابط هيبطل يشتغل.`)} className="rounded-lg border border-line bg-surface2 px-2.5 py-1 text-[12px] font-semibold text-loss hover:border-loss/40">الغِ</button>
                    </div>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {data && !data.invites.length && <div className="rounded-[10px] border border-dashed border-line p-6 text-center text-[13px] text-faint">مفيش دعوات لسه. اضغط "ادعُ مستخدم".</div>}
      <p className="mt-3 text-[12px] text-faint">الهدية بتشتغل فوق الباقة المدفوعة (الأعلى هي اللي بتتحسب) وبتقف لوحدها في ميعادها. التجربة والدفع بيتموا على Stripe بالسعر الحالي.</p>
    </Card>
  )
}

/** Invitations with their data. `prices` = the plans' current prices (from the finance endpoint). */
export function AdminInvites({ prices }: { prices: Record<string, number> }){
  const [data, setData] = useState<InvitesData | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const load = useCallback(async () => { try { setData(await call("/api/admin/invites")); setErr("") } catch (e: any) { setErr(e.message) } }, [])
  useEffect(() => { load() }, [load])
  async function act(path: string, msg: string){
    if (!confirm(msg)) return
    setBusy(true)
    try { const j = await call(path, "POST", { confirm: true }); if (j.emailed === false) setErr(`ما اتبعتش: ${j.email_error || ""}`); await load() }
    catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  return <>
    {err && <div className="rounded-xl border border-loss/30 bg-loss/10 px-3.5 py-2.5 text-[13px] text-loss">{err}</div>}
    <InvitesPanelView data={data} prices={prices} onInvite={() => setOpen(true)} onAction={act} busy={busy}/>
    <InviteDialog open={open} onClose={() => setOpen(false)} prices={prices} emailConfigured={!!data?.email_configured} onCreated={load}/>
  </>
}

/** The paid plans' monthly prices: the admin edits them; new checkouts charge the new price. */
export function PlanPrices({ onSaved }: { onSaved?: () => void }){
  const [plans, setPlans] = useState<{ prices: Record<string, number>, defaults: Record<string, number>, changed: Record<string, any> } | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const load = useCallback(async () => {
    try { const j = await call("/api/admin/plans"); setPlans(j); setDraft(Object.fromEntries(PAID.map(t => [t, String(j.prices[t])]))) }
    catch (e: any) { setMsg(`⚠️ ${e.message}`) }
  }, [])
  useEffect(() => { load() }, [load])
  const changed = plans ? PAID.filter(t => Number(draft[t]) !== plans.prices[t]) : []
  const valid = changed.every(t => Number.isInteger(Number(draft[t])) && Number(draft[t]) >= 1 && Number(draft[t]) <= 10000)
  async function save(){
    if (!plans) return
    const patch = Object.fromEntries(changed.map(t => [t, Number(draft[t])]))
    if (!confirm(`الأسعار الجديدة:\n${changed.map(t => `${NAME[t]}: $${plans.prices[t]} ← $${patch[t]}`).join("\n")}\n\nالمشتركين الجداد بس هيدفعوا السعر الجديد، والمشتركين الحاليين بيكملوا بسعرهم.`)) return
    setBusy(true); setMsg("")
    try { await call("/api/admin/plans", "POST", { prices: patch, confirm: true }); setMsg("✅ اتحفظ"); await load(); onSaved?.() }
    catch (e: any) { setMsg(`⚠️ ${e.message}`) } finally { setBusy(false) }
  }
  return (
    <Card>
      <CardHeader title="أسعار الباقات" sub="بالدولار في الشهر · السعر الجديد للمشتركين الجداد، والحاليين بيكملوا بسعرهم على Stripe"
        action={<>{msg && <span className="text-[12px] text-muted">{msg}</span>}<button onClick={save} disabled={!changed.length || !valid || busy} className={btn.primary}>{busy ? "بيحفظ…" : "احفظ الأسعار"}</button></>} />
      <div className="grid gap-3 sm:grid-cols-3">
        {PAID.map(t => (
          <label key={t} className={`rounded-[12px] border p-4 ${changed.includes(t as any) ? "border-corona/50 bg-corona/5" : "border-line bg-surface2"}`}>
            <div className="mb-2 flex items-center justify-between gap-2"><b className="text-[15px]">{NAME[t]}</b>
              {plans && plans.prices[t] !== plans.defaults[t] && <span className="text-[11px] text-faint">الأصلي ${plans.defaults[t]}</span>}</div>
            <div className="relative"><span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 font-mono text-muted">$</span>
              <input value={draft[t] ?? ""} onChange={e => setDraft(d => ({ ...d, [t]: e.target.value }))} type="number" min={1} max={10000} dir="ltr" disabled={!plans} className={`${field} pl-7 font-mono text-[18px] font-bold`}/></div>
            {plans?.changed?.[t] && <div className="mt-2 text-[11px] text-faint">آخر تعديل {fmtDate(plans.changed[t].updated_at)}</div>}
          </label>
        ))}
      </div>
    </Card>
  )
}

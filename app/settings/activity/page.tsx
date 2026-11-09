"use client"
import { useEffect, useState } from "react"
import { AppShell } from "@/components/AppShell"
import { signOutEverywhere } from "@/components/AccountMenu"
import { Card, CardHeader, PageHeader, Pill, type Tone } from "@/components/ui"
import { apiUserActivity, type ActivityItem } from "@/lib/api"
import { getUser } from "@/lib/supabase"

/**
 * Account activity (security plan item 10, owner 2026-11-08): every sign-in session the server saw (when, the device,
 * the IP) and every sensitive change, the account's own only. Something here that wasn't you = sign out everywhere,
 * then change the password (docs/security-runbook.md).
 */
const KIND: Record<ActivityItem["kind"], { label: string, tone: Tone }> = {
  session: { label: "دخول", tone: "signal" },
  account: { label: "تغيير", tone: "neutral" },
  real_money: { label: "فلوس حقيقية", tone: "corona" },
  admin: { label: "أدمن", tone: "umbra" },
}

function when(iso: string){
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString("ar-EG", { dateStyle: "medium", timeStyle: "short" })
}

export default function ActivityPage(){
  const [data, setData] = useState<{ items: ActivityItem[], keep_days: number } | null | undefined>(undefined)
  const [signedIn, setSignedIn] = useState<boolean | null>(null)
  useEffect(() => {
    let live = true
    getUser().then(u => { if (!live) return; setSignedIn(!!u); if (u) apiUserActivity().then(d => { if (live) setData(d) }) })
      .catch(() => { if (live) setSignedIn(false) })
    return () => { live = false }
  }, [])

  return (
    <AppShell active="/settings/activity">
      <PageHeader title="نشاط الحساب" subtitle="كل دخول لحسابك وكل تغيير مهم عليه"/>
      <Card className="mt-6">
        <CardHeader title="فيه حاجة ماعملتهاش؟"
          action={<button onClick={signOutEverywhere} data-testid="activity-sign-out-everywhere"
            className="rounded-[10px] border border-loss/40 bg-loss/10 px-3 py-1.5 text-[13px] font-semibold text-loss transition hover:bg-loss/20">اخرج من كل الأجهزة</button>}/>
        <p className="text-[13px] leading-6 text-muted">
          لو شايف دخول من جهاز أو مكان مش بتاعك، أو تغيير انت ماعملتوش: اضغط "اخرج من كل الأجهزة"، وبعدها غيّر الباسورد واتأكد إن الـ 2FA لسه على موبايلك.
        </p>
      </Card>
      <Card className="mt-4">
        <CardHeader title="آخر النشاط" sub={data ? `آخر ${data.keep_days} يوم · الأحدث فوق` : undefined}/>
        {signedIn === false && <p className="text-[14px] text-muted">سجّل دخول علشان تشوف نشاط حسابك.</p>}
        {signedIn !== false && data === undefined && <p className="text-[14px] text-muted">بيحمّل…</p>}
        {signedIn && data === null && <p className="text-[14px] text-loss">مقدرناش نجيب النشاط دلوقتي. جرّب تاني بعد شوية.</p>}
        {data && data.items.length === 0 && <p className="text-[14px] text-muted">لسه مفيش نشاط متسجل.</p>}
        {data && data.items.length > 0 && (
          <ul data-testid="activity-list" className="divide-y divide-line">
            {data.items.map((i, n) => (
              <li key={n} data-testid="activity-item" className="flex flex-wrap items-start gap-x-3 gap-y-1 py-3">
                <Pill tone={KIND[i.kind]?.tone ?? "neutral"}>{KIND[i.kind]?.label ?? i.kind}</Pill>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-semibold text-ink">{i.what}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-muted">
                    <span>{when(i.at)}</span>
                    {i.device && <span>{i.device}</span>}
                    {i.ip && <span dir="ltr" className="font-mono">{i.ip}</span>}
                  </div>
                  {i.details && Object.keys(i.details).length > 0 && (
                    <div dir="ltr" className="mt-1 break-all text-start font-mono text-[11px] text-faint">
                      {Object.entries(i.details).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ")}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </AppShell>
  )
}

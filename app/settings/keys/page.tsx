"use client"
import { AppShell } from "@/components/AppShell"
import { Card, PageHeader } from "@/components/ui"

/**
 * Removed from the menus on 2026-11-04. Its keys went to the admin vault for the dashboard's old engine, which only
 * trades paper (bot_loop refuses real orders) — so nothing ever used them, and a third place for keys confused the
 * owner. Users' Demo keys are on /settings/live; the real bot's key is a file on the server only (.env.real).
 * The API's /api/keys/* endpoints and keys_vault were removed with it (development-plan 3.2).
 */
export default function KeysMoved(){
  return (
    <AppShell active="/settings/keys">
      <PageHeader title="مفاتيح المنصات" subtitle="الصفحة دي اتشالت"/>
      <Card>
        <div className="space-y-3 text-[14px] leading-7 text-muted">
          <p>المفاتيح اللي كانت بتتحفظ هنا ماكانش في أي بوت بيستخدمها، فالصفحة اتشالت علشان ماتتلخبطش بين أماكن المفاتيح.</p>
          <ul className="list-inside list-disc space-y-1">
            <li><b className="text-ink">مفاتيح Binance Demo بتاعتك</b> (بوتاتك بفلوس وهمية): في <a href="/settings/live" className="font-semibold text-corona">بوتاتي على Binance (Demo)</a>.</li>
            <li><b className="text-ink">البوت الحقيقي</b>: مفتاحه متحطوط على السيرفر بس، ومابيعديش على الموقع.</li>
          </ul>
        </div>
      </Card>
    </AppShell>
  )
}

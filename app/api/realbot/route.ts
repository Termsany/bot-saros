import { NextResponse } from "next/server"

// The real-money bots' public file (scripts/realbot_export.py → https://realbot.da3m.io/live.json): already filtered
// to what that public page shows. Read here, on the server, so the dashboard needs no CORS on realbot.da3m.io.
const SRC = "https://realbot.da3m.io/live.json"

export const dynamic = "force-dynamic"

export async function GET(){
  try {
    const r = await fetch(SRC, { cache: "no-store", signal: AbortSignal.timeout(8000) })
    if(!r.ok) throw new Error(String(r.status))
    const doc = await r.json()
    if(!doc || !Array.isArray(doc.bots)) throw new Error("bad file")
    return NextResponse.json(doc, { headers: { "Cache-Control": "no-store" } })
  } catch {
    return NextResponse.json({ error: "unavailable" }, { status: 502, headers: { "Cache-Control": "no-store" } })
  }
}

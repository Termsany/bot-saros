import { NextRequest, NextResponse } from "next/server"
import { readFile } from "fs/promises"
import path from "path"
const BOT_DIR = "C:/Users/User/AppData/Local/hermes/cache/scratch/crypto-bot"
export async function GET(req: NextRequest) {
  const file = req.nextUrl.searchParams.get("file") || ""
  if (!file.match(/^backtest_.*\.(png|json)$/)) return new NextResponse("bad file", { status: 400 })
  const p = path.join(BOT_DIR, file)
  try {
    const buf = await readFile(p)
    const ct = file.endsWith(".png") ? "image/png" : "application/json"
    return new NextResponse(buf, { headers: { "Content-Type": ct, "Cache-Control": "no-store" } })
  } catch { return new NextResponse("not found", { status: 404 }) }
}

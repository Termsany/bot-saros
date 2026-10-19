import { NextRequest, NextResponse } from "next/server"
import { spawn } from "child_process"
import { readFile } from "fs/promises"
import { existsSync } from "fs"
import path from "path"

export const maxDuration = 120
const BOT_DIR = "C:/Users/User/AppData/Local/hermes/cache/scratch/crypto-bot"
const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

async function tryBackend(body: any): Promise<any | null> {
  try {
    const r = await fetch(`${BACKEND}/api/backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (r.ok) return await r.json()
  } catch {}
  return null
}

function runLocal(args: string[]): Promise<{ stdout: string; stderr: string; code: number | null }> {
  return new Promise((resolve) => {
    const py = spawn("python", [path.join(BOT_DIR, "backtest.py"), ...args], { cwd: BOT_DIR })
    let stdout = "", stderr = ""
    py.stdout.on("data", (d) => (stdout += d.toString()))
    py.stderr.on("data", (d) => (stderr += d.toString()))
    const timer = setTimeout(() => { try { py.kill() } catch {} }, 110000)
    py.on("close", (code) => { clearTimeout(timer); resolve({ stdout, stderr, code }) })
    py.on("error", (err) => { clearTimeout(timer); resolve({ stdout, stderr: stderr + String(err), code: 1 }) })
  })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  // Try FastAPI first (DB + OCO + Telegram)
  const viaBackend = await tryBackend(body)
  if (viaBackend) return NextResponse.json(viaBackend)

  // Fallback local (old behavior)
  const symbol: string = body.symbol || "BTC/USDT"
  const timeframe: string = body.timeframe || "1h"
  const limit: number = Math.min(2000, Math.max(50, parseInt(String(body.limit ?? 500))))
  const strategies: string[] | null = body.strategies?.length ? body.strategies : null
  const amount = parseFloat(body.amount) || 20
  const leverage = parseInt(body.leverage) || 5
  const from = body.from as string | undefined
  const to = body.to as string | undefined

  const args = ["--symbol", symbol, "--timeframe", timeframe, "--amount", String(amount), "--leverage", String(leverage)]
  if (from) args.push("--from", from)
  if (to) args.push("--to", to)
  if (!from && !to) args.push("--limit", String(limit))
  if (strategies && strategies.length) args.push("--strategies", strategies.join(","))
  const { stdout, stderr, code } = await runLocal(args)
  const symFile = symbol.replace("/","")
  const jsonPath = path.join(BOT_DIR, `backtest_${symFile}_${timeframe}.json`)
  let data: any = null
  if (existsSync(jsonPath)) { try { data = JSON.parse(await readFile(jsonPath, "utf-8")) } catch {} }
  return NextResponse.json({ ok: code===0, code, stdout: stdout.slice(-8000), stderr: stderr.slice(-2000), data, chart: `backtest_${symFile}_${timeframe}.png` })
}

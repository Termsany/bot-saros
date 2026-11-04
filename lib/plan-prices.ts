const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

/** The plans' current prices (the admin can change them), or none so the pricing shows its defaults. */
export async function planPrices(): Promise<Record<string, number> | undefined>{
  try{
    const r = await fetch(`${API}/api/plans`, { next: { revalidate: 300 }, signal: AbortSignal.timeout(4000) })
    return r.ok ? (await r.json()).prices : undefined
  }catch{ return undefined }
}

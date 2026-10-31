import { createClient } from "@supabase/supabase-js"

export const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ""
export const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ""
export const isSupabaseConfigured = !!supabaseUrl && !!supabaseAnonKey

export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey)
  : null as any

export async function getUser(){
  if (!supabase) return null
  const { data } = await supabase.auth.getUser()
  return data.user
}

/** Headers for calls to the FastAPI backend — carries the Supabase session token. */
export async function authHeaders(extra: Record<string,string> = {}): Promise<Record<string,string>>{
  const h: Record<string,string> = { ...extra }
  if (supabase){
    const { data } = await supabase.auth.getSession()
    const token = data.session?.access_token
    if (token) h.Authorization = `Bearer ${token}`
  }
  return h
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
export type MyPlan = { tier: string, gift: { tier: string, expires_at: string } | null }

/** The plan the backend enforces (paid or an admin's gift, the higher; admins count as elite), with the gift if one
 *  is running. Falls back to the profile row when the backend can't be reached. */
export async function getMyPlan(): Promise<MyPlan>{
  const h = await authHeaders()
  if (h.Authorization){
    try{
      const r = await fetch(`${API}/api/user/tier`, { headers: h, cache: "no-store" })
      if (r.ok){ const j = await r.json(); return { tier: j.tier || "free", gift: j.gift || null } }
    }catch{ /* fall back */ }
  }
  return { tier: await profileTier(), gift: null }
}

export async function getMyTier(): Promise<string>{
  return (await getMyPlan()).tier
}

/** Tier from the user's profile row (server data) — never from UI state. */
async function profileTier(): Promise<string>{
  if (!supabase) return "free"
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return "free"
  const { data } = await supabase.from("profiles").select("tier").eq("id", user.id).maybeSingle()
  return data?.tier || "free"
}

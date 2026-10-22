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

/** Tier from the user's profile row (server data) — never from UI state. */
export async function getMyTier(): Promise<string>{
  if (!supabase) return "free"
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return "free"
  const { data } = await supabase.from("profiles").select("tier,tier_expires_at").eq("id", user.id).maybeSingle()
  if(data?.tier_expires_at && Date.parse(data.tier_expires_at) <= Date.now()) return "free"
  return data?.tier || "free"
}

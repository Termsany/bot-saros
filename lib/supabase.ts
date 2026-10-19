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

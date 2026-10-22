import { createClient } from "@supabase/supabase-js"

const url = process.env.NEXT_PUBLIC_SUPABASE_URL || ""
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ""
const service = process.env.SUPABASE_SERVICE_KEY || ""

export function adminClient(){
  if(!url || !service) throw new Error("database not configured")
  return createClient(url, service, { auth: { persistSession: false, autoRefreshToken: false } })
}

export async function authenticatedUser(req: Request){
  const token = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
  if(!token || !url || !anon) return null
  const { data: { user } } = await createClient(url, anon, { auth: { persistSession: false, autoRefreshToken: false } }).auth.getUser(token)
  return user
}

export async function requireAdmin(req: Request){
  const user = await authenticatedUser(req)
  const admins = new Set((process.env.ADMIN_EMAILS || "").split(",").map(x=>x.trim().toLowerCase()).filter(Boolean))
  if(!user || !user.email || !user.email_confirmed_at || !admins.has(user.email.toLowerCase())) return null
  return user
}

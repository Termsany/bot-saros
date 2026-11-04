import { NextResponse, type NextRequest } from "next/server"

// The page's language for the root layout's <html lang dir> (and the client components, through LocaleProvider):
// - the landing pages are their own language — / English, /ar Arabic — and remember it in the raqm-lang cookie;
// - the pages already built in both languages (BILINGUAL) follow that cookie, Arabic when there is none;
// - every other page is Arabic.
const BILINGUAL = ["/dashboard", "/backtest", "/settings/live"]
const COOKIE = "raqm-lang"

export function middleware(req: NextRequest){
  const path = req.nextUrl.pathname
  const saved = req.cookies.get(COOKIE)?.value === "en" ? "en" : "ar"
  const landing = path === "/" ? "en" : path === "/ar" ? "ar" : null
  const locale = landing ?? (BILINGUAL.some(p => path === p || path.startsWith(p + "/")) ? saved : "ar")
  const headers = new Headers(req.headers)
  headers.set("x-raqm-locale", locale)
  const res = NextResponse.next({ request: { headers } })
  if (landing && req.cookies.get(COOKIE)?.value !== landing) res.cookies.set(COOKIE, landing, { path: "/", maxAge: 31536000, sameSite: "lax" })
  return res
}

// Only the pages with a language to choose: every other page renders Arabic without the header (app/layout.tsx).
// (A catch-all pattern lost its "\\." escape on the way and silently skipped /dashboard and /ar — keep it a list.)
export const config = { matcher: ["/", "/ar", "/dashboard", "/dashboard/:path*", "/backtest", "/settings/live"] }

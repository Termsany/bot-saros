import { NextResponse, type NextRequest } from "next/server"

// The page's language for the root layout's <html lang dir>: English on the landing page (/), Arabic everywhere else
// (/ar and the app). Only a request header the layout reads — no redirect, no cookie.
export function middleware(req: NextRequest){
  const headers = new Headers(req.headers)
  headers.set("x-raqm-locale", req.nextUrl.pathname === "/" ? "en" : "ar")
  return NextResponse.next({ request: { headers } })
}

export const config = { matcher: ["/((?!_next/|api/|favicon|icon|.*\.[a-z0-9]+$).*)"] }

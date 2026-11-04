// The real-money bots' public page (deploy/vps/realbot/index.html). A plain module, not a client one,
// so the server-rendered landing can call realPage() too.
import type { Locale } from "@/lib/i18n/landing"

export const REAL_PAGE = "https://realbot.da3m.io"
/** The real-money page in the reader's language (the page reads ?lang=). */
export const realPage = (l: Locale) => `${REAL_PAGE}/?lang=${l}`

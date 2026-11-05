import { localeTitle } from "@/lib/page-meta"

export const generateMetadata = localeTitle({ en: "My Binance Demo bots", ar: "بوتاتي على Binance (Demo)" })
export default function Layout({ children }: { children: React.ReactNode }){ return <>{children}</> }

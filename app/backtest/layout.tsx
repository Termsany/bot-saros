import { localeTitle } from "@/lib/page-meta"

export const generateMetadata = localeTitle({ en: "Backtest", ar: "Backtest" })
export default function Layout({ children }: { children: React.ReactNode }){ return <>{children}</> }

import { localeTitle } from "@/lib/page-meta"

export const generateMetadata = localeTitle({ en: "Dashboard", ar: "لوحة التحكم" })
export default function Layout({ children }: { children: React.ReactNode }){ return <>{children}</> }

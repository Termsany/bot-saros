import { localeTitle } from "@/lib/page-meta"

export const generateMetadata = localeTitle({ en: "Account activity", ar: "نشاط الحساب" })
export default function Layout({ children }: { children: React.ReactNode }){ return <>{children}</> }

import { localeTitle } from "@/lib/page-meta"

export const generateMetadata = localeTitle({ en: "Monthly statement", ar: "كشف الحساب الشهري" })
export default function Layout({ children }: { children: React.ReactNode }){ return <>{children}</> }

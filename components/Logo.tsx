"use client"
import { BRAND } from "@/lib/brand"

/** Raqm mark: gold coin rim + three rising bars (a digital coin that grows) + flare on the rim.
 *  Same geometry as "Raqm Mark" in the Figma brand file. */
export function RaqmMark({ size = 36, className = "" }: { size?: number, className?: string }){
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" className={className} aria-hidden="true">
      <circle cx="32" cy="32" r="27" stroke="#F5B841" strokeWidth="3"/>
      <circle cx="32" cy="32" r="21" stroke="#F5B841" strokeWidth="1" strokeOpacity="0.35"/>
      <rect x="20" y="34" width="6.5" height="10" rx="1.6" fill="#F5B841"/>
      <rect x="28.75" y="27" width="6.5" height="17" rx="1.6" fill="#F5B841"/>
      <rect x="37.5" y="20" width="6.5" height="24" rx="1.6" fill="#FFE1A1"/>
      <circle cx="51.1" cy="12.9" r="3.4" fill="#FFE1A1"/>
    </svg>
  )
}

export function Logo({ size="md", showText=true }: { size?: "sm"|"md"|"lg", showText?: boolean }){
  const mark = { sm: 30, md: 36, lg: 44 }[size]
  const textSize = { sm: "text-[15px]", md: "text-lg", lg: "text-[22px]" }[size]
  return (
    <div className="flex items-center gap-3" dir="ltr">
      <RaqmMark size={mark}/>
      {showText && (
        <div>
          <div className={`${textSize} font-display font-bold tracking-[0.28em] leading-none text-ink`}>{BRAND.nameCaps}</div>
          <div className="font-mono text-[9px] tracking-[0.24em] text-muted leading-none mt-1.5">{BRAND.subtitle}</div>
        </div>
      )}
    </div>
  )
}

export function LogoIcon({ size=32 }: { size?: number }){
  return <RaqmMark size={size}/>
}

"use client"
import { Activity } from "lucide-react"

export function Logo({ size="md", showText=true }: { size?: "sm"|"md"|"lg", showText?: boolean }){
  const dims = { sm: "h-8 w-8", md: "h-9 w-9", lg: "h-11 w-11" }[size]
  const textSize = { sm: "text-sm", md: "text-[15px]", lg: "text-lg" }[size]
  return (
    <div className="flex items-center gap-3">
      <div className={`${dims} relative grid place-items-center rounded-lg overflow-hidden bg-[#00D395]/10 border border-[#00D395]/20`}>
        {/* Diamond + chart S */}
        <svg viewBox="0 0 32 32" className="h-[70%] w-[70%]">
          {/* hexagon frame */}
          <path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z" fill="none" stroke="#00D395" strokeWidth="1.4" opacity="0.9"/>
          {/* inner chart line forming S / wave */}
          <path d="M7 20 L11 20 L13 12 L17 20 L19 14 L25 14" fill="none" stroke="#00D395" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>
          {/* dots */}
          <circle cx="7" cy="20" r="1.2" fill="#00D395"/>
          <circle cx="25" cy="14" r="1.2" fill="#00D395"/>
          {/* tiny crimson dot for SHORT accent */}
          <circle cx="13" cy="12" r="1" fill="#FF3B5C" opacity="0.9"/>
        </svg>
      </div>
      {showText && (
        <div>
          <div className={`${textSize} font-black tracking-[0.18em] leading-none text-white`}>BOT SAROS</div>
          <div className="font-mono text-[9px] tracking-[0.2em] text-[#647386] leading-none mt-1">AUTONOMOUS TRADING TERMINAL</div>
        </div>
      )}
    </div>
  )
}

export function LogoIcon({ size=32 }: { size?: number }){
  return (
    <div style={{width:size, height:size}} className="grid place-items-center rounded-lg bg-[#00D395]/10 border border-[#00D395]/20">
      <svg viewBox="0 0 32 32" className="h-[68%] w-[68%]">
        <path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z" fill="none" stroke="#00D395" strokeWidth="1.4"/>
        <path d="M7 20 L11 20 L13 12 L17 20 L19 14 L25 14" fill="none" stroke="#00D395" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>
        <circle cx="7" cy="20" r="1.2" fill="#00D395"/>
        <circle cx="25" cy="14" r="1.2" fill="#00D395"/>
        <circle cx="13" cy="12" r="1" fill="#FF3B5C"/>
      </svg>
    </div>
  )
}

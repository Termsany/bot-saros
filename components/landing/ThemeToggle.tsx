"use client"
import { useEffect, useState } from "react"
import { Moon, Sun } from "lucide-react"
import { LANDING, type Locale } from "@/lib/i18n/landing"

const KEY = "raqm-theme"

/** Runs before the page paints (inline in <head>): the visitor's last choice, else their system's. Never throws. */
export const THEME_INIT = `try{var t=localStorage.getItem("${KEY}");if(!t)t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";document.documentElement.dataset.theme=t}catch(e){}`

/** Dark / light switch for the landing pages. The colours are CSS variables (app/globals.css), so it only flips an attribute. */
export function ThemeToggle({ locale }: { locale: Locale }){
  const [theme, setTheme] = useState<"dark" | "light">("dark")
  useEffect(() => {
    // THEME_INIT set the attribute before the first paint, but React can drop it when it takes over <html>
    // (the server's <html> has no data-theme): put the saved / system choice back if it went missing.
    const el = document.documentElement
    if (!el.dataset.theme) {
      let saved: string | null = null
      try { saved = localStorage.getItem(KEY) } catch {}
      el.dataset.theme = saved === "light" || saved === "dark" ? saved : matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"
    }
    setTheme(el.dataset.theme === "light" ? "light" : "dark")
  }, [])
  const t = LANDING[locale].theme
  const next = theme === "dark" ? "light" : "dark"
  function flip(){
    document.documentElement.dataset.theme = next; setTheme(next)
    try { localStorage.setItem(KEY, next) } catch {}
  }
  return (
    <button type="button" onClick={flip} aria-label={next === "light" ? t.toLight : t.toDark} title={next === "light" ? t.toLight : t.toDark}
      className="grid h-9 w-9 place-items-center rounded-[10px] border border-line bg-surface2 text-corona transition hover:border-line2 hover:bg-surface">
      {theme === "dark" ? <Moon size={17} strokeWidth={2}/> : <Sun size={17} strokeWidth={2}/>}
    </button>
  )
}

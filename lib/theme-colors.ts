"use client"
// The theme's colours as plain CSS colours, for drawing code that can't use classes (recharts, canvas): read from the
// CSS variables (app/globals.css) and read again when the theme switch flips <html data-theme>.
import { useEffect, useState } from "react"

const NAMES = ["profit", "loss", "corona", "line", "faint", "ink", "surface2", "muted"] as const
export type ThemeColors = Record<(typeof NAMES)[number], string>

const DARK: ThemeColors = { profit: "rgb(34 211 160)", loss: "rgb(255 84 112)", corona: "rgb(245 184 65)", line: "rgb(35 40 56)",
  faint: "rgb(93 99 120)", ink: "rgb(242 243 247)", surface2: "rgb(22 26 37)", muted: "rgb(139 145 167)" }

function read(): ThemeColors {
  const css = getComputedStyle(document.documentElement)
  const out = { ...DARK }
  for (const n of NAMES) { const v = css.getPropertyValue(`--c-${n}`).trim(); if (v) out[n] = `rgb(${v})` }
  return out
}

export function useThemeColors(): ThemeColors {
  const [c, setC] = useState<ThemeColors>(DARK)
  useEffect(() => {
    setC(read())
    const obs = new MutationObserver(() => setC(read()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] })
    return () => obs.disconnect()
  }, [])
  return c
}

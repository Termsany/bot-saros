/** @type {import('tailwindcss').Config} */
// Raqm identity — the tokens of the Figma file "RAQM — Global Redesign 2026" (Color collection, modes Dark + Light).
// Each colour is a CSS variable holding "R G B" (app/globals.css): dark by default, light under [data-theme="light"],
// so `bg-corona/10`-style opacity still works. Brand accent is corona (gold); profit/loss only for gains, losses,
// LONG/SHORT.
const v = name => `rgb(var(--c-${name}) / <alpha-value>)`

module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        void: v("void"),         // page background
        surface: v("surface"),   // cards
        surface2: v("surface2"), // inner elements, inputs, hover
        line: v("line"),         // borders, dividers
        line2: v("line2"),       // stronger border
        ink: v("ink"),           // primary text
        muted: v("muted"),       // secondary text
        faint: v("faint"),       // tertiary text, captions
        corona: { DEFAULT: v("corona"), soft: v("corona-soft"), deep: v("corona-deep") },  // brand
        "on-corona": v("on-corona"),
        umbra: v("umbra"),       // AI / secondary accent
        profit: v("profit"),
        loss: v("loss"),
        signal: v("signal"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        "fade-up": { "0%": { opacity: "0", transform: "translateY(14px)" }, "100%": { opacity: "1", transform: "none" } },
      },
      animation: { "fade-up": "fade-up .7s cubic-bezier(.2,.7,.2,1) both" },
    },
  },
  plugins: [],
}

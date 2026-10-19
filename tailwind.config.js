/** @type {import('tailwindcss').Config} */
// Raqm identity — same tokens as the Figma file "Raqm / Color".
// Brand accent is corona (gold); profit/loss are only for gains, losses, LONG/SHORT.
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#07080D",       // page background
        surface: "#0F1118",    // cards
        surface2: "#161A25",   // inner elements, inputs, hover
        line: "#232838",       // borders, dividers
        ink: "#F2F3F7",        // primary text
        muted: "#8B91A7",      // secondary text
        faint: "#5D6378",      // tertiary text, captions
        corona: { DEFAULT: "#F5B841", soft: "#FFE1A1", deep: "#D99A1E" },  // brand
        umbra: "#7B61FF",      // AI / secondary accent
        profit: "#22D3A0",
        loss: "#FF5470",
        signal: "#4CC9F0",
      },
      fontFamily: {
        sans: ["var(--font-cairo)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-cairo)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
}

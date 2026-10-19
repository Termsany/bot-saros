/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: { extend: { colors: { raqm: { bg: "#070B12", card: "#111827", border: "#1E2A3A", green: "#00D395", red: "#FF3B5C", yellow: "#FFB800", blue: "#60A5FA" } } } },
  plugins: [],
}

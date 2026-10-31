"use client"
import { Bell } from "lucide-react"

/** Shared pieces of the 2026-10 redesign (Figma "Raqm — App Redesign", page Foundations). */

export type Tone = "profit" | "loss" | "neutral" | "corona" | "signal" | "umbra"

const PILL: Record<Tone, string> = {
  profit: "border-profit/40 bg-profit/10 text-profit",
  loss: "border-loss/40 bg-loss/10 text-loss",
  neutral: "border-line bg-surface2 text-muted",
  corona: "border-corona/40 bg-corona/10 text-corona",
  signal: "border-signal/40 bg-signal/10 text-signal",
  umbra: "border-umbra/40 bg-umbra/10 text-umbra",
}
const DOT: Record<Tone, string> = { profit: "bg-profit", loss: "bg-loss", neutral: "bg-faint", corona: "bg-corona", signal: "bg-signal", umbra: "bg-umbra" }

export function Pill({ tone = "neutral", children, className = "" }: { tone?: Tone, children: React.ReactNode, className?: string }){
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-semibold leading-5 ${PILL[tone]} ${className}`}>{children}</span>
}

export function Dot({ tone = "neutral", pulse = false }: { tone?: Tone, pulse?: boolean }){
  return <i className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[tone]} ${pulse ? "animate-pulse" : ""}`}/>
}

export function Card({ children, className = "", id }: { children: React.ReactNode, className?: string, id?: string }){
  return <section id={id} className={`min-w-0 rounded-2xl border border-line bg-surface p-5 ${className}`}>{children}</section>
}

export function CardHeader({ title, sub, action }: { title: React.ReactNode, sub?: React.ReactNode, action?: React.ReactNode }){
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[17px] font-bold leading-snug">{title}</h2>
        {sub && <p className="mt-0.5 text-[12px] text-muted">{sub}</p>}
      </div>
      {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}

/** Page title (right) and status pills + alerts (left), the same on every signed-in page. */
export function PageHeader({ title, subtitle, status, alerts = true }: { title: React.ReactNode, subtitle?: React.ReactNode, status?: React.ReactNode, alerts?: boolean }){
  return (
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[28px] font-extrabold leading-tight sm:text-[32px]">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-muted">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {status}
        {alerts && <span className="grid h-9 w-9 place-items-center rounded-[10px] border border-line bg-surface text-muted" aria-hidden><Bell size={17} strokeWidth={1.8}/></span>}
      </div>
    </header>
  )
}

export function Toggle({ on, onChange, disabled, label }: { on: boolean, onChange?: (v: boolean) => void, disabled?: boolean, label: string }){
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange?.(!on)}
      className={`relative h-[22px] w-[38px] shrink-0 rounded-full transition disabled:opacity-40 ${on ? "bg-profit" : "bg-surface2 ring-1 ring-line"}`}>
      <span className={`absolute top-[3px] h-4 w-4 rounded-full transition-all ${on ? "left-[3px] bg-void" : "left-[19px] bg-faint"}`}/>
    </button>
  )
}

export const btn = {
  primary: "inline-flex items-center justify-center gap-2 rounded-xl bg-corona px-[18px] py-2.5 text-sm font-semibold text-void transition hover:bg-corona-soft disabled:opacity-40",
  secondary: "inline-flex items-center justify-center gap-2 rounded-xl border border-line bg-surface2 px-[18px] py-2.5 text-sm font-semibold text-ink transition hover:border-corona/40 disabled:opacity-40",
  ghost: "inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold text-muted transition hover:text-ink disabled:opacity-40",
}

export const field = "w-full rounded-xl border border-line bg-void px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-faint focus:border-corona/60"
export const label = "mb-1.5 block text-[12px] font-semibold text-muted"

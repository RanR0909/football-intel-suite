import { cn } from "@/lib/utils"

type PillVariant =
  | "purple" | "teal" | "amber" | "blue"
  | "pink" | "red" | "green" | "gray"

const STYLE: Record<PillVariant, string> = {
  purple: "bg-pill-purple-bg text-pill-purple-fg",
  teal:   "bg-pill-teal-bg   text-pill-teal-fg",
  amber:  "bg-pill-amber-bg  text-pill-amber-fg",
  blue:   "bg-pill-blue-bg   text-pill-blue-fg",
  pink:   "bg-pill-pink-bg   text-pill-pink-fg",
  red:    "bg-pill-red-bg    text-pill-red-fg",
  green:  "bg-pill-green-bg  text-pill-green-fg",
  gray:   "bg-pill-gray-bg   text-pill-gray-fg",
}

interface PillProps {
  variant?: PillVariant
  className?: string
  children: React.ReactNode
}

export default function Pill({ variant = "gray", className, children }: PillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-1.5 h-5 rounded text-2xs font-medium",
        STYLE[variant],
        className
      )}
    >
      {children}
    </span>
  )
}

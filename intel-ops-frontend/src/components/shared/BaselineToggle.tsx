import { cn } from "@/lib/utils"

interface BaselineToggleProps {
  show: boolean
  onChange: (v: boolean) => void
  className?: string
}

export default function BaselineToggle({ show, onChange, className }: BaselineToggleProps) {
  return (
    <label className={cn("inline-flex items-center gap-1.5 text-2xs cursor-pointer select-none", className)}>
      <input
        type="checkbox"
        checked={show}
        onChange={(e) => onChange(e.target.checked)}
        className="w-3 h-3 accent-brand-500 cursor-pointer"
      />
      <span className="text-muted-foreground">vs baseline 列</span>
    </label>
  )
}

import { cn } from "@/lib/utils"

export interface FilterChipOption {
  value: string
  label: string
  badge?: number
}

interface FilterChipsProps {
  label?: string
  options: FilterChipOption[]
  value: string
  onChange: (v: string) => void
  className?: string
}

/** 一组 single-select chips（按 spec §9.2 风格）*/
export default function FilterChips({
  label, options, value, onChange, className,
}: FilterChipsProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      {label && (
        <span className="text-2xs text-muted-foreground shrink-0">{label}：</span>
      )}
      <div className="flex flex-wrap gap-1">
        {options.map((opt) => {
          const active = opt.value === value
          return (
            <button
              key={opt.value}
              onClick={() => onChange(opt.value)}
              className={cn(
                "px-2 h-6 inline-flex items-center gap-1 rounded text-2xs transition-colors duration-150",
                active
                  ? "bg-foreground text-background font-medium"
                  : "bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {opt.label}
              {opt.badge != null && opt.badge > 0 && (
                <span className={cn(
                  "min-w-3.5 h-3.5 px-1 inline-flex items-center justify-center rounded text-2xs",
                  active ? "bg-background/20" : "bg-foreground/10"
                )}>
                  {opt.badge}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

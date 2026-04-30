import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 格式化 1234567 → "1.23M" */
export function formatCompactNumber(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "—"
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2).replace(/\.?0+$/, "") + "B"
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2).replace(/\.?0+$/, "") + "M"
  if (n >= 1_000) return (n / 1_000).toFixed(2).replace(/\.?0+$/, "") + "K"
  return String(n)
}

/** 0.5254 → "52.5%" */
export function formatPct(p: number | null | undefined, digits = 1): string {
  if (p == null || isNaN(p)) return "—"
  return (p * 100).toFixed(digits) + "%"
}

/** 367 → "06:07" */
export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "—"
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
  return `${m}:${s.toString().padStart(2, "0")}`
}

import FilterChips from "./FilterChips"
import { REGIONS, REGION_LABELS } from "@/types/domain"

interface RegionChipProps {
  value: string
  onChange: (v: string) => void
  scope?: readonly string[]
  /** true → 用「🌐 总榜」(value="global") 替代「全部」(value="") */
  showGlobal?: boolean
}

export default function RegionChip({ value, onChange, scope, showGlobal }: RegionChipProps) {
  const list = scope || REGIONS
  const head = showGlobal
    ? { value: "global", label: "🌐 总榜" }
    : { value: "", label: "全部" }
  const options = [
    head,
    ...list.map((r) => ({
      value: r,
      label: REGION_LABELS[r as keyof typeof REGION_LABELS] || r.toUpperCase(),
    })),
  ]
  return <FilterChips label="国家" options={options} value={value} onChange={onChange} />
}

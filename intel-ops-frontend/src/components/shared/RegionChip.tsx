import FilterChips from "./FilterChips"
import { REGIONS, REGION_LABELS } from "@/types/domain"

interface RegionChipProps {
  value: string
  onChange: (v: string) => void
  scope?: readonly string[]
}

export default function RegionChip({ value, onChange, scope }: RegionChipProps) {
  const list = scope || REGIONS
  const options = [
    { value: "", label: "全部" },
    ...list.map((r) => ({
      value: r,
      label: REGION_LABELS[r as keyof typeof REGION_LABELS] || r.toUpperCase(),
    })),
  ]
  return <FilterChips label="国家" options={options} value={value} onChange={onChange} />
}

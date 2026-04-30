import FilterChips from "./FilterChips"
import { useFilterStore } from "@/stores/filterStore"
import type { AppScope } from "@/types/domain"

const OPTIONS = [
  { value: "competitor", label: "仅竞品" },
  { value: "baseline",   label: "仅 AF" },
  { value: "all",        label: "全部" },
]

interface AppScopeChipProps {
  value?: AppScope
  onChange?: (v: AppScope) => void
}

export default function AppScopeChip(props: AppScopeChipProps) {
  const { appScope, setAppScope } = useFilterStore()
  const value = props.value ?? appScope
  const onChange = props.onChange ?? ((v: string) => setAppScope(v as AppScope))
  return (
    <FilterChips label="范围" options={OPTIONS} value={value} onChange={onChange} />
  )
}

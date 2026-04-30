import { useCallback, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

/**
 * 把页面筛选状态写到 URL（?key=value），统一封装。
 *
 * 用法：
 *   const { value, setValue, allValues } = useUrlFilters({ source: "appstore_rank", region: "" })
 *
 *   <Select value={value("source")} onChange={v => setValue("source", v)} />
 *
 * URL 自动同步，刷新 / 复制链接 / 浏览器前进后退都保持。
 */
export function useUrlFilters<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams()

  const allValues = useMemo(() => {
    const out: Record<string, string> = { ...defaults }
    for (const key of Object.keys(defaults)) {
      const v = params.get(key)
      if (v !== null) out[key] = v
    }
    return out as T
  }, [params, defaults])

  const value = useCallback(
    <K extends keyof T>(key: K): T[K] => allValues[key],
    [allValues]
  )

  const setValue = useCallback(
    <K extends keyof T>(key: K, val: T[K]) => {
      const next = new URLSearchParams(params)
      if (!val || val === defaults[key]) {
        next.delete(key as string)
      } else {
        next.set(key as string, val as string)
      }
      setParams(next, { replace: true })
    },
    [params, setParams, defaults]
  )

  const reset = useCallback(() => {
    setParams(new URLSearchParams(), { replace: true })
  }, [setParams])

  return { value, setValue, allValues, reset }
}

import { useEffect, useMemo, useRef, useState } from "react"
import { cn } from "@/lib/utils"

interface VirtualListProps<T> {
  items: T[]
  /** 单行估算高度（px）— 越准确越流畅 */
  itemHeight: number
  /** 容器高度（px）— 默认 600 */
  height?: number
  renderItem: (item: T, index: number) => React.ReactNode
  /** 列表上下额外渲染的行数 buffer */
  overscan?: number
  className?: string
  /** 取唯一 key */
  keyExtractor?: (item: T, index: number) => string | number
}

/**
 * 极简虚拟滚动列表 — 自实现避免依赖 react-virtuoso（包大小考量）。
 *
 * 适用场景：
 *   - GP Reviews 评论流（>100 条时启用）
 *   - 同步日志（rolling 50, 但抓取阶段可达数百）
 *   - 商业新闻 / 社媒评论（数百条）
 *
 * 当 items.length < 30 时降级为不分块的常规渲染（避免无谓开销）。
 */
export default function VirtualList<T>({
  items,
  itemHeight,
  height = 600,
  renderItem,
  overscan = 5,
  className,
  keyExtractor,
}: VirtualListProps<T>) {
  const ref = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onScroll = () => setScrollTop(el.scrollTop)
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

  // 数据少 → 不虚拟化（更轻量）
  if (items.length < 30) {
    return (
      <div className={cn("overflow-auto", className)} style={{ maxHeight: height }}>
        {items.map((item, i) => (
          <div key={keyExtractor?.(item, i) ?? i}>{renderItem(item, i)}</div>
        ))}
      </div>
    )
  }

  const totalHeight = items.length * itemHeight
  const startIdx = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan)
  const visibleCount = Math.ceil(height / itemHeight) + overscan * 2
  const endIdx = Math.min(items.length, startIdx + visibleCount)
  const offsetY = startIdx * itemHeight

  const slice = useMemo(
    () => items.slice(startIdx, endIdx),
    [items, startIdx, endIdx]
  )

  return (
    <div
      ref={ref}
      className={cn("overflow-auto relative", className)}
      style={{ height }}
    >
      <div style={{ height: totalHeight, position: "relative" }}>
        <div style={{ transform: `translateY(${offsetY}px)` }}>
          {slice.map((item, i) => {
            const realIdx = startIdx + i
            return (
              <div
                key={keyExtractor?.(item, realIdx) ?? realIdx}
                style={{ height: itemHeight }}
              >
                {renderItem(item, realIdx)}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

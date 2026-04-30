/**
 * vs baseline 计算（AF = baseline）
 *
 * 颜色约定（注意：竞品优于 AF 用 danger 红，竞品劣于 AF 用 success 绿）
 *   - "danger"  红 = 竞品在该指标上比我方强（警示）
 *   - "success" 绿 = 我方在该指标上领先
 *   - "neutral" 灰 = 数据缺失或差异微小
 */

export type BaselineColor = "danger" | "success" | "neutral"

export interface BaselineDelta {
  value: number | null
  display: string
  color: BaselineColor
}

/** 数值型（下载 / 收入 / 访问量）— 越大越强 */
export function computeNumericDelta(
  competitor: number | null | undefined,
  af: number | null | undefined
): BaselineDelta {
  if (competitor == null || af == null || af === 0) {
    return { value: null, display: "—", color: "neutral" }
  }
  const delta = (competitor - af) / af
  const sign = delta > 0 ? "+" : ""
  return {
    value: delta,
    display: `${sign}${(delta * 100).toFixed(1)}%`,
    color: delta > 0.01 ? "danger" : delta < -0.01 ? "success" : "neutral",
  }
}

/** 排名型 — 数小=好（AF 排名 - 竞品排名）*/
export function computeRankDelta(
  competitor: number | null | undefined,
  af: number | null | undefined
): BaselineDelta {
  if (competitor == null || af == null) {
    return { value: null, display: "—", color: "neutral" }
  }
  const delta = af - competitor   // 正 = 竞品比 AF 排名靠前
  const sign = delta > 0 ? "+" : ""
  return {
    value: delta,
    display: `${sign}${delta} 名`,
    color: delta > 0 ? "danger" : delta < 0 ? "success" : "neutral",
  }
}

/** 评分型 — 直接相减 */
export function computeRatingDelta(
  competitor: number | null | undefined,
  af: number | null | undefined
): BaselineDelta {
  if (competitor == null || af == null) {
    return { value: null, display: "—", color: "neutral" }
  }
  const delta = competitor - af
  const sign = delta > 0 ? "+" : ""
  return {
    value: delta,
    display: `${sign}${delta.toFixed(1)} 星`,
    color: delta > 0 ? "danger" : delta < 0 ? "success" : "neutral",
  }
}

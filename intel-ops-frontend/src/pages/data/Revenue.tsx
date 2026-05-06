/** 收入下载页 · 双源合并视图
 *
 * 用户视角："大概看个趋势" — 不要 source 切换，把 2 个源的数据并排展示。
 *
 * 数据现实：
 *   sensor_tower → us 1 国 · 下载 + 收入 + 排名 (10/10 竞品)
 *   androidrank  → 全球总 · 仅下载 (8/8 竞品，无收入)
 *
 * 表格 6 列：
 *   产品 | ST · 月下载(US) vs AF | ST · 月收入(US) vs AF | AR · 全球下载 vs AF
 *
 * AF 永远固定第一行高亮，其他竞品按 ST 月收入降序（同样保留 baseline 比较）。
 */
import { useMemo, useState } from "react"
import PageHeader from "@/components/shared/PageHeader"
import KpiCard, { KpiRow } from "@/components/shared/KpiCard"
import BaselineToggle from "@/components/shared/BaselineToggle"
import BaselineDeltaCell from "@/components/shared/BaselineDeltaCell"
import EmptyState from "@/components/shared/EmptyState"
import { SkeletonTable } from "@/components/shared/Skeleton"
import { useRank } from "@/hooks/api/useRank"
import { computeNumericDelta } from "@/lib/baseline"
import { formatCompactNumber } from "@/lib/utils"
import { BASELINE_APP } from "@/types/domain"

interface MergedRow {
  competitor: string
  st_dl: number | null      // Sensor Tower us 月下载
  st_rev: number | null     // Sensor Tower us 月收入
  st_rank: number | null    // Sensor Tower us 体育榜排名
  ar_dl: number | null      // Androidrank 全球总下载
}

export default function Revenue() {
  const [showBaseline, setShowBaseline] = useState(true)

  // 两个源并发拉
  const stQ = useRank({ source: "sensor_tower", region: "us", limit: 100 })
  const arQ = useRank({ source: "androidrank", limit: 100 })

  const isLoading = stQ.isLoading || arQ.isLoading
  const isError = stQ.isError && arQ.isError
  const refetch = () => { stQ.refetch(); arQ.refetch() }

  // 按竞品名合并两个 source 的字段
  const { rows, af } = useMemo(() => {
    const stByName: Record<string, any> = {}
    for (const r of stQ.data?.rankings || []) {
      if (r.competitor) stByName[r.competitor] = r
    }
    const arByName: Record<string, any> = {}
    for (const r of arQ.data?.rankings || []) {
      if (r.competitor) arByName[r.competitor] = r
    }
    // 取两个源 competitor 名字的并集
    const allNames = new Set<string>([
      ...Object.keys(stByName),
      ...Object.keys(arByName),
    ])
    const merged: MergedRow[] = [...allNames].map((name) => ({
      competitor: name,
      st_dl: stByName[name]?.downloads_num ?? null,
      st_rev: stByName[name]?.revenue_num ?? null,
      st_rank: stByName[name]?.rank_value ?? null,
      ar_dl: arByName[name]?.downloads_num ?? null,
    }))
    const af = merged.find((r) => r.competitor === BASELINE_APP) || null
    const others = merged
      .filter((r) => r.competitor !== BASELINE_APP)
      .sort((a, b) => {
        const va = a.st_rev ?? a.st_dl ?? a.ar_dl ?? 0
        const vb = b.st_rev ?? b.st_dl ?? b.ar_dl ?? 0
        return vb - va
      })
    return { rows: af ? [af, ...others] : others, af }
  }, [stQ.data, arQ.data])

  // KPI — AF baseline 4 个数
  const kpi = {
    afDl: af?.st_dl,
    afRev: af?.st_rev,
    afRank: af?.st_rank,
    completeness: rows.filter((r) =>
      r.competitor !== BASELINE_APP && (r.st_dl != null || r.ar_dl != null)
    ).length,
  }
  const compCount = rows.filter((r) => r.competitor !== BASELINE_APP).length

  // AR 块特殊提示：AF 不在 Androidrank 索引（区域市场），导致 vs AF 列全空
  const arHasAf = af?.ar_dl != null

  return (
    <div>
      <PageHeader
        title="收入下载"
        subtitle="Sensor Tower (US 月估算) + Androidrank (全球·Android) · 以 AF 为基准"
      />

      <KpiRow>
        <KpiCard
          label="AF 月下载"
          value={kpi.afDl != null ? formatCompactNumber(kpi.afDl) : "—"}
          hint="US (Sensor Tower)"
        />
        <KpiCard
          label="AF 月收入"
          value={kpi.afRev != null ? "$" + formatCompactNumber(kpi.afRev) : "—"}
          hint="US (Sensor Tower)"
        />
        <KpiCard
          label="AF US 排名"
          value={kpi.afRank != null ? `#${kpi.afRank}` : "—"}
          hint="体育榜"
        />
        <KpiCard
          label="数据完整度"
          value={`${kpi.completeness}/${compCount}`}
          hint="竞品至少有一个源"
        />
      </KpiRow>

      <div className="flex justify-end mb-3">
        <BaselineToggle show={showBaseline} onChange={setShowBaseline} />
      </div>

      {isLoading && <SkeletonTable rows={10} />}
      {isError && <EmptyState type="error" onRetry={refetch} />}
      {!isLoading && !isError && rows.length === 0 && <EmptyState type="empty" />}

      {rows.length > 0 && !arHasAf && (
        <div className="mb-2 px-3 py-2 rounded-md border border-semantic-warning/30 bg-semantic-warning/5 text-xs text-muted-foreground">
          ⚠ <span className="font-mono">Androidrank</span> 不收录{" "}
          <span className="font-mono text-foreground">AllFootball</span>（区域市场）
          {" "}和{" "}
          <span className="font-mono text-foreground">310Scores</span>（app 太新），
          故 vs AF 列仅展示 Sensor Tower 块。
        </div>
      )}

      {rows.length > 0 && (
        <div className="border border-border-soft rounded-md bg-card overflow-x-auto">
          <table className="w-full text-xs">
            {/* 双层表头：上层是数据源分组，下层是字段 */}
            <thead className="bg-muted/30">
              <tr className="text-2xs uppercase tracking-wider text-muted-foreground border-b border-border-soft">
                <th rowSpan={2} className="text-left px-3 align-bottom pb-1.5 pt-2">产品</th>
                <th
                  colSpan={showBaseline ? 4 : 2}
                  className="text-center px-3 pt-1.5 pb-0.5 border-l border-border-soft text-muted-foreground/80 font-mono"
                >
                  Sensor Tower (US 月估算)
                </th>
                <th
                  colSpan={showBaseline && arHasAf ? 2 : 1}
                  className="text-center px-3 pt-1.5 pb-0.5 border-l border-border-soft text-muted-foreground/80 font-mono"
                >
                  Androidrank (全球·Android)
                  {!arHasAf && (
                    <span className="ml-1 normal-case font-sans text-2xs text-semantic-warning">
                      · AF 不在此源
                    </span>
                  )}
                </th>
                <th rowSpan={2} className="text-right px-3 align-bottom pb-1.5 pt-2 border-l border-border-soft">
                  US 排名
                </th>
              </tr>
              <tr className="text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="text-right px-3 h-8 border-l border-border-soft">月下载</th>
                {showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
                <th className="text-right px-3 h-8">月收入</th>
                {showBaseline && <th className="text-right px-3 h-8">vs AF</th>}
                <th className="text-right px-3 h-8 border-l border-border-soft">月下载</th>
                {showBaseline && arHasAf && <th className="text-right px-3 h-8">vs AF</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft">
              {rows.map((r) => {
                const isAf = r.competitor === BASELINE_APP
                return (
                  <tr
                    key={r.competitor}
                    className={isAf
                      ? "bg-pill-blue-bg/40 font-medium"
                      : "hover:bg-muted/30 transition-colors duration-150"}
                  >
                    <td className="px-3 h-9">
                      {isAf ? (
                        <>
                          <span className="text-semantic-info">{BASELINE_APP}</span>
                          <span className="ml-2 text-2xs text-pill-blue-fg">[baseline]</span>
                        </>
                      ) : (
                        <span>{r.competitor}</span>
                      )}
                    </td>
                    {/* Sensor Tower 块 */}
                    <td className="px-3 h-9 text-right tabular-nums border-l border-border-soft">
                      {r.st_dl != null ? formatCompactNumber(r.st_dl) : "—"}
                    </td>
                    {showBaseline && (
                      <td className="px-3 h-9 text-right">
                        {isAf ? <span className="text-muted-foreground">—</span>
                              : <BaselineDeltaCell delta={computeNumericDelta(r.st_dl, af?.st_dl ?? null)} />}
                      </td>
                    )}
                    <td className="px-3 h-9 text-right tabular-nums">
                      {r.st_rev != null ? "$" + formatCompactNumber(r.st_rev) : "—"}
                    </td>
                    {showBaseline && (
                      <td className="px-3 h-9 text-right">
                        {isAf ? <span className="text-muted-foreground">—</span>
                              : <BaselineDeltaCell delta={computeNumericDelta(r.st_rev, af?.st_rev ?? null)} />}
                      </td>
                    )}
                    {/* Androidrank 块 — vs AF 列仅在 AF 有数据时展示 */}
                    <td className="px-3 h-9 text-right tabular-nums border-l border-border-soft">
                      {r.ar_dl != null ? formatCompactNumber(r.ar_dl) : "—"}
                    </td>
                    {showBaseline && arHasAf && (
                      <td className="px-3 h-9 text-right">
                        {isAf ? <span className="text-muted-foreground">—</span>
                              : <BaselineDeltaCell delta={computeNumericDelta(r.ar_dl, af?.ar_dl ?? null)} />}
                      </td>
                    )}
                    {/* 排名 */}
                    <td className="px-3 h-9 text-right tabular-nums border-l border-border-soft">
                      {r.st_rank != null ? `#${r.st_rank}` : "—"}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

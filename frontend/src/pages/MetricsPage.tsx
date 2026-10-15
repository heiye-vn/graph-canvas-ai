/**
 * 可观测指标页（M9.3 DoD ②③）。
 *
 * 核心指标只有一个：**计划校验拒绝率** —— 被六道关卡拦下的计划占
 * 尝试规划总数的比例。它是衡量 Agent 稳定性的关键，但多数实现根本
 * 不统计它（被拒的计划无声无息地消失了）。
 *
 * 图表刻意手写 SVG：折线 50 行，不为此引 chart.js（装机在本机有坑）。
 */

import { useQuery } from '@tanstack/react-query'
import { Card, Segmented, Skeleton } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { getMetrics } from '@/api/agent'

export default function MetricsPage() {
  const [days, setDays] = useState(14)
  const metrics = useQuery({
    queryKey: ['agentMetrics', days],
    queryFn: () => getMetrics(days),
  })

  if (metrics.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    )
  }
  if (metrics.isError || !metrics.data) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <p className="text-danger text-sm">指标加载失败：{(metrics.error as Error)?.message}</p>
      </div>
    )
  }

  const data = metrics.data
  const maxRounds = Math.max(1, ...data.daily.map((d) => d.rounds))

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="m-0 text-lg font-medium">Agent 可观测指标</h1>
          <p className="text-faint m-0 text-xs">
            核心指标是「计划校验拒绝率」—— 被六道关卡拦下的计划占比，衡量规划稳定性。
          </p>
        </div>
        <Segmented
          value={days}
          onChange={(value) => setDays(value as number)}
          options={[
            { label: '7 天', value: 7 },
            { label: '14 天', value: 14 },
            { label: '30 天', value: 30 },
          ]}
        />
      </header>

      {/* ---- 核心数字卡 ---- */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="校验拒绝率" value={`${(data.reject_rate * 100).toFixed(1)}%`} highlight />
        <StatCard label="对话轮数" value={String(data.rounds_total)} />
        <StatCard label="平均计划步数" value={data.avg_steps_per_round.toFixed(1)} />
        <StatCard label="工具失败率" value={`${(data.tool_fail_rate * 100).toFixed(1)}%`} />
      </div>

      {/* ---- 拒绝率趋势（SVG 折线） ---- */}
      <Card size="small" title="拒绝率与轮数趋势">
        {data.daily.length === 0 ? (
          <p className="text-faint m-0 text-xs">近 {days} 天还没有对话轮数据。</p>
        ) : (
          <TrendChart daily={data.daily} maxRounds={maxRounds} />
        )}
      </Card>

      {/* ---- prompt 版本对比（DoD ③） ---- */}
      <Card size="small" title="Prompt 版本对比">
        {data.by_prompt_version.length === 0 ? (
          <p className="text-faint m-0 text-xs">还没有规划数据。</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-faint text-left">
                <th className="py-1 font-normal">版本</th>
                <th className="py-1 font-normal">规划次数</th>
                <th className="py-1 font-normal">被拦截</th>
                <th className="py-1 font-normal">拒绝率</th>
                <th className="py-1 font-normal">平均耗时</th>
                <th className="py-1 font-normal">输出 tokens</th>
              </tr>
            </thead>
            <tbody>
              {data.by_prompt_version.map((item) => (
                <tr key={item.prompt_version} className="border-line border-t">
                  <td className="py-1.5">{item.prompt_version}</td>
                  <td className="py-1.5 tabular-nums">{item.plannings}</td>
                  <td className="py-1.5 tabular-nums">{item.validate_failed}</td>
                  <td className="py-1.5 tabular-nums">
                    {(item.reject_rate * 100).toFixed(1)}%
                  </td>
                  <td className="py-1.5 tabular-nums">{item.avg_duration_ms}ms</td>
                  <td className="py-1.5 tabular-nums">{item.tokens_out}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <p className="text-faint text-xs">
        <Link to="/" className="text-brand">← 回到工作台</Link>
      </p>
    </div>
  )
}

function StatCard({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={`border-line rounded-card border p-3 ${highlight ? 'border-brand' : ''}`}>
      <p className="text-faint m-0 text-[11px]">{label}</p>
      <p className={`m-0 mt-1 text-xl font-medium tabular-nums ${highlight ? 'text-brand' : ''}`}>
        {value}
      </p>
    </div>
  )
}

/** 双序列：柱 = 轮数，线 = 当日失败轮数。手写 SVG，零依赖。 */
function TrendChart({ daily, maxRounds }: { daily: { day: string; rounds: number; failed: number }[]; maxRounds: number }) {
  const width = 640
  const height = 180
  const padding = { top: 12, right: 12, bottom: 22, left: 28 }
  const innerW = width - padding.left - padding.right
  const innerH = height - padding.top - padding.bottom
  const n = daily.length
  const stepX = n > 1 ? innerW / (n - 1) : innerW
  const barW = Math.min(28, (innerW / Math.max(1, n)) * 0.6)
  const x = (i: number) => (n > 1 ? padding.left + i * stepX : padding.left + innerW / 2)
  const y = (v: number) => padding.top + innerH - (v / maxRounds) * innerH

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      <line x1={padding.left} y1={padding.top + innerH} x2={width - padding.right} y2={padding.top + innerH} stroke="var(--border, #ddd)" />
      {daily.map((d, i) => (
        <g key={d.day}>
          <rect
            x={x(i) - barW / 2}
            y={y(d.rounds)}
            width={barW}
            height={padding.top + innerH - y(d.rounds)}
            rx={2}
            className="fill-brand/40"
          />
          {d.failed > 0 && (
            <rect
              x={x(i) - barW / 2}
              y={y(d.failed)}
              width={barW}
              height={Math.max(2, padding.top + innerH - y(d.failed))}
              rx={2}
              className="fill-danger/50"
            />
          )}
          <text x={x(i)} y={height - 6} textAnchor="middle" className="fill-current text-[9px] opacity-60">
            {d.day.slice(5)}
          </text>
        </g>
      ))}
      <text x={4} y={padding.top + 8} className="fill-current text-[9px] opacity-60">
        {maxRounds}
      </text>
    </svg>
  )
}

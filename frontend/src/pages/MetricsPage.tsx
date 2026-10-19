/**
 * 可观测指标页 —— Agent 稳定性与规划表现看板。
 */

import { useQuery } from '@tanstack/react-query'
import { Segmented, Skeleton } from 'antd'
import { useState } from 'react'
import {
  BarChartOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'

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
        <p className="text-red-500 text-sm">指标加载失败：{(metrics.error as Error)?.message}</p>
      </div>
    )
  }

  const data = metrics.data
  const maxRounds = Math.max(1, ...data.daily.map((d) => d.rounds))

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-8 select-none">
      <header className="flex items-center justify-between pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="m-0 text-xl font-bold text-slate-900">Agent 可观测指标</h1>
            <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded font-mono">
              Metrics
            </span>
          </div>
          <p className="text-slate-500 m-0 mt-1 text-xs">
            核心指标「计划校验拒绝率」—— 衡量多步规划逻辑的稳定性与模型执行能力。
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
          className="text-xs"
        />
      </header>

      {/* ---- 核心数字卡 ---- */}
      <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4">
        <StatCard
          label="校验拒绝率"
          value={`${(data.reject_rate * 100).toFixed(1)}%`}
          icon={<CloseCircleOutlined className="text-amber-500" />}
          highlight
        />
        <StatCard
          label="对话总轮数"
          value={String(data.rounds_total)}
          icon={<BarChartOutlined className="text-blue-500" />}
        />
        <StatCard
          label="平均计划步数"
          value={data.avg_steps_per_round.toFixed(1)}
          icon={<ClockCircleOutlined className="text-indigo-500" />}
        />
        <StatCard
          label="工具失败率"
          value={`${(data.tool_fail_rate * 100).toFixed(1)}%`}
          icon={<CheckCircleOutlined className="text-emerald-500" />}
        />
      </div>

      {/* ---- 拒绝率趋势（SVG 折线与柱状组合图） ---- */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
        <h3 className="text-xs font-semibold text-slate-800 m-0 mb-3">拒绝率与轮数趋势</h3>
        {data.daily.length === 0 ? (
          <p className="text-slate-400 m-0 text-xs py-8 text-center">近 {days} 天暂无对话轮数据</p>
        ) : (
          <TrendChart daily={data.daily} maxRounds={maxRounds} />
        )}
      </div>

      {/* ---- Prompt 版本对比 ---- */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
        <h3 className="text-xs font-semibold text-slate-800 m-0 mb-3">Prompt 版本效能对比</h3>
        {data.by_prompt_version.length === 0 ? (
          <p className="text-slate-400 m-0 text-xs py-4 text-center">暂无版本规划数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 font-medium">
                  <th className="pb-2">版本标识</th>
                  <th className="pb-2">规划次数</th>
                  <th className="pb-2">拦截次数</th>
                  <th className="pb-2">拒绝率</th>
                  <th className="pb-2">平均耗时</th>
                  <th className="pb-2">输出 Tokens</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.by_prompt_version.map((item) => (
                  <tr key={item.prompt_version} className="hover:bg-slate-50 transition-colors">
                    <td className="py-2.5 font-medium text-slate-800">{item.prompt_version}</td>
                    <td className="py-2.5 font-mono tabular-nums text-slate-600">{item.plannings}</td>
                    <td className="py-2.5 font-mono tabular-nums text-slate-600">{item.validate_failed}</td>
                    <td className="py-2.5 font-mono tabular-nums text-amber-600 font-medium">
                      {(item.reject_rate * 100).toFixed(1)}%
                    </td>
                    <td className="py-2.5 font-mono tabular-nums text-slate-600">{item.avg_duration_ms}ms</td>
                    <td className="py-2.5 font-mono tabular-nums text-slate-600">{item.tokens_out}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({
  label,
  value,
  icon,
  highlight = false,
}: {
  label: string
  value: string
  icon?: React.ReactNode
  highlight?: boolean
}) {
  return (
    <div
      className={`rounded-xl border p-4 transition-all ${
        highlight
          ? 'border-blue-200 bg-blue-50/30 shadow-2xs'
          : 'border-slate-200 bg-white shadow-2xs'
      }`}
    >
      <div className="flex items-center justify-between text-slate-400 mb-2">
        <span className="text-xs font-medium text-slate-500">{label}</span>
        {icon}
      </div>
      <p className="m-0 text-2xl font-bold font-mono tracking-tight text-slate-900 tabular-nums">
        {value}
      </p>
    </div>
  )
}

function TrendChart({
  daily,
  maxRounds,
}: {
  daily: { day: string; rounds: number; failed: number }[]
  maxRounds: number
}) {
  const width = 640
  const height = 180
  const padding = { top: 16, right: 16, bottom: 24, left: 32 }
  const innerW = width - padding.left - padding.right
  const innerH = height - padding.top - padding.bottom
  const n = daily.length
  const stepX = n > 1 ? innerW / (n - 1) : innerW
  const barW = Math.min(24, (innerW / Math.max(1, n)) * 0.6)
  const x = (i: number) => (n > 1 ? padding.left + i * stepX : padding.left + innerW / 2)
  const y = (v: number) => padding.top + innerH - (v / maxRounds) * innerH

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      <line
        x1={padding.left}
        y1={padding.top + innerH}
        x2={width - padding.right}
        y2={padding.top + innerH}
        stroke="#e2e8f0"
      />
      {daily.map((d, i) => (
        <g key={d.day}>
          <rect
            x={x(i) - barW / 2}
            y={y(d.rounds)}
            width={barW}
            height={Math.max(2, padding.top + innerH - y(d.rounds))}
            rx={3}
            fill="#3b82f6"
            opacity="0.8"
          />
          {d.failed > 0 && (
            <rect
              x={x(i) - barW / 2}
              y={y(d.failed)}
              width={barW}
              height={Math.max(2, padding.top + innerH - y(d.failed))}
              rx={3}
              fill="#ef4444"
              opacity="0.85"
            />
          )}
          <text
            x={x(i)}
            y={height - 6}
            textAnchor="middle"
            fill="#94a3b8"
            className="text-[9px] font-mono"
          >
            {d.day.slice(5)}
          </text>
        </g>
      ))}
      <text x={4} y={padding.top + 8} fill="#94a3b8" className="text-[9px] font-mono">
        {maxRounds}
      </text>
    </svg>
  )
}


/**
 * 使用概览 —— 给用户看的「我这两天用得顺不顺」。
 *
 * 与旧的 Agent 可观测指标（拒绝率 / prompt 版本 / 计划步数）的区别：
 * 那些是研发调 prompt 用的，用户看不懂也不需要；这里只回答四件事 ——
 * 成功几次、失败几次、平均多久、出了几张图，外加一份失败记录。
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Segmented, Skeleton } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  PictureOutlined,
} from '@ant-design/icons'
import type { EChartsOption } from 'echarts'

import { getUsageSummary } from '@/api/usage'
import type { FailureItem } from '@/api/usage'
import EChart from '@/components/EChart'

const PALETTE = [
  '#2563eb',
  '#0ea5e9',
  '#14b8a6',
  '#f59e0b',
  '#ec4899',
  '#8b5cf6',
  '#64748b',
]

function StatCard({
  label,
  value,
  hint,
  icon,
  tone,
}: {
  label: string
  value: string
  hint: string
  icon: React.ReactNode
  tone: string
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">{label}</span>
        <span className={`text-base ${tone}`}>{icon}</span>
      </div>
      <p className="m-0 mt-2 text-2xl font-semibold tabular-nums text-slate-900">
        {value}
      </p>
      <p className="m-0 mt-1 text-[11px] leading-snug text-slate-400">{hint}</p>
    </div>
  )
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function FailureRow({ item }: { item: FailureItem }) {
  const isChat = item.kind === 'chat'
  return (
    <div className="flex items-start gap-3 py-2.5">
      <span
        className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${
          isChat ? 'bg-violet-50 text-violet-600' : 'bg-red-50 text-red-600'
        }`}
      >
        {isChat ? '对话' : '任务'}
      </span>
      <div className="min-w-0 flex-1">
        <p className="m-0 truncate text-xs text-slate-700">{item.label}</p>
        <p className="m-0 mt-0.5 truncate text-[11px] text-slate-400">
          {item.error || '服务端没有返回原因'}
        </p>
      </div>
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-slate-400">
        {formatTime(item.created_at)}
      </span>
    </div>
  )
}

function TokenStat({
  label,
  value,
  emphasis = false,
}: {
  label: string
  value: number
  emphasis?: boolean
}) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <p className="m-0 text-[11px] text-slate-500">{label}</p>
      <p
        className={`m-0 mt-0.5 font-mono tabular-nums ${
          emphasis
            ? 'text-lg font-semibold text-slate-900'
            : 'text-sm text-slate-700'
        }`}
      >
        {value.toLocaleString('zh-CN')}
      </p>
    </div>
  )
}

export default function MetricsPage() {
  const [days, setDays] = useState(7)
  const usage = useQuery({
    queryKey: ['usage', days],
    queryFn: () => getUsageSummary(days),
  })

  const barOption = useMemo<EChartsOption>(() => {
    const daily = usage.data?.daily ?? []
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: {
        bottom: 0,
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { fontSize: 11, color: '#64748b' },
      },
      grid: { left: 4, right: 8, top: 12, bottom: 34, containLabel: true },
      xAxis: {
        type: 'category',
        data: daily.map((item) => item.day.slice(5)),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: '#f1f5f9' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      series: [
        {
          name: '成功',
          type: 'bar',
          stack: 'tasks',
          barMaxWidth: 26,
          itemStyle: { color: '#2563eb' },
          data: daily.map((item) => item.succeeded),
        },
        {
          name: '失败',
          type: 'bar',
          stack: 'tasks',
          barMaxWidth: 26,
          itemStyle: { color: '#ef4444' },
          data: daily.map((item) => item.failed),
        },
      ],
    }
  }, [usage.data])

  const pieOption = useMemo<EChartsOption>(() => {
    const byTool = usage.data?.by_tool ?? []
    return {
      tooltip: { trigger: 'item', formatter: '{b}：{c} 次（{d}%）' },
      legend: {
        orient: 'vertical',
        right: 0,
        top: 'center',
        itemWidth: 8,
        itemHeight: 8,
        itemGap: 10,
        textStyle: { fontSize: 11, color: '#64748b' },
      },
      series: [
        {
          type: 'pie',
          radius: ['46%', '70%'],
          center: ['34%', '50%'],
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          label: { show: false },
          emphasis: { scale: true, scaleSize: 4 },
          data: byTool.map((item, index) => ({
            name: item.label,
            value: item.count,
            itemStyle: { color: PALETTE[index % PALETTE.length] },
          })),
        },
      ],
    }
  }, [usage.data])

  const tokenOption = useMemo<EChartsOption>(() => {
    const byDay = usage.data?.tokens.by_day ?? []
    return {
      tooltip: { trigger: 'axis' },
      legend: {
        bottom: 0,
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { fontSize: 11, color: '#64748b' },
      },
      grid: { left: 4, right: 8, top: 12, bottom: 30, containLabel: true },
      xAxis: {
        type: 'category',
        data: byDay.map((item) => item.day.slice(5)),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#f1f5f9' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      series: [
        {
          name: '输入',
          type: 'line',
          smooth: true,
          symbolSize: 5,
          itemStyle: { color: '#0ea5e9' },
          areaStyle: { color: 'rgba(14,165,233,0.08)' },
          data: byDay.map((item) => item.input),
        },
        {
          name: '输出',
          type: 'line',
          smooth: true,
          symbolSize: 5,
          itemStyle: { color: '#8b5cf6' },
          areaStyle: { color: 'rgba(139,92,246,0.08)' },
          data: byDay.map((item) => item.output),
        },
      ],
    }
  }, [usage.data])

  if (usage.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    )
  }

  if (usage.isError || !usage.data) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <p className="text-sm text-red-500">
          使用数据加载失败：{(usage.error as Error)?.message}
        </p>
      </div>
    )
  }

  const data = usage.data
  const hasTasks = data.by_tool.length > 0
  const successRate =
    data.tasks.total > 0
      ? Math.round((data.tasks.succeeded / data.tasks.total) * 100)
      : null

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-8">
      <header className="flex items-end justify-between border-b border-slate-200 pb-4">
        <div>
          <h1 className="m-0 text-xl font-bold text-slate-900">使用概览</h1>
          <p className="m-0 mt-1 text-xs text-slate-500">
            最近 {data.days} 天的生成与编辑情况。只统计你自己发起的操作。
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

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="成功任务"
          value={String(data.tasks.succeeded)}
          hint={`共发起 ${data.tasks.total} 次${successRate === null ? '' : `，成功率 ${successRate}%`}`}
          icon={<CheckCircleOutlined />}
          tone="text-emerald-500"
        />
        <StatCard
          label="失败"
          value={String(data.tasks.failed + data.chats.failed)}
          hint={`任务 ${data.tasks.failed} 次 · 对话 ${data.chats.failed} 次`}
          icon={<CloseCircleOutlined />}
          tone="text-red-500"
        />
        <StatCard
          label="平均耗时"
          value={data.avg_seconds > 0 ? `${data.avg_seconds}s` : '—'}
          hint="只算成功的任务"
          icon={<ClockCircleOutlined />}
          tone="text-sky-500"
        />
        <StatCard
          label="生成图片"
          value={String(data.images)}
          hint="不含投放尺寸与选区遮罩"
          icon={<PictureOutlined />}
          tone="text-slate-400"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <section className="rounded-lg border border-slate-200 bg-white p-4 lg:col-span-3">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="m-0 text-sm font-semibold text-slate-900">每日任务</h2>
            <span className="text-[11px] text-slate-400">成功 / 失败</span>
          </div>
          <EChart option={barOption} height={230} />
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4 lg:col-span-2">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="m-0 text-sm font-semibold text-slate-900">用了哪些能力</h2>
            <span className="text-[11px] text-slate-400">按成功次数</span>
          </div>
          {hasTasks ? (
            <EChart option={pieOption} height={230} />
          ) : (
            <div className="flex h-[230px] items-center justify-center text-xs text-slate-400">
              这段时间还没有成功的任务
            </div>
          )}
        </section>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="m-0 text-sm font-semibold text-slate-900">Token 消耗</h2>
          <span className="text-[11px] text-slate-400">
            只统计服务商真实返回的用量
          </span>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          <div className="grid grid-cols-2 gap-2.5 lg:col-span-2">
            <TokenStat label="合计" value={data.tokens.total} emphasis />
            <TokenStat label="输入" value={data.tokens.input} />
            <TokenStat label="输出" value={data.tokens.output} />
            <TokenStat label="调用次数" value={data.tokens.calls} />
          </div>
          <div className="lg:col-span-3">
            {data.tokens.calls > 0 ? (
              <EChart option={tokenOption} height={180} />
            ) : (
              <div className="flex h-[180px] items-center justify-center rounded-md bg-slate-50 text-xs text-slate-400">
                这段时间没有产生 token 的调用（全是图像任务）
              </div>
            )}
          </div>
        </div>

        {data.tokens.missing_calls > 0 && (
          <p className="m-0 mt-3 rounded bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-700">
            有 {data.tokens.missing_calls} 次调用没有返回用量（服务商未提供），
            未计入上述数字 —— 这里不做估算。
          </p>
        )}
        <p className="m-0 mt-2 text-[11px] text-slate-400">
          生图、去背景、超分等任务按次计费，不产生 token，不在此统计。
        </p>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="m-0 text-sm font-semibold text-slate-900">失败记录</h2>
          <span className="text-[11px] text-slate-400">
            {data.failures.length > 0 ? `最近 ${data.failures.length} 条` : '没有失败'}
          </span>
        </div>
        {data.failures.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">
            这段时间没有失败，挺好。
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {data.failures.map((item) => (
              <FailureRow key={`${item.kind}-${item.id}`} item={item} />
            ))}
          </div>
        )}
      </section>

      <p className="m-0 text-center text-[10px] text-slate-300">
        拒绝率、Prompt 版本等研发指标已移到内部看板，不再对使用者展示。
      </p>
    </div>
  )
}

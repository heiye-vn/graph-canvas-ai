/**
 * 极薄的 ECharts 封装。
 *
 * 为什么不用 echarts-for-react：这里只需要「option 变了就 setOption」，
 * 多一个依赖不划算。按需注册图表与组件，避免把整包 1MB 打进 bundle。
 *
 * 两个生命周期细节：
 *   1. init 只跑一次（依赖 []）—— 每次 option 变化都重建实例会掉帧
 *   2. ResizeObserver 负责 resize —— 侧栏收起/窗口拉伸时图表不能保持旧宽度
 */

import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export default function EChart({
  option,
  height = 240,
}: {
  option: EChartsOption
  height?: number
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    const element = containerRef.current
    if (!element) return

    const chart = echarts.init(element)
    chartRef.current = chart

    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element)

    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    // notMerge = true：数据从 7 天切到 30 天时，旧 series 不能残留
    chartRef.current?.setOption(option, true)
  }, [option])

  return <div ref={containerRef} style={{ height, width: '100%' }} />
}

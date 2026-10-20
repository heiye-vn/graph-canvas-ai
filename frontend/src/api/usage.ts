/** 使用概览（用户视角）：成功/失败、耗时、出图数、失败记录。 */

import { apiGet } from './client'

export interface UsageCounts {
  total: number
  succeeded: number
  failed: number
  cancelled: number
}

export interface DailyUsage {
  day: string
  succeeded: number
  failed: number
}

export interface ToolUsage {
  tool: string
  label: string
  count: number
}

export interface FailureItem {
  id: string
  kind: 'task' | 'chat'
  label: string
  error: string | null
  created_at: string
}

export interface DailyTokens {
  day: string
  input: number
  output: number
}

/** 只统计服务商真实返回的 usage；缺失调用单独计数，不估算 */
export interface TokenSummary {
  input: number
  output: number
  total: number
  calls: number
  missing_calls: number
  by_day: DailyTokens[]
}

export interface UsageSummary {
  days: number
  tasks: UsageCounts
  chats: UsageCounts
  avg_seconds: number
  images: number
  daily: DailyUsage[]
  by_tool: ToolUsage[]
  tokens: TokenSummary
  failures: FailureItem[]
}

export const getUsageSummary = (days: number) =>
  apiGet<UsageSummary>(`/usage/summary?days=${days}`)

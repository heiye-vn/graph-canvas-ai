/**
 * Agent 多步计划接口（M8）。
 *
 * 一轮对话 = 一条 AgentRun：plan 里带每个步骤的状态，前端据此渲染
 * 计划卡片（确认/取消/重试），排队步完成后凭 run_id 驱动继续。
 */

import { apiGet, apiPost } from './client'

export type PlanStepStatus =
  | 'pending'
  | 'waiting'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'canceled'

export interface PlanStep {
  id: string
  tool: string
  params: Record<string, unknown>
  depends_on: string[]
  status: PlanStepStatus
  run_id: string | null
  message: string | null
}

export type AgentRunStatus =
  | 'planning'
  | 'awaiting_confirm'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface AgentRun {
  id: string
  session_id: string
  instruction: string
  plan: PlanStep[]
  reply: string | null
  status: AgentRunStatus
  error: string | null
  created_at: string
  updated_at: string
}

export const createPlan = (session_id: string, instruction: string) =>
  apiPost<AgentRun>('/agent/plan', { session_id, instruction })

export const getAgentRun = (runId: string) => apiGet<AgentRun>(`/agent/runs/${runId}`)

export const confirmPlan = (runId: string) => apiPost<AgentRun>(`/agent/runs/${runId}/confirm`)

export const cancelPlan = (runId: string) => apiPost<AgentRun>(`/agent/runs/${runId}/cancel`)

export const retryPlan = (runId: string) => apiPost<AgentRun>(`/agent/runs/${runId}/retry`)

/** 排队步的 ToolRun 结束后驱动计划继续。 */
export const continuePlan = (runId: string, toolRunId: string) =>
  apiPost<AgentRun>(`/agent/runs/${runId}/continue`, { run_id: toolRunId })

/** 恢复现场：这个会话的历史对话轮（旧→新）。 */
export const listSessionRuns = (sessionId: string) =>
  apiGet<AgentRun[]>(`/agent/sessions/${sessionId}/runs`)

// ---------------------------------------------------------------- trace / metrics（M9.3）

export interface TraceSpan {
  id: string
  agent_run_id: string
  kind: 'planner' | 'validate' | 'tool' | 'reflect' | 'turn'
  name: string
  status: 'ok' | 'failed'
  duration_ms: number | null
  prompt_version: string | null
  model: string | null
  tokens_in: number | null
  tokens_out: number | null
  detail: Record<string, unknown> | null
  created_at: string
}

export const getTrace = (runId: string) => apiGet<TraceSpan[]>(`/agent/runs/${runId}/trace`)

export interface VersionMetrics {
  prompt_version: string
  plannings: number
  validate_failed: number
  reject_rate: number
  avg_duration_ms: number
  tokens_out: number
}

export interface DailyMetrics {
  day: string
  rounds: number
  failed: number
  steps: number
}

export interface AgentMetrics {
  days: number
  rounds_total: number
  rejected_total: number
  reject_rate: number
  avg_steps_per_round: number
  tool_fail_rate: number
  daily: DailyMetrics[]
  by_prompt_version: VersionMetrics[]
}

export const getMetrics = (days = 14) => apiGet<AgentMetrics>(`/agent/metrics?days=${days}`)

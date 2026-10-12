import { apiGet, apiPost } from './client'
import type { RunResult, RunStatus } from '@/domain/events'

export interface RunOut {
  id: string
  tool: string
  status: RunStatus
  progress: number
  stage: string | null
  params: Record<string, unknown>
  result: RunResult | null
  error: { code?: string; message?: string; recoverable?: boolean } | null
}

export interface TextToImagePayload {
  prompt: string
  size?: string
  n?: number
}

/** 常用出图尺寸：商品物料就这几种比例，别让用户自己猜像素。 */
export const SIZE_PRESETS = [
  { value: '1024x1024', label: '方图 1:1' },
  { value: '768x1024', label: '竖版 3:4' },
  { value: '1024x768', label: '横版 4:3' },
] as const

/** 建任务：返回 202，结果靠 /events/runs/{id} 推过来，不要在这里等。 */
export const createTextToImage = (payload: TextToImagePayload) =>
  apiPost<RunOut>('/runs/text-to-image', payload)

export const listRuns = () => apiGet<RunOut[]>('/runs')

export const getRun = (id: string) => apiGet<RunOut>(`/runs/${id}`)

export const cancelRun = (id: string) => apiPost<RunOut>(`/runs/${id}/cancel`)

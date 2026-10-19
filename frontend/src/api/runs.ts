import { apiDelete, apiGet, apiPost } from './client'
import type { AssetOut } from './assets'
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
  created_at?: string
  cover_url?: string | null
}

export interface TextToImagePayload {
  prompt: string
  size?: string
  n?: number
}

/** 常用出图尺寸：涵盖主流社媒、电商主图、海报及横版宽屏尺寸。 */
export const SIZE_PRESETS = [
  { value: '1024x1024', label: '1:1', ratio: '1:1' },
  { value: '816x1020', label: '4:5', ratio: '4:5' },
  { value: '768x1024', label: '3:4', ratio: '3:4' },
  { value: '576x1024', label: '9:16', ratio: '9:16' },
  { value: '1024x576', label: '16:9', ratio: '16:9' },
] as const

/** 建任务：返回 202，结果靠 /events/runs/{id} 推过来，不要在这里等。 */
export const createTextToImage = (payload: TextToImagePayload) =>
  apiPost<RunOut>('/runs/text-to-image', payload)

export const listRuns = (params?: { tool?: string; status?: string; limit?: number }) => {
  const search = new URLSearchParams()
  if (params?.tool) search.set('tool', params.tool)
  if (params?.status) search.set('status', params.status)
  if (params?.limit) search.set('limit', String(params.limit))
  const qs = search.toString()
  return apiGet<RunOut[]>(`/runs${qs ? `?${qs}` : ''}`)
}

export const getRun = (id: string) => apiGet<RunOut>(`/runs/${id}`)

/**
 * 这一次运行产出的素材（带预签名 URL）。
 *
 * 存在的意义：让候选页**可刷新、可分享**。只靠 SSE 内存里的事件恢复不了现场，
 * 刷新一下这次生成的图就全丢了。
 */
export const listRunAssets = (id: string) => apiGet<AssetOut[]>(`/runs/${id}/assets`)

export const cancelRun = (id: string) => apiPost<RunOut>(`/runs/${id}/cancel`)

export const deleteRun = (id: string) => apiDelete(`/runs/${id}`)


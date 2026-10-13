/**
 * 编辑会话接口。
 *
 * 与 runs 的分工一致：**REST 负责现场恢复**。`GET /edit-sessions/{id}` 是画布的
 * 唯一数据源 —— session id 在 URL 上，刷新和分享都靠它把画布重建出来。
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client'
import type { AssetOut } from './assets'

// 文档结构与后端 LayerDocument 一致；字段定义集中在 domain/layerDoc.ts，这里直接引用
import type { LayerDocument } from '@/domain/layerDoc'

export interface SessionSummary {
  id: string
  title: string
  layer_count: number
  asset_count: number
  created_at: string
  updated_at: string
}

export interface SessionOut {
  id: string
  title: string
  doc: LayerDocument
  assets: AssetOut[]
  created_at: string
  updated_at: string
}

export const createSession = (payload: { asset_ids: string[]; title?: string }) =>
  apiPost<SessionOut>('/edit-sessions', payload)

export const listSessions = () => apiGet<SessionSummary[]>('/edit-sessions')

export const getSession = (id: string) => apiGet<SessionOut>(`/edit-sessions/${id}`)

export const addSessionAssets = (id: string, asset_ids: string[]) =>
  apiPost<SessionOut>(`/edit-sessions/${id}/assets`, { asset_ids })

/** 整份替换图层文档：工具执行后产出的是完整文档，不做 patch。 */
export const replaceSessionDoc = (id: string, doc: LayerDocument) =>
  apiPut<SessionOut>(`/edit-sessions/${id}/doc`, { doc })

export const renameSession = (id: string, title: string) =>
  apiPatch<SessionOut>(`/edit-sessions/${id}`, { title })

export const deleteSession = (id: string) => apiDelete<void>(`/edit-sessions/${id}`)

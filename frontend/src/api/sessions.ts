/**
 * 编辑会话接口。
 *
 * 与 runs 的分工一致：**REST 负责现场恢复**。`GET /edit-sessions/{id}` 是画布的
 * 唯一数据源 —— session id 在 URL 上，刷新和分享都靠它把画布重建出来。
 */

import { apiDelete, apiGet, apiPatch, apiPost } from './client'
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
  /** 乐观锁版本：文档一变就自增，选区 overlay 凭它判断自己还作不作数 */
  revision: number
  assets: AssetOut[]
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------- 选区（M6）

export interface SelectionMarker {
  index: number
  x: number
  y: number
}

export interface SelectionOut {
  revision: number
  mask: AssetOut
  markers: SelectionMarker[]
}

export interface SelectPayload {
  revision: number
  points?: { x: number; y: number }[]
  strokes?: { x: number; y: number }[][]
  radius?: number
  append?: boolean
}

export const createSession = (payload: { asset_ids: string[]; title?: string }) =>
  apiPost<SessionOut>('/edit-sessions', payload)

export const listSessions = () => apiGet<SessionSummary[]>('/edit-sessions')

export const getSession = (id: string) => apiGet<SessionOut>(`/edit-sessions/${id}`)

export const renameSession = (id: string, title: string) =>
  apiPatch<SessionOut>(`/edit-sessions/${id}`, { title })

export const deleteSession = (id: string) => apiDelete<void>(`/edit-sessions/${id}`)

// ---------------------------------------------------------------- 选区（M6）

/** 点选 / 笔刷生成选区。409 = 画布已变，本地笔迹应当丢弃。 */
export const createSelection = (id: string, payload: SelectPayload) =>
  apiPost<SelectionOut>(`/edit-sessions/${id}/selection`, payload)

/** 恢复现场用。选区过期或不存在时后端返回 null，不是 404。 */
export const getSelection = (id: string) =>
  apiGet<SelectionOut | null>(`/edit-sessions/${id}/selection`)

export const clearSelection = (id: string) =>
  apiDelete<void>(`/edit-sessions/${id}/selection`)

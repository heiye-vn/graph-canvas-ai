/**
 * 撤销栈接口。
 *
 * 与 runs 那条 ADQ 无关 —— 这里的每一步都是**已经发生过的**，
 * 不需要流式通知，一次请求拿回新文档就够了。
 */

import { apiGet, apiPost } from './client'
import type { SessionOut } from './sessions'

export interface HistoryEntry {
  seq: number
  tool: string | null
  label: string
  changed: boolean
  created_at: string
}

export interface HistoryState {
  /** 指针位置：0 = 初始状态 */
  seq: number
  can_undo: boolean
  can_redo: boolean
  items: HistoryEntry[]
}

export interface TimeTravelResult {
  session: SessionOut
  label: string | null
  seq: number
  can_undo: boolean
  can_redo: boolean
}

export const getHistory = (sessionId: string) =>
  apiGet<HistoryState>(`/edit-sessions/${sessionId}/history`)

export const undoStep = (sessionId: string) =>
  apiPost<TimeTravelResult>(`/edit-sessions/${sessionId}/history/undo`, {})

export const redoStep = (sessionId: string) =>
  apiPost<TimeTravelResult>(`/edit-sessions/${sessionId}/history/redo`, {})

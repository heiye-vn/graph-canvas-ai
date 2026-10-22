/**
 * 工具与 Agent 接口。
 *
 * 前端**不硬编码任何工具清单**：工具名、标签、参数表单全部来自 `/api/tools`。
 * 后端加一个工具，这里一行都不用改（M4 的 DoD ②）。
 */

import { apiGet, apiPost } from './client'
import type { SessionOut } from './sessions'

export interface ToolParamMeta {
  name: string
  label: string
  description: string
  type: 'string' | 'number' | 'integer' | 'boolean' | 'enum'
  required: boolean
  default: unknown
  min?: number | null
  max?: number | null
  enum?: (string | number)[] | null
  agent_hidden: boolean
}

export interface ToolMeta {
  name: string
  label: string
  description: string
  group: string
  undoable: boolean
  params: ToolParamMeta[]
}

export interface InvokeResponse {
  tool: string
  message: string
  session: SessionOut
  /** 排队型工具（局部编辑等）提交出的任务 id；确定性工具为 null */
  run_id: string | null
}

export const listTools = () => apiGet<{ items: ToolMeta[] }>('/tools')
export const invokeTool = (name: string, session_id: string, params: Record<string, unknown>) =>
  apiPost<InvokeResponse>(`/tools/${name}/invoke`, {
    session_id,
    params,
  })

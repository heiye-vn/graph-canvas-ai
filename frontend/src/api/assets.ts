import { apiDelete, apiGet, apiPost } from './client'

export interface AssetOut {
  id: string
  kind: string
  mime: string
  width: number | null
  height: number | null
  size: number
  created_at: string
  /** 预签名临时 URL：桶是私有的，前端一律用它取图 */
  url: string
}

/**
 * 上传凭据。两种模式结构一致，只有 method / upload_url 不同：
 *   backend   -> POST 到本服务
 *   presigned -> PUT 到对象存储
 * 后端切换 ASSET_UPLOAD_MODE 时前端无需改动。
 */
export interface UploadTicket {
  mode: 'backend' | 'presigned'
  key: string
  upload_url: string
  method: 'POST' | 'PUT'
  headers: Record<string, string>
  expires_in: number
}

export const createUploadTicket = (payload: {
  filename: string
  mime: string
  size: number
  kind?: string
}) => apiPost<UploadTicket>('/assets/upload-ticket', payload)

export const confirmUpload = (payload: { key: string; mime: string; size: number }) =>
  apiPost<AssetOut>('/assets/confirm', payload)

export const listAssets = () => apiGet<{ items: AssetOut[] }>('/assets')

export const getAsset = (id: string) => apiGet<AssetOut>(`/assets/${id}`)

export const deleteAsset = (id: string) => apiDelete<void>(`/assets/${id}`)

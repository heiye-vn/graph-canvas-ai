import { apiDelete, apiGet, apiPost, tokenStore } from './client'

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
  /** 缩略图入口（服务端 307 到预签名小图）。卡片展示一律用它，看大图才用 url */
  thumb_url?: string | null
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

export const deleteAsset = (id: string) => apiDelete<void>(`/assets/${id}`)

/**
 * 卡片展示用的图片地址。
 *
 * 缩略图走 API（`/assets/{id}/thumb`），而 `<img src>` 带不了 Authorization 头 ——
 * 只能像 SSE 一样把令牌挂在 query 上。没有缩略图（如生成中的候选图）时回退原图，
 * 那是预签名地址，本身就不需要令牌。
 */
export function assetThumbSrc(asset: {
  thumb_url?: string | null
  url: string
}): string {
  if (!asset.thumb_url) return asset.url
  const token = tokenStore.get()
  return token
    ? `${asset.thumb_url}?token=${encodeURIComponent(token)}`
    : asset.thumb_url
}

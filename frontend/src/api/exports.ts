/**
 * 导出物料接口。
 *
 * 与单图导出（前端 stage.toDataURL）分工：
 *   - 单图 PNG：所见即所得，走前端，零往返
 *   - 投放尺寸 / 打包：要服务端拍平（含调色/裁剪/旋转）并落成资产，走这里
 */

import { API_BASE, apiPost, tokenStore } from './client'
import type { AssetOut } from './assets'

export const DELIVERY_RATIOS = ['1:1', '4:5', '9:16'] as const
export type DeliveryRatio = (typeof DELIVERY_RATIOS)[number]

export const RATIO_SIZES: Record<DeliveryRatio, string> = {
  '1:1': '1080 × 1080',
  '4:5': '1080 × 1350',
  '9:16': '1080 × 1920',
}

/** 把当前画布 letterbox 到选定比例（不裁切），结果落成会话素材。 */
export const createExportSizes = (sessionId: string, ratios: string[]) =>
  apiPost<{ items: AssetOut[] }>(
    `/edit-sessions/${sessionId}/export-sizes`,
    { ratios },
  )

/**
 * 打包下载 ZIP（含 manifest.json）。
 *
 * 不用 apiGet 是因为它假定 JSON 响应；这里要拿 blob。
 * 仍然手工带一次 token，避免绕过统一的鉴权约定。
 */
export async function downloadExportZip(
  sessionId: string,
  assetIds: string[],
  filename = 'export.zip',
): Promise<void> {
  const token = tokenStore.get()
  const query = encodeURIComponent(assetIds.join(','))
  const response = await fetch(
    `${API_BASE}/edit-sessions/${sessionId}/export?asset_ids=${query}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    },
  )
  if (!response.ok) {
    throw new Error(`打包失败（${response.status}）`)
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

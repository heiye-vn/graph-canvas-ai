/**
 * 上传领域逻辑。
 *
 * 这是「后端直传」与「预签名直传」的唯一分叉点：
 * 流程完全一致（拿 ticket → 按 method 上传 → confirm），
 * 只有第二步的实现方式不同。将来后端切到 presigned，这里不用改一行。
 */

import { confirmUpload, createUploadTicket } from '@/api/assets'
import type { AssetOut, UploadTicket } from '@/api/assets'
import { tokenStore } from '@/api/client'

export interface UploadOptions {
  kind?: string
  onTicket?: (ticket: UploadTicket) => void
}

export async function uploadAsset(file: File, options: UploadOptions = {}): Promise<AssetOut> {
  const ticket = await createUploadTicket({
    filename: file.name,
    mime: file.type,
    size: file.size,
    kind: options.kind ?? 'image',
  })
  options.onTicket?.(ticket)

  await putToTarget(ticket, file)
  return confirmUpload({ key: ticket.key, mime: file.type, size: file.size })
}

async function putToTarget(ticket: UploadTicket, file: File): Promise<void> {
  if (ticket.method === 'PUT') {
    // 预签名直传：直接 PUT 到对象存储，主体就是文件二进制
    const resp = await fetch(ticket.upload_url, {
      method: 'PUT',
      headers: ticket.headers,
      body: file,
    })
    if (!resp.ok) throw new Error(`上传到对象存储失败（${resp.status}）`)
    return
  }

  // 后端直传：multipart 带上 key 与文件
  const form = new FormData()
  form.append('key', ticket.key)
  form.append('file', file)
  const token = tokenStore.get()
  const resp = await fetch(ticket.upload_url, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`上传失败（${resp.status}）${detail}`)
  }
}

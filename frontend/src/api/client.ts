/**
 * HTTP 客户端。
 *
 * 两条 base 刻意分开：
 *   /api    —— 业务接口
 *   根路径  —— /health、/ready 探针与 /events（SSE），不挂业务前缀，
 *              参考项目也是这个做法，便于反向代理单独关闭缓冲
 */

export const API_BASE = '/api'
export const ROOT_BASE = ''

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public payload?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })

  if (!resp.ok) {
    let message = `请求失败（${resp.status}）`
    let payload: unknown
    try {
      payload = await resp.json()
      const detail = (payload as { detail?: string; message?: string } | null) ?? {}
      message = detail.detail ?? detail.message ?? message
    } catch {
      /* 非 JSON 响应，保留默认文案 */
    }
    throw new ApiError(resp.status, message, payload)
  }

  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(`${API_BASE}${path}`, init)
}

export function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return request<T>(`${API_BASE}${path}`, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
  })
}

export function rootGet<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(`${ROOT_BASE}${path}`, init)
}

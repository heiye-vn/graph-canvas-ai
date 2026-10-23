/**
 * HTTP 客户端。
 *
 * 只覆盖挂在 /api 下的业务接口。SSE（/events/*）与探针不走这里：
 * EventSource 需要把令牌放在 query 上，由 domain/events.ts 直接拼根路径 URL。
 *
 * 访问令牌集中在这里注入，业务模块不需要各自拼 Authorization。
 */

export const API_BASE = '/api'

const TOKEN_KEY = 'gca.access_token'

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

export const tokenStore = {
  get: (): string | null => localStorage.getItem(TOKEN_KEY),
  set: (token: string | null) => {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  },
}

/**
 * 令牌失效（401）时除了清 token，还要让鉴权 store 也回到未登录态，
 * 否则页面会停在「已登录但什么都取不到」的死状态里，不会跳回登录页。
 * 用回调注册而不是直接 import store，避免 client ↔ store 循环依赖。
 */
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get()

  const resp = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
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
    if (resp.status === 401 && token === tokenStore.get()) {
      tokenStore.set(null) // 令牌失效立即清理，避免带着坏 token 反复重试
      unauthorizedHandler?.()
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

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${API_BASE}${path}`, {
    method: 'PATCH',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(`${API_BASE}${path}`, { method: 'DELETE' })
}

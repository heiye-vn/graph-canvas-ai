import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiGet, setUnauthorizedHandler, tokenStore } from './client'

const unauthorized = vi.fn()
beforeEach(() => {
  vi.clearAllMocks()
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  })
  setUnauthorizedHandler(unauthorized)
})
afterEach(() => vi.unstubAllGlobals())

it('旧账号迟到的 401 不得退出新账号或清掉新 token', async () => {
  let respond!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => { respond = resolve })))
  tokenStore.set('old')
  const pending = apiGet('/assets').catch((error) => error)
  tokenStore.set('new')
  respond({ ok: false, status: 401, json: async () => ({ detail: '令牌过期' }) })
  await pending
  expect(tokenStore.get()).toBe('new')
  expect(unauthorized).not.toHaveBeenCalled()
})

it('当前 token 的 401 仍清理并通知退出', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) }))
  tokenStore.set('current')
  await apiGet('/assets').catch(() => undefined)
  expect(tokenStore.get()).toBeNull()
  expect(unauthorized).toHaveBeenCalledOnce()
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'

vi.mock('@/api/auth', () => ({ fetchMe: vi.fn(), login: vi.fn(), register: vi.fn() }))
import { fetchMe, login, register } from '@/api/auth'
import { tokenStore } from '@/api/client'
import { useAuthStore } from './authStore'

const user = (id: string) => ({ id, email: `${id}@example.com`, display_name: null, created_at: '' })
const response = (id: string) => ({ user: user(id), token: { access_token: id, token_type: 'bearer', expires_in: 60 } })
const deferred = <T,>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// 通过原型拿到 store 实际使用的客户端，不依赖新文件是否已经创建。
let clients: QueryClient[]
beforeEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  })
  clients = []
  const cancel = QueryClient.prototype.cancelQueries
  vi.spyOn(QueryClient.prototype, 'cancelQueries').mockImplementation(function (this: QueryClient, ...args) {
    clients.push(this)
    return cancel.apply(this, args)
  })
  useAuthStore.setState({ user: user('old'), loading: false })
  tokenStore.set('old')
})

describe('账号查询隔离', () => {
  it('退出时取消并清空实际客户端，迟到查询不能重新填缓存', async () => {
    useAuthStore.getState().signOut()
    expect(clients.length).toBeGreaterThan(0)
    const client = clients[0]
    client.setQueryData(['assets'], ['old-private-asset'])
    const late = deferred<string[]>()
    const pending = client.fetchQuery({ queryKey: ['sessions'], queryFn: () => late.promise }).catch(() => undefined)
    useAuthStore.getState().signOut()
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    late.resolve(['old-private-session'])
    await pending
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    expect(tokenStore.get()).toBeNull()
    expect(useAuthStore.getState()).toMatchObject({ user: null, loading: false })
  })

  it.each(['signIn', 'signUp'] as const)('%s 在发布新用户前取消并清空缓存', async (method) => {
    vi.mocked(login).mockResolvedValue(response('new'))
    vi.mocked(register).mockResolvedValue(response('new'))
    await useAuthStore.getState()[method]('new@example.com', 'password')
    expect(clients.length).toBeGreaterThan(0)
    const client = clients[0]
    client.setQueryData(['assets'], ['private'])
    let cacheAtPublish: unknown
    const unsubscribe = useAuthStore.subscribe(() => { cacheAtPublish = client.getQueryData(['assets']) })
    await useAuthStore.getState()[method]('new@example.com', 'password')
    unsubscribe()
    expect(cacheAtPublish).toBeUndefined()
    expect(useAuthStore.getState()).toMatchObject({ user: user('new'), loading: false })
  })

  it('退出后迟到的 bootstrap 不得恢复旧用户', async () => {
    const late = deferred<ReturnType<typeof user>>()
    vi.mocked(fetchMe).mockReturnValue(late.promise)
    const pending = useAuthStore.getState().bootstrap()
    useAuthStore.getState().signOut()
    late.resolve(user('old'))
    await pending
    expect(useAuthStore.getState().user).toBeNull()
  })

  it('旧 bootstrap 失败不能清掉新登录的 token', async () => {
    const late = deferred<ReturnType<typeof user>>()
    vi.mocked(fetchMe).mockReturnValue(late.promise)
    vi.mocked(login).mockResolvedValue(response('new'))
    const pending = useAuthStore.getState().bootstrap()
    await useAuthStore.getState().signIn('new@example.com', 'password')
    late.reject(new Error('旧请求失败'))
    await pending
    expect(tokenStore.get()).toBe('new')
    expect(useAuthStore.getState().user?.id).toBe('new')
  })

  it('退出后迟到的登录响应不能重新登录', async () => {
    const late = deferred<ReturnType<typeof response>>()
    vi.mocked(login).mockReturnValue(late.promise)
    const pending = useAuthStore.getState().signIn('old@example.com', 'password')
    useAuthStore.getState().signOut()
    late.resolve(response('old'))
    await pending
    expect(tokenStore.get()).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
  })
})

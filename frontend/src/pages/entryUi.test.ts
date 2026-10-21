import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'

const fixture = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, effects: [] as (() => unknown)[],
  location: { pathname: '/create', search: '?view=recent', hash: '#prompt', state: null as unknown },
  navigate: vi.fn(), mutate: vi.fn(), refetch: vi.fn(),
  auth: { user: null as unknown, loading: false, signIn: vi.fn(), signUp: vi.fn() },
  query: { data: undefined as unknown, isLoading: false, isError: false, error: null as Error | null },
}))
vi.mock('react', async (original) => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = fixture.cursor++
    if (!(index in fixture.slots)) fixture.slots[index] = typeof initial === 'function' ? initial() : initial
    return [fixture.slots[index], (next: unknown) => {
      fixture.slots[index] = typeof next === 'function' ? next(fixture.slots[index]) : next
    }]
  },
  useRef: (initial: unknown) => {
    const index = fixture.cursor++
    if (!(index in fixture.slots)) fixture.slots[index] = { current: initial }
    return fixture.slots[index]
  },
  useEffect: (effect: () => unknown) => { fixture.effects.push(effect) },
  useMemo: (compute: () => unknown) => compute(),
}))
vi.mock('react-router-dom', () => ({
  useNavigate: () => fixture.navigate, useLocation: () => fixture.location,
  Navigate: 'navigate', Outlet: 'outlet', Link: 'link',
}))
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ ...fixture.query, refetch: fixture.refetch }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ mutate: fixture.mutate, isPending: false }),
}))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => fixture.auth }))
vi.mock('@/hooks/useCreateSession', () => ({ useCreateSessionAndEdit: () => ({ mutate: vi.fn() }) }))
vi.mock('@/hooks/useRunStream', () => ({ useRunStream: () => ({}) }))
vi.mock('@/hooks/useCotStream', () => ({ useCotStream: () => ({}) }))
vi.mock('antd', () => ({
  Alert: 'alert', Button: 'button', Input: Object.assign('input', { TextArea: 'textarea' }),
  Popconfirm: 'popconfirm', Popover: 'popover', Tag: 'tag', Spin: 'spin',
  Form: Object.assign(() => null, { useForm: () => [{}], Item: 'item' }),
  Typography: { Text: 'text' }, Modal: 'modal', Empty: 'empty', Collapse: 'collapse',
}))

import ProtectedRoute from '@/components/ProtectedRoute'
import LoginPage from './LoginPage'
import CreatePage from './CreatePage'
import AssetsPage from './AssetsPage'
import ChatPanel from '@/components/editor/ChatPanel'
import PromptComposer from '@/components/landing/PromptComposer'

type Element = ReactElement<Record<string, any>>
function nodes(tree: unknown): Element[] {
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (!tree || typeof tree !== 'object' || !('props' in tree)) return []
  const element = tree as Element
  return [element, ...nodes(element.props.children)]
}
function render(component: () => unknown) {
  fixture.cursor = 0
  fixture.effects = []
  return component()
}
function textarea(tree: unknown) {
  return nodes(tree).find((element) => element.type === 'textarea')!
}
function event(nativeEvent: object, extra = {}) {
  return { key: 'Enter', shiftKey: false, nativeEvent, preventDefault: vi.fn(), ...extra }
}

beforeEach(() => {
  vi.clearAllMocks()
  fixture.slots = []
  fixture.auth.user = null
  fixture.query = { data: undefined, isLoading: false, isError: false, error: null }
  fixture.location = { pathname: '/create', search: '?view=recent', hash: '#prompt', state: null }
})

describe('入口状态接力', () => {
  it('路由守卫保留路径、查询、锚点及原 state', () => {
    fixture.location.state = { prompt: '首页画面', extra: 'keep' }
    const tree = render(() => ProtectedRoute({})) as Element
    fixture.location.state = tree.props.state
    fixture.auth.user = { id: 'user' }
    const login = render(LoginPage) as Element
    expect(login.props.to).toBe('/create?view=recent#prompt')
    expect(login.props.state).toEqual({ prompt: '首页画面', extra: 'keep' })
  })

  it('账号变化会重建受保护页面，避免保留上一账号的本地状态', () => {
    fixture.auth.user = { id: 'first' }
    const first = render(() => ProtectedRoute({})) as Element
    fixture.auth.user = { id: 'second' }
    const second = render(() => ProtectedRoute({})) as Element
    expect(first.key).toBe('first')
    expect(second.key).toBe('second')
  })

  it.each(['https://example.com', '//example.com', '/login', '/login?next=/assets'])('不接受无效登录目标 %s', (next) => {
    fixture.location.state = { next }
    fixture.auth.user = { id: 'user' }
    expect((render(LoginPage) as Element).props.to).toBe('/create')
  })

  it('首页 prompt 只填入不自动生成，并 replace 消费 state、保留其他 state', () => {
    fixture.location.state = { prompt: '首页画面', extra: 'keep' }
    let tree = render(CreatePage)
    for (const effect of fixture.effects) effect()
    tree = render(CreatePage)
    expect(textarea(tree).props.value).toBe('首页画面')
    expect(fixture.mutate).not.toHaveBeenCalled()
    expect(fixture.navigate).toHaveBeenCalledWith('/create?view=recent#prompt', {
      replace: true, state: { extra: 'keep' },
    })
  })
})

describe.each([
  ['创作', () => CreatePage(), false],
  ['对话', () => ChatPanel({ sessionId: 'session' }), false],
  ['首页', () => PromptComposer(), true],
] as const)('%s 输入法保护', (_name, component, ctrlKey) => {
  it('合成态和 keyCode 229 的回车不提交、不阻止选词', () => {
    let tree = render(component)
    textarea(tree).props.onChange({ target: { value: '输入内容' } })
    tree = render(component)
    for (const nativeEvent of [{ isComposing: true }, { keyCode: 229 }]) {
      const key = event(nativeEvent, { ctrlKey })
      textarea(tree).props.onKeyDown(key)
      expect(key.preventDefault).not.toHaveBeenCalled()
    }
    expect(fixture.mutate).not.toHaveBeenCalled()
    expect(fixture.navigate).not.toHaveBeenCalled()
  })

  it('普通回车仍提交，Shift+Enter 不提交', () => {
    let tree = render(component)
    textarea(tree).props.onChange({ target: { value: '输入内容' } })
    tree = render(component)
    textarea(tree).props.onKeyDown(event({}, { ctrlKey: false, shiftKey: true }))
    expect(fixture.mutate).not.toHaveBeenCalled()
    expect(fixture.navigate).not.toHaveBeenCalled()
    textarea(tree).props.onKeyDown(event({}, { ctrlKey }))
    expect(fixture.mutate.mock.calls.length + fixture.navigate.mock.calls.length).toBe(1)
  })
})

describe.each([
  ['创作历史', () => CreatePage()], ['素材库', () => AssetsPage()],
  ['对话历史', () => ChatPanel({ sessionId: 'session' })],
] as const)('%s 查询错误', (_name, component) => {
  it('查询失败展示错误与重试，不当作空数据', () => {
    fixture.query = { data: undefined, isLoading: false, isError: true, error: new Error('网络暂不可用') }
    const tree = render(component)
    const alert = nodes(tree).find((element) => element.type === 'alert')
    expect(alert).toBeDefined()
    expect(JSON.stringify(alert?.props)).toContain('网络暂不可用')
    const retry = nodes(alert?.props.action).find((element) => element.props.onClick)
    expect(retry).toBeDefined()
    retry!.props.onClick()
    expect(fixture.refetch).toHaveBeenCalled()
  })
})

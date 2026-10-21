import { beforeEach, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'

const fixture = vi.hoisted(() => ({
  sessionId: 'a', cursor: 0, slots: [] as unknown[], effects: [] as (() => void | (() => void))[],
  mutations: [] as any[], navigate: vi.fn(), refetch: vi.fn(), success: vi.fn(), error: vi.fn(),
  sessionError: null as Error | null, sessionsError: null as Error | null,
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
  useEffect: (effect: () => void | (() => void)) => { fixture.effects.push(effect) },
  useMemo: (compute: () => unknown) => compute(),
}))
vi.mock('react-router-dom', () => ({ useParams: () => ({ sessionId: fixture.sessionId }), useNavigate: () => fixture.navigate, Link: 'link' }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: ({ queryKey }: { queryKey: string[] }) => {
    const error = queryKey[0] === 'session' ? fixture.sessionError : fixture.sessionsError
    return { data: queryKey[0] === 'session' ? { id: fixture.sessionId, title: fixture.sessionId, doc: { canvas: {} }, assets: [] } : [],
      isLoading: false, isError: !!error, error, refetch: fixture.refetch }
  },
  useMutation: (options: unknown) => {
    fixture.mutations.push(options)
    return { isPending: false, mutate: vi.fn() }
  },
}))
vi.mock('antd', () => ({ Alert: 'alert', Button: 'button', Checkbox: 'checkbox', Select: 'select', Skeleton: 'skeleton', Result: 'result',
  Empty: Object.assign('empty', { PRESENTED_IMAGE_SIMPLE: '' }), message: { success: fixture.success, error: fixture.error } }))
vi.mock('@/domain/layerDoc', () => ({ topmostVisibleImageLayer: () => null }))
vi.mock('@/api/exports', () => ({ DELIVERY_RATIOS: ['1:1', '4:5', '9:16'], RATIO_SIZES: {}, createExportSizes: vi.fn(), downloadExportZip: vi.fn() }))

import ExportPage from './ExportPage'
import { downloadExportZip } from '@/api/exports'
import { ApiError } from '@/api/client'

type Element = ReactElement<Record<string, any>>
function nodes(tree: unknown): Element[] {
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (!tree || typeof tree !== 'object' || !('props' in tree)) return []
  const element = tree as Element
  return [element, ...nodes(element.props.children)]
}
function render() {
  fixture.cursor = 0
  fixture.effects = []
  const root = ExportPage() as Element
  return typeof root.type === 'function' ? (root.type as (props: unknown) => unknown)(root.props) : root
}
function packButton(tree: unknown) {
  return nodes(tree).find((element) => element.type === 'button' && JSON.stringify(element.props.children).includes('打包'))!
}
beforeEach(() => {
  vi.clearAllMocks()
  fixture.sessionId = 'a'
  fixture.slots = []
  fixture.mutations = []
  fixture.sessionError = null
  fixture.sessionsError = null
})

it('session 切换使用不同组件 key，重置结果、选择与忙碌状态', () => {
  const first = ExportPage() as Element
  fixture.sessionId = 'b'
  const second = ExportPage() as Element
  expect(first.key).toBe('a')
  expect(second.key).toBe('b')
})

it('卸载后迟到的生成成功和失败不再写状态或弹提示', () => {
  render()
  const cleanups = fixture.effects.map((effect) => effect())
  const oldMutation = fixture.mutations.at(-1)
  for (const cleanup of cleanups) cleanup?.()
  const oldSlots = [...fixture.slots]
  oldMutation.onSuccess({ items: [{ id: 'old' }] })
  oldMutation.onError(new Error('旧会话失败'))
  expect(fixture.slots).toEqual(oldSlots)
  expect(fixture.success).not.toHaveBeenCalled()
  expect(fixture.error).not.toHaveBeenCalled()
})

it('当前会话生成仍可选择打包；卸载后取消 ZIP 且不弹旧提示', async () => {
  render()
  const cleanups = fixture.effects.map((effect) => effect())
  fixture.mutations.at(-1).onSuccess({ items: [{ id: 'asset' }] })
  fixture.success.mockClear()
  const tree = render()
  expect(packButton(tree).props.disabled).toBe(false)
  let finish!: () => void
  vi.mocked(downloadExportZip).mockImplementation(() => new Promise<void>((resolve) => { finish = resolve }))
  const pending = packButton(tree).props.onClick()
  const call = vi.mocked(downloadExportZip).mock.calls[0]
  const signal = (call as unknown[])[3] as AbortSignal | undefined
  for (const cleanup of cleanups) cleanup?.()
  expect(signal?.aborted).toBe(true)
  finish()
  await pending
  expect(fixture.success).not.toHaveBeenCalled()
})

it('真实 404 仍明确提示会话不存在', () => {
  fixture.sessionError = new ApiError(404, '会话不存在')
  const result = nodes(render()).find((element) => element.type === 'result')
  expect(result?.props.status).toBe('404')
  expect(result?.props.title).toBe('找不到这个编辑会话')
})

it.each(['session', 'sessions'])('%s 查询失败显示真实错误并可重试，不误报 404 或空列表', (kind) => {
  if (kind === 'session') fixture.sessionError = new Error('网络暂不可用')
  else fixture.sessionsError = new Error('网络暂不可用')
  const tree = render()
  const error = nodes(tree).find((element) => ['alert', 'result'].includes(element.type as string) && JSON.stringify(element.props).includes('网络暂不可用'))
  expect(error).toBeDefined()
  const retry = [...nodes(error?.props.extra), ...nodes(error?.props.action)].find((element) => element.props.onClick)
  expect(retry).toBeDefined()
  retry!.props.onClick()
  expect(fixture.refetch).toHaveBeenCalled()
})

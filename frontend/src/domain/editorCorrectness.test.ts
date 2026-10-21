import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import type { Layer, LayerDocument } from './layerDoc'

// 用轻量 Hook 执行器验证状态流，不引入 DOM 或新的测试依赖。
const runtime = vi.hoisted(() => ({ current: null as any, query: null as any, mutation: null as any, rendered: null as any, stage: null as any, unmount: vi.fn() }))
vi.mock('react', async (original) => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => runtime.current.state(initial),
  useRef: (initial: unknown) => runtime.current.ref(initial),
  useMemo: (fn: () => unknown, deps: unknown[]) => runtime.current.memo(fn, deps),
  useCallback: (fn: unknown, deps: unknown[]) => runtime.current.memo(() => fn, deps),
  useEffect: (fn: () => unknown, deps: unknown[]) => runtime.current.effect(fn, deps),
}))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: runtime.query, isLoading: false }),
  useMutation: (options: unknown) => { runtime.mutation = options; return { reset: vi.fn(), mutate: vi.fn() } },
}))
vi.mock('antd', () => ({ Button: 'Button', Slider: 'Slider', Input: 'Input', InputNumber: 'InputNumber', Select: 'Select', Switch: 'Switch', Tooltip: 'Tooltip' }))
vi.mock('@ant-design/icons', () => ({ CloseOutlined: 'CloseOutlined', LockOutlined: 'LockOutlined', ThunderboltOutlined: 'ThunderboltOutlined', ToolOutlined: 'ToolOutlined' }))
vi.mock('@/api/tools', () => ({ invokeTool: vi.fn(), listTools: vi.fn() }))
vi.mock('react-konva', () => Object.fromEntries(['Circle', 'Group', 'Image', 'Layer', 'Line', 'Rect', 'Stage', 'Text', 'Transformer'].map((name) => [name, name])))
vi.mock('react-dom/client', () => ({ createRoot: () => ({
  render: (tree: any) => { runtime.rendered = tree; tree.props.ref.current = runtime.stage },
  unmount: runtime.unmount,
}) }))
vi.mock('react-dom', () => ({ flushSync: (fn: () => void) => fn() }))

import AdjustPanel from '@/components/editor/AdjustPanel'
import ToolPanel from '@/components/editor/ToolPanel'
import * as canvas from '@/components/editor/CanvasStage'
import { useLoadedImages } from '@/components/editor/useLoadedImages'
import { invokeTool } from '@/api/tools'

function hooks<T>(render: () => T) {
  const slots: any[] = []
  let index = 0
  let dirty = true
  let effects: Array<() => void> = []
  const changed = (a: unknown[] | undefined, b: unknown[]) => !a || a.length !== b.length || b.some((v, i) => !Object.is(v, a[i]))
  const dispatcher = {
    state(initial: any) {
      const i = index++
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial
      return [slots[i], (value: any) => { const next = typeof value === 'function' ? value(slots[i]) : value; if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true } }]
    },
    ref(initial: any) { const i = index++; return slots[i] ??= { current: initial } },
    memo(fn: () => unknown, deps: unknown[]) { const i = index++; if (changed(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() }; return slots[i].value },
    effect(fn: () => any, deps: unknown[]) {
      const i = index++
      if (changed(slots[i]?.deps, deps)) effects.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: fn() } })
    },
  }
  return {
    render() {
      let result!: T
      let passes = 0
      do {
        if (++passes > 20) throw new Error('Hook 未收敛')
        dirty = false; index = 0; effects = []; runtime.current = dispatcher
        result = render(); effects.forEach((fn) => fn())
      } while (dirty)
      return result
    },
    dispose() { slots.forEach((slot) => slot?.cleanup?.()) },
  }
}

function nodes(tree: any, type: string): any[] {
  if (!tree || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap((child) => nodes(child, type))
  return [...(tree.type === type ? [tree] : []), ...nodes(tree.props?.children, type)]
}
const zero = { brightness: 0, contrast: 0, highlights: 0, shadows: 0, temperature: 0, tint: 0, saturation: 0, vibrance: 0, sharpness: 0, clarity: 0, vignette: 0 }
function layer(id = 'bottom'): Layer {
  return { id, name: id, type: 'image', visible: true, locked: false, opacity: 1, transform: { x: 0, y: 0, width: 100, height: 80, rotation: 0, flip_x: false, flip_y: false }, source: { asset_id: id }, adjustments: { ...zero }, crop: null }
}
function doc(): LayerDocument { return { version: 1, canvas: { width: 100, height: 80, background: '#ffffff' }, layers: [layer(), layer('top')], active_layer_id: null } }
const image = () => ({ complete: true, naturalWidth: 100, naturalHeight: 80 }) as HTMLImageElement
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })

describe('调色持久值与撤销', () => {
  it('已保存的非零调色不脏，归零后可应用', () => {
    const target = { ...layer(), adjustments: { ...zero, brightness: 30 } }
    const preview = vi.fn()
    const view = hooks(() => AdjustPanel({ layer: target, onPreview: preview, onApply: vi.fn() }))
    let buttons = nodes(view.render(), 'Button')
    expect(buttons[1].props.disabled).toBe(true)
    buttons[0].props.onClick()
    buttons = nodes(view.render(), 'Button')
    expect(buttons[1].props.disabled).toBe(false)
  })
  it('同层撤销同步滑杆并清除预览，等值 refetch 不覆盖草稿', () => {
    let target = { ...layer(), adjustments: { ...zero, brightness: 30 } }
    const preview = vi.fn()
    const view = hooks(() => AdjustPanel({ layer: target, onPreview: preview, onApply: vi.fn() }))
    nodes(view.render(), 'Slider')[0].props.onChange(60)
    target = { ...target, adjustments: { ...target.adjustments } }
    expect(nodes(view.render(), 'Slider')[0].props.value).toBe(60)
    target = { ...target, adjustments: { ...zero, brightness: 10 } }
    expect(nodes(view.render(), 'Slider')[0].props.value).toBe(10)
    expect(preview).toHaveBeenLastCalledWith(null)
  })
})

describe('工具选层绑定', () => {
  const tool = { name: 'set_layer_text', label: '改文字', params: [{ name: 'layer' }, { name: 'text', default: null }] }
  it('改文案使用选中层 id 和原文，换层后清掉上一层草稿', async () => {
    runtime.query = { items: [tool] }
    let target = { ...layer('text-a'), type: 'text' as const, text: { text: '原文 A', font_size: 24, fill: '#000000' } }
    const view = hooks(() => ToolPanel({ sessionId: 's', selected: 'set_layer_text', selectedLayer: target } as any))
    let tree = view.render()
    const textField = tree!.props.children.flat(Infinity).find((node: any) => node?.props?.param?.name === 'text')
    expect(textField.props.value).toBe('原文 A')
    textField.props.onChange('草稿 A')
    view.render()
    await runtime.mutation.mutationFn()
    expect(invokeTool).toHaveBeenLastCalledWith('set_layer_text', 's', expect.objectContaining({ layer: 'text-a', text: '草稿 A' }))
    target = { ...target, id: 'text-b', text: { ...target.text, text: '原文 B' } }
    tree = view.render()
    expect(tree).toBeTruthy()
    await runtime.mutation.mutationFn()
    expect(invokeTool).toHaveBeenLastCalledWith('set_layer_text', 's', expect.objectContaining({ layer: 'text-b', text: '原文 B' }))
  })
  it('普通图层工具显式绑定选中层，不回落到最上层', async () => {
    runtime.query = { items: [{ ...tool, name: 'rename_layer' }] }
    const view = hooks(() => ToolPanel({ sessionId: 's', selected: 'rename_layer', selectedLayer: layer('bottom') }))
    view.render()
    await runtime.mutation.mutationFn()
    expect(invokeTool).toHaveBeenLastCalledWith('rename_layer', 's', { layer: 'bottom' })
  })
  it('未选层或非文字层时禁止改文案', () => {
    runtime.query = { items: [tool] }
    let target: Layer | null = layer()
    const view = hooks(() => ToolPanel({ sessionId: 's', selected: 'set_layer_text', selectedLayer: target }))
    expect(nodes(view.render(), 'Button')[0].props.disabled).toBe(true)
    target = null
    expect(nodes(view.render(), 'Button')[0].props.disabled).toBe(true)
  })
  it('关闭受控工具后不从 localName 复活', () => {
    runtime.query = { items: [{ ...tool, name: 'rename_layer' }] }
    let selected: string | null = null
    const view = hooks(() => ToolPanel({ sessionId: 's', selected, onSelect: (name) => { selected = name || null } }))
    nodes(view.render(), 'Select')[0].props.onChange('rename_layer')
    view.render()
    selected = null
    expect(nodes(view.render(), 'Select')).toHaveLength(1)
  })
})

describe('图片重新加载', () => {
  it('失败后仅签名更新也会真正加载；成功缓存仍复用', async () => {
    const requests: any[] = []
    class FakeImage { crossOrigin = ''; onload: any; onerror: any; decode = () => Promise.resolve(); set src(url: string) { requests.push({ url, image: this }) } }
    vi.stubGlobal('Image', FakeImage)
    vi.stubGlobal('window', { setTimeout: (fn: () => void) => fn() })
    let urls = { a: '/asset?old' }
    const view = hooks(() => useLoadedImages(urls))
    view.render()
    requests[0].image.onerror(); requests[1].image.onerror()
    await settle()
    expect(view.render().failed).toEqual(['a'])
    urls = { a: '/asset?new' }
    view.render()
    expect(requests.at(-1).url).toBe('/asset?new')
    requests.at(-1).image.onload()
    await settle()
    expect(view.render().failed).toEqual([])
    const count = requests.length
    urls = { a: '/asset?newer' }; view.render()
    expect(requests).toHaveLength(count)
    view.dispose()
  })
  it('相同 URL 的手动 reload 重试失败图片，但不重复下载成功项', async () => {
    const requests: any[] = []
    class FakeImage { onload: any; onerror: any; decode = () => Promise.resolve(); set src(url: string) { requests.push({ url, image: this }) } }
    vi.stubGlobal('Image', FakeImage)
    vi.stubGlobal('window', { setTimeout: (fn: () => void) => fn() })
    const view = hooks(() => useLoadedImages({ a: '/a', b: '/b' }))
    view.render()
    requests[0].image.onload(); requests[1].image.onerror(); requests[2].image.onerror()
    await settle()
    expect(view.render().failed).toEqual(['b'])
    view.render().reload(); view.render()
    expect(requests.map((request) => request.url)).toEqual(['/a', '/b', '/b', '/b'])
    requests[3].image.onload(); await settle()
    expect(view.render().failed).toEqual([])
    expect(Object.keys(view.render().images)).toEqual(['a', 'b'])
    view.dispose()
  })
  it('旧请求晚完成不会覆盖当前路径或污染缓存', async () => {
    const requests: any[] = []
    class FakeImage { onload: any; decode = () => Promise.resolve(); set src(url: string) { requests.push({ url, image: this }) } }
    vi.stubGlobal('Image', FakeImage)
    let urls = { a: '/old' }
    const view = hooks(() => useLoadedImages(urls))
    view.render(); urls = { a: '/new' }; view.render()
    requests[1].image.onload(); await settle()
    expect(view.render().images.a).toBe(requests[1].image)
    requests[0].image.onload(); await settle()
    expect(view.render().images.a).toBe(requests[1].image)
    urls = { a: '/new?signature' }; view.render()
    expect(requests).toHaveLength(2)
    view.dispose()
  })
  it('解码失败不能视为图片就绪', async () => {
    const requests: any[] = []
    class FakeImage { onload: any; decode = () => Promise.reject(new Error('解码失败')); set src(url: string) { requests.push({ url, image: this }) } }
    vi.stubGlobal('Image', FakeImage)
    vi.stubGlobal('window', { setTimeout: (fn: () => void) => fn() })
    const view = hooks(() => useLoadedImages({ a: '/a' }))
    view.render(); requests[0].image.onload(); await settle()
    requests[1].image.onload(); await settle()
    expect(view.render().images).toEqual({})
    expect(view.render().failed).toEqual(['a'])
    expect(view.render().pending).toBe(false)
    view.dispose()
  })
  it('新素材待加载时不暴露旧路径图片，也不因旧计数误报就绪', async () => {
    const requests: any[] = []
    class FakeImage { onload: any; decode = () => Promise.resolve(); set src(url: string) { requests.push({ url, image: this }) } }
    vi.stubGlobal('Image', FakeImage)
    let urls = { a: '/old' }
    const view = hooks(() => useLoadedImages(urls))
    view.render(); requests[0].image.onload(); await settle()
    expect(view.render().images.a).toBeTruthy()
    urls = { a: '/new' }
    const next = view.render()
    expect(next.pending).toBe(true)
    expect(next.images.a).toBeUndefined()
    view.dispose()
  })
})

describe('纯文档 PNG 导出', () => {
  it('独立原分辨率 Stage 只画持久文档，不带辅助层、对比或预览', () => {
    const remove = vi.fn()
    vi.stubGlobal('document', { createElement: () => ({ remove }), body: { appendChild: vi.fn() } })
    runtime.stage = { toDataURL: vi.fn(() => 'data:image/png;base64,ok') }
    const data = doc()
    const exportPng = (canvas as any).exportDocumentPng
    expect(typeof exportPng).toBe('function')
    expect(exportPng(data, { bottom: image(), top: image() })).toBe('data:image/png;base64,ok')
    const stage = runtime.rendered as ReactElement<any>
    expect(stage.props).toMatchObject({ width: 100, height: 80 })
    expect(stage.props.scaleX ?? 1).toBe(1)
    const content = stage.props.children
    const tree = typeof content.type === 'function' ? content.type(content.props) : content
    expect(nodes(tree, 'Transformer')).toHaveLength(0)
    expect(nodes(tree, 'Circle')).toHaveLength(0)
    const layers = nodes(tree, 'Layer')[0].props.children.flat(Infinity).filter((node: any) => node?.props?.layer)
    expect(layers.map((node: any) => node.props.layer.id)).toEqual(['bottom', 'top'])
    expect(layers.every((node: any) => !node.props.preview && !node.props.interactive)).toBe(true)
    expect(runtime.unmount).toHaveBeenCalled()
    expect(remove).toHaveBeenCalled()
  })
  it('Konva 吞掉跨域错误返回空数据时仍报错，不能下载空 PNG', () => {
    vi.stubGlobal('document', { createElement: () => ({ remove: vi.fn() }) })
    runtime.stage = { toDataURL: vi.fn(() => '') }
    expect(() => canvas.exportDocumentPng(doc(), { bottom: image(), top: image() })).toThrow(/导出/)
  })
  it('未就绪或失败图片阻止下载，隐藏图片不阻塞，导出异常仍清理', () => {
    const exportPng = (canvas as any).exportDocumentPng
    expect(typeof exportPng).toBe('function')
    expect(() => exportPng(doc(), {})).toThrow(/图片.*(未就绪|未加载)/)
    expect(() => exportPng(doc(), { bottom: { ...image(), complete: false }, top: image() })).toThrow(/图片/)
    const remove = vi.fn()
    vi.stubGlobal('document', { createElement: () => ({ remove }), body: { appendChild: vi.fn() } })
    runtime.stage = { toDataURL: vi.fn(() => { throw new Error('跨域限制') }) }
    const data = doc(); data.layers[1].visible = false
    expect(() => exportPng(data, { bottom: image() })).toThrow('跨域限制')
    expect(remove).toHaveBeenCalled()
    expect(runtime.unmount).toHaveBeenCalled()
  })
})

it('局部编辑由服务端采用，前端不再自动 add_image_layer', () => {
  const source = readFileSync(new URL('../pages/EditorPage.tsx', import.meta.url), 'utf8')
  const queued = source.match(/const DOCUMENT_QUEUED_TOOLS = new Set\(\[([\s\S]*?)\]\)/)?.[1] ?? ''
  expect(queued).toContain('"erase_region"')
  expect(queued).toContain('"replace_region"')
  expect(source).not.toMatch(/name:\s*["']add_image_layer["']/)
  expect(source).toMatch(/selectedLayer=\{selectedLayer\}/)
  expect(source).toMatch(/await session\.refetch\(\)[\s\S]*?reload\(\)/)
  expect(source).toContain('message.error(')
})

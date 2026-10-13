/**
 * 图层文档领域层 —— 与后端 `app/schemas/layer_doc.py` 一比一对应。
 *
 * ⚠️ 改这个文件必须同时看一眼后端那份：这是 UI 与 Agent 之间的契约，
 * 两边漂移的结果不是报错，而是「画布上显示的不是工具实际改的东西」。
 *
 * 三条约定（与后端注释同款，改代码前先看）：
 *   1. `layers` 数组**从下到上**（index 0 最底）。面板显示要倒过来。
 *   2. `id` 唯一；`name` 允许重复，按名查找取**最上层**。
 *   3. 文档里只有 asset_id 引用，取图地址要用 AssetOut 里的预签名 URL。
 *
 * 这里全部是**纯函数**：不改入参，返回新文档。
 * UI（选中态）与对话工具（M4 起）都必须走同一套，否则同一句指令在两个入口
 * 会落到不同的图层上。
 */

export type LayerType = 'image' | 'text' | 'shape'

export interface LayerTransform {
  x: number
  y: number
  /** 为空表示「用素材原始尺寸」 */
  width: number | null
  height: number | null
  rotation: number
}

export interface ImageSource {
  asset_id: string
}

export interface TextContent {
  text: string
  font_size: number
  fill: string
}

export interface Adjustments {
  brightness: number
  contrast: number
  saturation: number
  temperature: number
}

export interface Layer {
  id: string
  name: string
  type: LayerType
  visible: boolean
  locked: boolean
  opacity: number
  transform: LayerTransform
  source?: ImageSource
  text?: TextContent
  adjustments: Adjustments
}

export interface LayerCanvas {
  width: number
  height: number
  background: string | null
}

export interface LayerDocument {
  version: number
  canvas: LayerCanvas
  layers: Layer[]
  active_layer_id: string | null
}

export type LayerRef = string | { id?: string; name?: string } | null | undefined

export class LayerNotFoundError extends Error {
  constructor(ref?: unknown) {
    const detail = ref === undefined || ref === null ? '' : `：${String(ref)}`
    super(`找不到匹配的图层${detail}`)
    this.name = 'LayerNotFoundError'
  }
}

/** 从最上层到最底层 —— 图层面板渲染与「按名查找」都用这个顺序。 */
export function topDown(doc: LayerDocument): Layer[] {
  return [...doc.layers].reverse()
}

/** 默认图层：最上层**可见**的 image 层。文字/形状层没有像素来源，不作默认目标。 */
export function topmostVisibleImageLayer(doc: LayerDocument): Layer | undefined {
  return topDown(doc).find((layer) => layer.visible && layer.type === 'image')
}

/**
 * 定位图层 —— UI 选中态与工具调用的唯一入口。
 *
 * 找不到一律抛 LayerNotFoundError。**绝不悄悄回退到「第一个图层」**：
 * 那会让用户以为在改 A，实际改了 B。
 */
export function resolveLayer(doc: LayerDocument, ref: LayerRef = null): Layer {
  let wanted: string | undefined

  if (ref && typeof ref === 'object') {
    wanted = ref.id ?? ref.name
  } else if (typeof ref === 'string') {
    wanted = ref
  }

  if (!wanted) {
    const fallback = topmostVisibleImageLayer(doc)
    if (!fallback) throw new LayerNotFoundError()
    return fallback
  }

  const byId = doc.layers.find((layer) => layer.id === wanted)
  if (byId) return byId

  const byName = topDown(doc).find((layer) => layer.name === wanted)
  if (byName) return byName

  throw new LayerNotFoundError(wanted)
}

function commit(base: LayerDocument, layers: Layer[], patch: Partial<LayerDocument> = {}) {
  return { ...base, ...patch, layers }
}

/** 追加为最上层。 */
export function addLayer(doc: LayerDocument, layer: Layer): LayerDocument {
  return commit(doc, [...doc.layers, layer])
}

export function removeLayer(doc: LayerDocument, layerId: string): LayerDocument {
  const remaining = doc.layers.filter((layer) => layer.id !== layerId)
  if (remaining.length === doc.layers.length) throw new LayerNotFoundError(layerId)
  return {
    ...doc,
    layers: remaining,
    active_layer_id: doc.active_layer_id === layerId ? null : doc.active_layer_id,
  }
}

export function updateLayer(
  doc: LayerDocument,
  layerId: string,
  patch: Partial<Layer>,
): LayerDocument {
  let touched = false
  const layers = doc.layers.map((layer) => {
    if (layer.id !== layerId) return layer
    touched = true
    return { ...layer, ...patch }
  })
  if (!touched) throw new LayerNotFoundError(layerId)
  return commit(doc, layers)
}

export function setLayerVisible(
  doc: LayerDocument,
  layerId: string,
  visible: boolean,
): LayerDocument {
  return updateLayer(doc, layerId, { visible })
}

export function setActiveLayer(doc: LayerDocument, layerId: string | null): LayerDocument {
  if (layerId !== null && !doc.layers.some((layer) => layer.id === layerId)) {
    throw new LayerNotFoundError(layerId)
  }
  return { ...doc, active_layer_id: layerId }
}

/**
 * 把某张候选图切为「当前图」：它可见，其余**图像层**隐藏。
 *
 * 刻意只动 image 层 —— 面板上的文字层 / 形状层属于用户自己加的东西，
 * 切一张候选图不该顺手把它们也藏了。
 */
export function switchCurrentImage(doc: LayerDocument, layerId: string): LayerDocument {
  const target = resolveLayer(doc, layerId)
  if (target.type !== 'image') throw new Error('当前图只能是图像层')

  const layers = doc.layers.map((layer) =>
    layer.type === 'image' ? { ...layer, visible: layer.id === target.id } : layer,
  )
  return commit(doc, layers, { active_layer_id: target.id })
}

export function layerSourceAssetId(layer: Layer): string | null {
  return layer.source?.asset_id ?? null
}

/** 文档里用到的全部素材 id（去重，从底到顶）。渲染时按 id 找预签名 URL。 */
export function referencedAssetIds(doc: LayerDocument): string[] {
  const ids: string[] = []
  for (const layer of doc.layers) {
    const assetId = layerSourceAssetId(layer)
    if (assetId && !ids.includes(assetId)) ids.push(assetId)
  }
  return ids
}

export interface LayerRect {
  x: number
  y: number
  width: number
  height: number
  rotation: number
}

/**
 * 图层在画布上的最终矩形。
 *
 * 缺宽高时**回退到画布尺寸**而不是 0：素材尺寸未知的情况多半是还没探测出来，
 * 画成 0 会让人以为图丢了。
 */
export function layerRect(layer: Layer, canvas: LayerCanvas): LayerRect {
  return {
    x: layer.transform.x,
    y: layer.transform.y,
    width: layer.transform.width ?? canvas.width,
    height: layer.transform.height ?? canvas.height,
    rotation: layer.transform.rotation,
  }
}

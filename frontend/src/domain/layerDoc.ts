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

export interface LayerCrop {
  /** 相对**素材原始像素**的裁剪窗口 */
  x: number
  y: number
  width: number
  height: number
}

export interface LayerTransform {
  x: number
  y: number
  /** 为空表示「用素材原始尺寸」 */
  width: number | null
  height: number | null
  rotation: number
  flip_x: boolean
  flip_y: boolean
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
  /** 只影响亮部 */
  highlights: number
  /** 只影响暗部 */
  shadows: number
  temperature: number
  /** 正品红、负绿 */
  tint: number
  saturation: number
  /** 自然饱和度：本来就是灰的像素多改一点 */
  vibrance: number
  sharpness: number
  /** 更大半径的局部对比 */
  clarity: number
  /** 0~100，只加暗 */
  vignette: number
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
  /** 没有裁剪时为 null —— 与后端 Layer.crop 一致 */
  crop: LayerCrop | null
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

/** 从最上层到最底层 —— 图层面板渲染与「按名查找」都用这个顺序。 */
export function topDown(doc: LayerDocument): Layer[] {
  return [...doc.layers].reverse()
}

/** 默认图层：最上层**可见**的 image 层。文字/形状层没有像素来源，不作默认目标。 */
export function topmostVisibleImageLayer(doc: LayerDocument): Layer | undefined {
  return topDown(doc).find((layer) => layer.visible && layer.type === 'image')
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

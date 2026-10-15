/**
 * Konva 画布。
 *
 * 这个组件做的唯一一件事：**按图层文档渲染**。它不做任何编辑操作，
 * 也不持有文档之外的状态 —— 文档是唯一真相源，画布只是它的一个投影。
 * 好处是「画布上显示的」和「工具实际改的」永远是一份东西。
 *
 * 缩放只有一个 scale：Stage 尺寸 = 画布尺寸 × scale，坐标仍是文档里的画布像素。
 * 这样以后加节点变换/选区时不用做「屏幕坐标 ⇄ 文档坐标」的第二套换算。
 *
 * M5.5 起支持两种缩放：`fit`（贴齐容器宽，默认）与固定倍率。
 * 画布缩放是**视图状态**，不是文档状态 —— 放大镜不该进撤销栈。
 *
 * M5 起这里把文档里此前**只读不画**的字段补上了：`adjustments`（调色）、
 * `crop`（裁剪）、`transform.flip_x/flip_y`（翻转）。工具能改但画布不渲染，
 * 等于功能做了一半 —— 用户只会认为那个工具坏了。
 *
 * M6 起增加选区交互：点选（每次点击 = 一个提示点）与笔刷（按住拖动涂抹）。
 * 选区是**视图伴随状态**：遮罩 overlay 与提示点由后端选区服务下发，
 * 不进文档、不产生撤销记录。交互层只在选区模式激活时监听事件，
 * 平时保持 listening=false 不干扰画布渲染。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type Konva from 'konva'
import type { MutableRefObject } from 'react'
import { Circle, Group, Image as KonvaImage, Layer as KonvaLayer, Line, Rect, Stage } from 'react-konva'

import type { LayerCanvas, LayerDocument, Layer as LayerModel } from '@/domain/layerDoc'
import type { SelectionMarker } from '@/api/sessions'
import { layerRect, layerSourceAssetId } from '@/domain/layerDoc'
import { adjustedSource } from './adjustedSource'
import type { ImageMap } from './useLoadedImages'

export type SelectionMode = 'off' | 'point' | 'brush'

interface NormalizedPoint {
  x: number
  y: number
}

/**
 * 单个图层。
 *
 * 抽成组件而不是内联 map 出去：每个图层需要自己的 useMemo（按自己的
 * adjustments 缓存离屏 canvas），Hook 不能写在循环里。
 */
function LayerNode({
  layer,
  canvas,
  image,
}: {
  layer: LayerModel
  canvas: LayerCanvas
  image: HTMLImageElement
}) {
  const rect = layerRect(layer, canvas)

  // 依赖写具体的字段而不是整层的对象引用：文档每次保存都是新对象，
  // 用对象做依赖会让所有图层在任意一次改动后全部重算
  const source = useMemo(
    () => adjustedSource(image, layer.adjustments),
    [image, layer.adjustments],
  )

  const crop = layer.crop
  return (
    <KonvaImage
      image={source as Konva.ImageConfig['image']}
      x={layer.transform.flip_x ? rect.x + rect.width : rect.x}
      y={layer.transform.flip_y ? rect.y + rect.height : rect.y}
      width={rect.width}
      height={rect.height}
      rotation={rect.rotation}
      scaleX={layer.transform.flip_x ? -1 : 1}
      scaleY={layer.transform.flip_y ? -1 : 1}
      opacity={layer.opacity}
      crop={
        crop
          ? { x: crop.x, y: crop.y, width: crop.width, height: crop.height }
          : undefined
      }
    />
  )
}

/** 遮罩 overlay 图：后端下发的半透明 PNG，随选区生成/失效整体出现或消失。 */
function MaskOverlay({ url }: { url: string }) {
  const [image, setImage] = useState<HTMLImageElement | null>(null)

  useEffect(() => {
    if (!url) {
      setImage(null)
      return
    }
    const img = new window.Image()
    img.onload = () => setImage(img)
    img.src = url
    return () => {
      img.onload = null
    }
  }, [url])

  if (!image) return null
  return <KonvaImage image={image} opacity={0.45} listening={false} />
}

export default function CanvasStage({
  doc,
  images,
  loading = false,
  zoom = null,
  stageRef,
  onScaleChange,
  selectionMode = 'off',
  brushRadius = 0.03,
  maskUrl = null,
  markers = [],
  selectionBusy = false,
  onPointClick,
  onStrokeEnd,
}: {
  doc: LayerDocument
  images: ImageMap
  loading?: boolean
  /** null = 贴齐容器宽；数字 = 固定倍率（1 = 100%） */
  zoom?: number | null
  /** 导出要用 Stage 本体；由父级持有（视图状态不进文档） */
  stageRef?: MutableRefObject<Konva.Stage | null>
  /** 实际生效的倍率回传给顶栏显示（fit 时的倍率只有这里算得出来） */
  onScaleChange?: (scale: number) => void
  selectionMode?: SelectionMode
  /** 笔刷半径，相对画布短边的比例 */
  brushRadius?: number
  maskUrl?: string | null
  markers?: SelectionMarker[]
  selectionBusy?: boolean
  /** 点选模式下的单击回调（归一化坐标） */
  onPointClick?: (point: NormalizedPoint) => void
  /** 笔刷模式下一笔结束的回调（归一化坐标序列） */
  onStrokeEnd?: (points: NormalizedPoint[]) => void
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [boxWidth, setBoxWidth] = useState(0)
  // 正在画的笔迹（文档像素坐标），mouseup 时归一化交出去
  const [stroke, setStroke] = useState<NormalizedPoint[] | null>(null)
  const drawingRef = useRef(false)

  // 容器宽度是唯一外部约束：编辑区旁边还有面板，写死宽度必然会溢出
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      setBoxWidth(entries[0]?.contentRect.width ?? 0)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const { width: canvasWidth, height: canvasHeight } = doc.canvas
  const fitScale = useMemo(() => {
    if (!boxWidth || !canvasWidth) return 0
    return Math.min(boxWidth / canvasWidth, 1) // 小图不放大到糊
  }, [boxWidth, canvasWidth])
  const scale = zoom ?? fitScale

  useEffect(() => {
    if (scale > 0) onScaleChange?.(scale)
  }, [scale, onScaleChange])

  // 选区模式切换时丢弃没画完的笔迹，避免上一次模式的残影
  useEffect(() => {
    if (selectionMode !== 'brush') setStroke(null)
  }, [selectionMode])

  // layers 数组从下到上，直接顺序渲染即可（不需要翻转 —— 翻转是为了给面板看）
  const drawable = doc.layers.filter((layer) => layer.visible)

  function pointerNormalized(): NormalizedPoint | null {
    const stage = stageRef?.current
    const pos = stage?.getPointerPosition()
    if (!pos || scale === 0) return null
    return { x: pos.x / scale / canvasWidth, y: pos.y / scale / canvasHeight }
  }

  function handleClick() {
    if (selectionMode !== 'point' || selectionBusy || !onPointClick) return
    const point = pointerNormalized()
    if (point) onPointClick(point)
  }

  function handleMouseDown() {
    if (selectionMode !== 'brush' || selectionBusy || !onStrokeEnd) return
    drawingRef.current = true
    const point = pointerNormalized()
    if (point) setStroke([point])
  }

  function handleMouseMove() {
    if (!drawingRef.current) return
    const point = pointerNormalized()
    if (point) setStroke((prev) => (prev ? [...prev, point] : [point]))
  }

  function handleMouseUp() {
    if (!drawingRef.current) return
    drawingRef.current = false
    if (stroke && stroke.length > 0 && onStrokeEnd) {
      onStrokeEnd(stroke)
    }
    setStroke(null)
  }

  const brushWidthPx = Math.max(2, Math.min(canvasWidth, canvasHeight) * brushRadius)
  const markerRadius = Math.max(4, Math.min(canvasWidth, canvasHeight) * 0.008)

  return (
    // 放大后要能拖动滚动条看细节，容器自身交给外层布局滚
    <div ref={boxRef} className="relative w-full overflow-auto">
      {scale === 0 ? (
        <div className="bg-soft rounded-card h-64 w-full animate-pulse" />
      ) : (
        <Stage
          ref={stageRef}
          width={canvasWidth * scale}
          height={canvasHeight * scale}
          scaleX={scale}
          scaleY={scale}
          onClick={handleClick}
          onTap={handleClick}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onTouchMove={handleMouseMove}
          onTouchEnd={handleMouseUp}
          style={{ cursor: selectionMode === 'off' ? 'default' : 'crosshair' }}
        >
          <KonvaLayer listening={false}>
            {doc.canvas.background && (
              <Rect x={0} y={0} width={canvasWidth} height={canvasHeight} fill={doc.canvas.background} />
            )}

            {drawable.map((layer) => {
              const assetId = layerSourceAssetId(layer)
              const image = assetId ? images[assetId] : undefined
              if (!image) return null
              return (
                <LayerNode
                  key={layer.id}
                  layer={layer}
                  canvas={doc.canvas}
                  image={image}
                />
              )
            })}

            {/* 选区 overlay 与提示点：渲染属于画布，状态不属于文档 */}
            <MaskOverlay url={maskUrl ?? ''} />
            {markers.map((marker) => (
              <Group key={marker.index} listening={false}>
                <Circle
                  x={marker.x * canvasWidth}
                  y={marker.y * canvasHeight}
                  radius={markerRadius}
                  fill="#ffffff"
                  stroke={SELECTION_COLOR}
                  strokeWidth={2}
                />
                <Circle
                  x={marker.x * canvasWidth}
                  y={marker.y * canvasHeight}
                  radius={markerRadius * 0.4}
                  fill={SELECTION_COLOR}
                />
              </Group>
            ))}
          </KonvaLayer>

          {/* 正在画的笔迹预览：纯视觉反馈，松手才交给服务端 */}
          {stroke && stroke.length > 0 && (
            <KonvaLayer listening={false}>
              <Line
                points={stroke.flatMap((p) => [p.x * canvasWidth, p.y * canvasHeight])}
                stroke="rgba(95, 152, 173, 0.55)"
                strokeWidth={brushWidthPx}
                lineCap="round"
                lineJoin="round"
              />
            </KonvaLayer>
          )}
        </Stage>
      )}

      {loading && (
        <span className="text-faint absolute top-3 left-3 text-xs">素材加载中…</span>
      )}
      {selectionBusy && (
        <span className="border-line bg-paper text-muted absolute top-3 right-3 rounded-card border px-2 py-1 text-xs shadow-sm">
          选区计算中…
        </span>
      )}
    </div>
  )
}

const SELECTION_COLOR = '#5f98ad'

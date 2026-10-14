/**
 * Konva 画布。
 *
 * 这个组件做的唯一一件事：**按图层文档渲染**。它不做任何编辑操作，
 * 也不持有文档之外的状态 —— 文档是唯一真相源，画布只是它的一个投影。
 * 好处是「画布上显示的」和「工具实际改的」永远是一份东西。
 *
 * 缩放只用一个 scale：Stage 尺寸 = 画布尺寸 × scale，坐标仍是文档里的画布像素。
 * 这样以后加节点变换/选区时不用做「屏幕坐标 ⇄ 文档坐标」的第二套换算。
 *
 * M5 起这里把文档里此前**只读不画**的字段补上了：`adjustments`（调色）、
 * `crop`（裁剪）、`transform.flip_x/flip_y`（翻转）。工具能改但画布不渲染，
 * 等于功能做了一半 —— 用户只会认为那个工具坏了。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type Konva from 'konva'
import { Image as KonvaImage, Layer as KonvaLayer, Rect, Stage } from 'react-konva'

import type { LayerCanvas, LayerDocument, Layer as LayerModel } from '@/domain/layerDoc'
import { layerRect, layerSourceAssetId } from '@/domain/layerDoc'
import { adjustedSource } from './adjustedSource'
import type { ImageMap } from './useLoadedImages'

/**
 * 单个图层。
 *
 * 抽成组件而不是内联 map 出去：每个图层需要自己的 useMemo（按 own 的
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

export default function CanvasStage({
  doc,
  images,
  loading = false,
}: {
  doc: LayerDocument
  images: ImageMap
  loading?: boolean
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [boxWidth, setBoxWidth] = useState(0)

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
  const scale = useMemo(() => {
    if (!boxWidth || !canvasWidth) return 0
    return Math.min(boxWidth / canvasWidth, 1) // 小图不放大到糊
  }, [boxWidth, canvasWidth])

  // layers 数组从下到上，直接顺序渲染即可（不需要翻转 —— 翻转是为了给面板看）
  const drawable = doc.layers.filter((layer) => layer.visible)

  return (
    <div ref={boxRef} className="relative w-full">
      {scale === 0 ? (
        <div className="bg-soft rounded-card h-64 w-full animate-pulse" />
      ) : (
        <Stage width={canvasWidth * scale} height={canvasHeight * scale} scaleX={scale} scaleY={scale}>
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
          </KonvaLayer>
        </Stage>
      )}

      {loading && (
        <span className="text-faint absolute top-3 left-3 text-xs">素材加载中…</span>
      )}
    </div>
  )
}

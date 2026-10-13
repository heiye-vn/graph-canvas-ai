/**
 * Konva 画布。
 *
 * 这个组件做的唯一一件事：**按图层文档渲染**。它不做任何编辑操作，
 * 也不持有文档之外的状态 —— 文档是唯一真相源，画布只是它的一个投影。
 * 好处是「画布上显示的」和「工具实际改的」永远是一份东西。
 *
 * 缩放只用一个 scale：Stage 尺寸 = 画布尺寸 × scale，坐标仍是文档里的画布像素。
 * 这样以后加节点变换/选区时不用做「屏幕坐标 ⇄ 文档坐标」的第二套换算。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type Konva from 'konva'
import { Image as KonvaImage, Layer as KonvaLayer, Rect, Stage } from 'react-konva'

import type { LayerDocument } from '@/domain/layerDoc'
import { layerRect, layerSourceAssetId } from '@/domain/layerDoc'
import type { ImageMap } from './useLoadedImages'

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
              const rect = layerRect(layer, doc.canvas)
              return (
                <KonvaImage
                  key={layer.id}
                  image={image as Konva.ImageConfig['image']}
                  x={rect.x}
                  y={rect.y}
                  width={rect.width}
                  height={rect.height}
                  rotation={rect.rotation}
                  opacity={layer.opacity}
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

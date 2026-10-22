/**
 * 把调整后的像素变成 Konva 能画的对象。
 *
 * 「为什么不直接用 Konva 的 filters」：见 domain/pixels.ts 的模块注释。
 * 一句话总结 —— Konva 自定义 filter 依赖 `this` 绑定读节点属性，
 * 一旦失效是「调色没反应」这种很难联想到 filter 的表现；而离屏 canvas
 * 的路径在 vitest 里能一行断言钉住。
 */

import type { Adjustments } from '@/domain/layerDoc'
import {
  adjustPixels,
  hasAdjustments,
  sharpenPixels,
  vignettePixels,
} from '@/domain/pixels'

export type DrawableSource = HTMLImageElement | HTMLCanvasElement

/**
 * 按 adjustments 生成显示用图像。
 *
 * 没有调整时**直接返回原图**：每次操作都拷一张 bitmap 的话，
 * 拖一次明度滑块就等于排了一串等值但不同地址的 bitmap，内存悄悄涨上去。
 */
export function adjustedSource(
  source: HTMLImageElement,
  adjustments: Adjustments | undefined,
): DrawableSource {
  if (!hasAdjustments(adjustments)) return source
  if (!adjustments) return source

  const canvas = document.createElement('canvas')
  canvas.width = source.naturalWidth
  canvas.height = source.naturalHeight

  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return source

  try {
    ctx.drawImage(source, 0, 0)
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
    // 与后端 _adjust_numpy 同序：颜色 → 锐化/清晰度 → 晕影
    const colored = adjustPixels(imageData.data, adjustments)
    const sharpened = sharpenPixels(
      colored,
      canvas.width,
      canvas.height,
      adjustments,
    )
    // set() 而非替换引用：ImageData.data 是只读的那块内存
    imageData.data.set(
      vignettePixels(
        sharpened,
        canvas.width,
        canvas.height,
        adjustments.vignette,
      ),
    )
    ctx.putImageData(imageData, 0, 0)
    return canvas
  } catch {
    // 跨域或取不到像素：宁可显示**没调色**的原图，也不要整块画布变空白。
    // 真到了这里多半是对象存储的 CORS 没配对，控制台会有浏览器自己的告警。
    return source
  }
}

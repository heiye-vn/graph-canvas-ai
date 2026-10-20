/**
 * 调色的像素运算 —— DoD ③「带透明通道的图调色不发黑」的落点。
 *
 * 为什么把这段刻意写成**纯函数**（而不是塞进 Konva 的 filters）：
 *
 *   1. 可测。「透明区调色后仍是透明」这件事用不着截图，几行数组断言就能钉死
 *   2. 不依赖 Konva 内部机制。Konva 的自定义 filter 靠 `this` 绑定读节点属性，
 *      版本一换就可能静默失效 —— 而失效的表现是「调色突然没效果了」，很难查
 *
 * ⚠️ 只写 RGB，**永不写第 4 个字节（alpha）**。
 * 服务端 Pillow 那类实现的经典坑是 `convert('RGB')` 把 alpha 丢掉，
 * 透明区域就变成了黑底；这里从数据结构上就没让它发生 —— 循环体里压根
 * 没有 `data[i + 3]` 的左值。
 *
 * ⚠️ **运算顺序必须与 `backend/app/edits/render.py::_adjust_numpy` 一致**：
 * 对比 → 明度 → 高光/阴影 → 色温/色调 → 饱和 → 自然饱和 → 锐化 → 清晰度 → 晕影。
 * 两边顺序一旦不同，「画布上看到的」和「拍平喂给模型的」就不是一张图。
 */

import type { Adjustments } from './layerDoc'

export const NEUTRAL_ADJUSTMENTS: Adjustments = {
  brightness: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  temperature: 0,
  tint: 0,
  saturation: 0,
  vibrance: 0,
  sharpness: 0,
  clarity: 0,
  vignette: 0,
}

/** 全组参数都没动过 —— 这时连画布拷贝都可以省掉。 */
export function hasAdjustments(adjustments: Adjustments | undefined): boolean {
  if (!adjustments) return false
  return (Object.keys(NEUTRAL_ADJUSTMENTS) as (keyof Adjustments)[]).some(
    (key) => adjustments[key] !== NEUTRAL_ADJUSTMENTS[key],
  )
}

function clamp(value: number): number {
  return value < 0 ? 0 : value > 255 ? 255 : value
}

/** 明度/对比度的步长：±100 对应 ±255 色阶，与后端 `step = 2.55` 同款。 */
const STEP = 2.55

/**
 * 按 RGBA 顺序排列的像素序列做非破坏性调色，返回**新的**数组（不改入参）。
 *
 * width/height 只服务晕影（需要知道像素在画面里的位置）。
 * 不传时跳过晕影 —— 单测不需要为了测颜色去构造坐标系。
 */
export function adjustPixels(
  data: Uint8ClampedArray,
  adjustments: Adjustments,
  width = 0,
  height = 0,
): Uint8ClampedArray {
  const out = new Uint8ClampedArray(data.length)

  const contrast = adjustments.contrast * STEP // -255 ~ 255
  // 线性拉伸式对比度系数：0 时恒等于 1，两端分别趋向全灰与硬阈值
  const factor =
    (259 * (contrast + 255)) / Math.max(255 * (259 - contrast), 1)
  const brightness = adjustments.brightness * STEP
  const highlights = adjustments.highlights / 100
  const shadows = adjustments.shadows / 100
  const warm = (adjustments.temperature / 100) * 24
  const tint = adjustments.tint / 100
  const saturation = adjustments.saturation / 100
  const vibrance = adjustments.vibrance / 100
  const vignette = adjustments.vignette / 100

  const hasVignette = vignette > 0 && width > 0 && height > 0
  const centerX = (width - 1) / 2
  const centerY = (height - 1) / 2
  const farthest = Math.hypot(centerX, centerY) || 1

  for (let i = 0, pixel = 0; i < data.length; i += 4, pixel += 1) {
    let r = data[i]
    let g = data[i + 1]
    let b = data[i + 2]

    if (contrast !== 0) {
      r = factor * (r - 128) + 128
      g = factor * (g - 128) + 128
      b = factor * (b - 128) + 128
    }
    if (brightness !== 0) {
      r += brightness
      g += brightness
      b += brightness
    }
    if (highlights !== 0 || shadows !== 0) {
      // 按亮度线性分配：亮部吃高光、暗部吃阴影，中间调基本不动
      const luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
      const lift = shadows * (1 - luma) * 64 + highlights * luma * 64
      r += lift
      g += lift
      b += lift
    }
    if (warm !== 0 || tint !== 0) {
      // 暖 = 红多蓝少；色调正品红、负绿。G 只吃色调，动它会把肤色推向品红
      r += warm + tint * 12
      g -= tint * 20
      b -= warm + tint * 12
    }
    if (saturation !== 0) {
      const gray = 0.2126 * r + 0.7152 * g + 0.0722 * b
      r = gray + (r - gray) * (1 + saturation)
      g = gray + (g - gray) * (1 + saturation)
      b = gray + (b - gray) * (1 + saturation)
    }
    if (vibrance !== 0) {
      // 自然饱和度：本来就鲜艳的像素少改，灰扑扑的多改
      const average = (r + g + b) / 3
      const chroma =
        (Math.abs(r - average) +
          Math.abs(g - average) +
          Math.abs(b - average)) /
        3
      const weight = vibrance * Math.max(0, 1 - chroma / 128)
      r += (r - average) * weight
      g += (g - average) * weight
      b += (b - average) * weight
    }
    if (hasVignette) {
      const x = pixel % width
      const y = (pixel / width) | 0
      const distance = Math.hypot(x - centerX, y - centerY) / farthest
      const shade = 1 - vignette * Math.pow(Math.min(1, distance), 1.6)
      r *= shade
      g *= shade
      b *= shade
    }

    out[i] = clamp(r)
    out[i + 1] = clamp(g)
    out[i + 2] = clamp(b)
    out[i + 3] = data[i + 3] // alpha 原样搬运 —— 透明区永远透明
  }
  return out
}

/**
 * 锐化 / 清晰度：邻域运算，必须在颜色调整之后单独跑一遍。
 *
 * 算法是 unsharp mask（原图 + (原图 - 模糊) × 强度），
 * 与后端 Pillow 的 `ImageFilter.UnsharpMask` 同源；半径取 1（锐化）和 2（清晰度），
 * 负值退化成高斯模糊（和拖到负数的直觉一致）。
 */
export function sharpenPixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  adjustments: Adjustments,
): Uint8ClampedArray {
  const { sharpness, clarity } = adjustments
  if ((!sharpness && !clarity) || width <= 0 || height <= 0) return data

  const out = new Uint8ClampedArray(data)
  const size = width * height
  const plane = new Float32Array(size)

  for (let channel = 0; channel < 3; channel += 1) {
    for (let i = 0; i < size; i += 1) plane[i] = data[i * 4 + channel]
    if (sharpness) applyUnsharp(plane, width, height, 1, sharpness / 100)
    if (clarity) applyUnsharp(plane, width, height, 2, (clarity / 100) * 0.8)
    for (let i = 0; i < size; i += 1) out[i * 4 + channel] = plane[i]
  }
  return out
}

function applyUnsharp(
  plane: Float32Array,
  width: number,
  height: number,
  radius: number,
  amount: number,
): void {
  const blurred = boxBlur(plane, width, height, radius)
  for (let i = 0; i < plane.length; i += 1) {
    plane[i] = plane[i] + (plane[i] - blurred[i]) * amount
  }
}

/** 可分离 box blur：水平一遍、垂直一遍，O(n)，边界按复制处理。 */
function boxBlur(
  source: Float32Array,
  width: number,
  height: number,
  radius: number,
): Float32Array {
  const window = radius * 2 + 1
  const temp = new Float32Array(source.length)
  const out = new Float32Array(source.length)

  for (let y = 0; y < height; y += 1) {
    const row = y * width
    let sum = 0
    for (let x = -radius; x <= radius; x += 1) {
      sum += source[row + Math.min(width - 1, Math.max(0, x))]
    }
    for (let x = 0; x < width; x += 1) {
      temp[row + x] = sum / window
      const next = row + Math.min(width - 1, x + radius + 1)
      const prev = row + Math.max(0, x - radius)
      sum += source[next] - source[prev]
    }
  }

  for (let x = 0; x < width; x += 1) {
    let sum = 0
    for (let y = -radius; y <= radius; y += 1) {
      sum += temp[Math.min(height - 1, Math.max(0, y)) * width + x]
    }
    for (let y = 0; y < height; y += 1) {
      out[y * width + x] = sum / window
      const next = Math.min(height - 1, y + radius + 1) * width + x
      const prev = Math.max(0, y - radius) * width + x
      sum += temp[next] - temp[prev]
    }
  }
  return out
}

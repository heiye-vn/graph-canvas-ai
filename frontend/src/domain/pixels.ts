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
 */

import type { Adjustments } from './layerDoc'

export const NEUTRAL_ADJUSTMENTS: Adjustments = {
  brightness: 0,
  contrast: 0,
  saturation: 0,
  temperature: 0,
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

/** 明度/色温的步长：±100 对应 ±25 个色阶，再大就是纯白/纯黑的浪费区间。 */
const STEP = 2.55

/**
 * 按 RGBA 顺序排列的像素序列做非破坏性调色，返回**新的**数组（不改入参）。
 *
 * 顺序是有讲究的：饱和度在明度之后算，否则先把接近白色的像素提亮会让
 * 「去饱和」看起来像没生效 —— 灰度值是按对比后的结果取的。
 */
export function adjustPixels(
  data: Uint8ClampedArray,
  adjustments: Adjustments,
): Uint8ClampedArray {
  const out = new Uint8ClampedArray(data.length)

  const contrast = adjustments.contrast * STEP // -255 ~ 255
  // 线性拉伸式对比度系数：0 时恒等于 1，两端分别趋向全灰与硬阈值
  const factor =
    (259 * (contrast + 255)) / Math.max(255 * (259 - contrast), 1)
  const brightness = adjustments.brightness * STEP
  const saturation = adjustments.saturation / 100
  const warm = (adjustments.temperature / 100) * 24

  for (let i = 0; i < data.length; i += 4) {
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
    if (saturation !== 0) {
      const gray = 0.2126 * r + 0.7152 * g + 0.0722 * b
      r = gray + (r - gray) * (1 + saturation)
      g = gray + (g - gray) * (1 + saturation)
      b = gray + (b - gray) * (1 + saturation)
    }
    if (warm !== 0) {
      // 暖 = 红多蓝少。刻意只对 R/B 施力：动 G 会把肤色推向品红
      r += warm
      b -= warm
    }

    out[i] = clamp(r)
    out[i + 1] = clamp(g)
    out[i + 2] = clamp(b)
    out[i + 3] = data[i + 3] // alpha 原样搬运 —— 透明区永远透明
  }
  return out
}

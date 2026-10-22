/**
 * 调色像素运算的测试。
 *
 * 重点不是「数值算得对」，而是 **DoD ③：带透明通道的图调色不发黑**。
 * 这条在服务端 Pillow 那类实现里很容易坏（`convert('RGB')` 丢 alpha），
 * 而坏了之后的表现是「透明 PNG 一调色就糊上一层黑」，用户只会觉得产品很糙，
 * 绝不会想到是通道问题 —— 所以必须用测试钉住。
 */

import { describe, expect, it } from 'vitest'

import {
  adjustPixels,
  hasAdjustments,
  NEUTRAL_ADJUSTMENTS,
  sharpenPixels,
  vignettePixels,
} from '@/domain/pixels'
import type { Adjustments } from '@/domain/layerDoc'

const adj = (patch: Partial<Adjustments> = {}): Adjustments => ({
  ...NEUTRAL_ADJUSTMENTS,
  ...patch,
})

/** 三个像素：不透明红 / 全透明黑 / 半透明绿 */
function sample() {
  return new Uint8ClampedArray([
    200, 40, 40, 255,
    10, 20, 30, 0,
    0, 180, 60, 128,
  ])
}

const alphaOf = (data: Uint8ClampedArray) => [data[3], data[7], data[11]]

describe('adjustPixels', () => {
  it('全中性时不改动任何字节（连 alpha 也不）', () => {
    const input = sample()
    expect(Array.from(adjustPixels(input, adj()))).toEqual(Array.from(input))
  })

  it('提亮：提高 RGB，且不碰 alpha', () => {
    const out = adjustPixels(sample(), adj({ brightness: 20 }))
    expect(out[0]).toBeGreaterThan(200)
    expect(out[1]).toBeGreaterThan(40)
    expect(alphaOf(out)).toEqual([255, 0, 128])
  })

  it('压暗：降低 RGB', () => {
    const out = adjustPixels(sample(), adj({ brightness: -20 }))
    expect(out[0]).toBeLessThan(200)
  })

  it('去饱和：RGB 三通道互相靠近', () => {
    const out = adjustPixels(sample(), adj({ saturation: -100 }))
    const [r, g, b] = [out[0], out[1], out[2]]
    expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(2)
  })

  it('加饱和：拉开三通道差距', () => {
    const before = adj({ saturation: 0 })
    const after = adj({ saturation: 60 })
    const spread = (data: Uint8ClampedArray) =>
      Math.max(data[0], data[1], data[2]) - Math.min(data[0], data[1], data[2])
    expect(spread(adjustPixels(sample(), after))).toBeGreaterThan(
      spread(adjustPixels(sample(), before)),
    )
  })

  it('暖色调：红色增加、蓝色减少', () => {
    const out = adjustPixels(sample(), adj({ temperature: 50 }))
    expect(out[0]).toBeGreaterThan(200)
    expect(out[2]).toBeLessThan(40)
  })

  it('对比度：亮的更亮、暗的更暗', () => {
    const out = adjustPixels(sample(), adj({ contrast: 30 }))
    expect(out[0]).toBeGreaterThan(200) // 原本就亮的红
    expect(out[1]).toBeLessThan(40) // 原本就暗的绿
  })

  it('不修改入参', () => {
    const input = sample()
    const before = Array.from(input)
    adjustPixels(input, adj({ brightness: 50 }))
    expect(Array.from(input)).toEqual(before)
  })

  it('结果被夹在 0-255 内，不会溢出回绕', () => {
    const out = adjustPixels(sample(), adj({ brightness: 100, temperature: 100 }))
    for (const value of out) {
      expect(value).toBeGreaterThanOrEqual(0)
      expect(value).toBeLessThanOrEqual(255)
    }
  })

  // ---- DoD ③ ----

  it('★ DoD③ 透明区域调色后仍是透明：全透明像素不会被填成黑', () => {
    const out = adjustPixels(sample(), adj({ brightness: 80, contrast: 40, saturation: -100 }))
    // 第二个像素是 (10,20,30,alpha=0) —— 它的 alpha 必须还是 0
    expect(out[7]).toBe(0)
    expect(alphaOf(out)).toEqual([255, 0, 128])
  })

  it('★ DoD③ 极端组合下 alpha 依然逐字节不变', () => {
    const input = sample()
    const expectedAlpha = alphaOf(input)
    const mixes: Adjustments[] = [
      adj({ brightness: 100 }),
      adj({ brightness: -100 }),
      adj({ contrast: 100 }),
      adj({ contrast: -100 }),
      adj({ saturation: 100 }),
      adj({ temperature: -100 }),
      adj({ brightness: 100, contrast: 100, saturation: 100, temperature: 100 }),
      adj({ brightness: -100, contrast: -100, saturation: -100, temperature: -100 }),
    ]
    for (const mix of mixes) {
      expect(alphaOf(adjustPixels(input, mix))).toEqual(expectedAlpha)
    }
  })

  it('★ DoD③ 半透明像素保持原有权重（alpha 不参与混合计算）', () => {
    const out = adjustPixels(sample(), adj({ brightness: 100 }))
    // 第三个像素 alpha=128，调色不该把它推向 255 或 0
    expect(out[11]).toBe(128)
    // 但它的 RGB 确实变了 —— 否则就变成「半透明的图调不动」
    expect(out[8]).toBeGreaterThan(0)
  })
})

describe('hasAdjustments', () => {
  it('中性参数视为没有调整', () => {
    expect(hasAdjustments(adj())).toBe(false)
  })

  it('任意一项偏离中性即为有调整', () => {
    expect(hasAdjustments(adj({ brightness: 1 }))).toBe(true)
    expect(hasAdjustments(adj({ temperature: -1 }))).toBe(true)
  })

  it('缺省时按「没调整」处理（老文档里没有这个字段）', () => {
    expect(hasAdjustments(undefined)).toBe(false)
  })
})

describe('新增调色参数', () => {
  /** 两个像素：亮部 / 暗部 */
  function tones() {
    return new Uint8ClampedArray([
      220, 220, 220, 255,
      30, 30, 30, 255,
    ])
  }

  it('高光只抬亮部，暗部基本不动', () => {
    const out = adjustPixels(tones(), adj({ highlights: 60 }))
    expect(out[0]).toBeGreaterThan(220)
    // 暗部 luma 低，分到的高光量很小（< 8 而不是完全为 0）
    expect(Math.abs(out[4] - 30)).toBeLessThan(8)
    expect(out[0] - 220).toBeGreaterThan(out[4] - 30)
  })

  it('阴影只抬暗部，亮部基本不动', () => {
    const out = adjustPixels(tones(), adj({ shadows: 60 }))
    expect(out[4]).toBeGreaterThan(30)
    expect(Math.abs(out[0] - 220)).toBeLessThan(8)
    expect(out[4] - 30).toBeGreaterThan(out[0] - 220)
  })

  it('色调：正值为品红（绿降、红蓝升），负值为绿', () => {
    const pink = adjustPixels(tones(), adj({ tint: 60 }))
    expect(pink[1]).toBeLessThan(220) // 绿降
    expect(pink[0]).toBeGreaterThan(220) // 红升

    const green = adjustPixels(tones(), adj({ tint: -60 }))
    expect(green[0]).toBeLessThan(220) // 红降
    expect(green[1]).toBeGreaterThan(30) // 绿升
  })

  it('自然饱和度：低饱和像素的**相对**增益大于高饱和像素', () => {
    // 左：低饱和 (150,130,120)；右：高饱和 (220,40,40)
    const input = new Uint8ClampedArray([
      150, 130, 120, 255,
      220, 40, 40, 255,
    ])
    const before = adjustPixels(input, adj())
    const after = adjustPixels(input, adj({ vibrance: 80 }))
    const delta = (out: Uint8ClampedArray, offset: number) =>
      Math.abs(out[offset] - before[offset]) +
      Math.abs(out[offset + 1] - before[offset + 1]) +
      Math.abs(out[offset + 2] - before[offset + 2])
    const chroma = (offset: number) => {
      const average =
        (before[offset] + before[offset + 1] + before[offset + 2]) / 3
      return (
        (Math.abs(before[offset] - average) +
          Math.abs(before[offset + 1] - average) +
          Math.abs(before[offset + 2] - average)) /
        3
      )
    }
    // 绝对变化量反而可能是高饱和像素更大（差值大），
    // 「少改」说的是相对自身色度的比例
    expect(delta(after, 0) / chroma(0)).toBeGreaterThan(
      delta(after, 4) / chroma(4),
    )
  })

  it('颜色链路不再处理晕影（交给最后一步）', () => {
    const data = new Uint8ClampedArray([200, 200, 200, 255])
    expect(Array.from(adjustPixels(data, adj({ vignette: 100 })))).toEqual([
      200, 200, 200, 255,
    ])
  })
})

describe('vignettePixels', () => {
  it('四角变暗、中心不变', () => {
    const size = 8
    const data = new Uint8ClampedArray(size * size * 4)
    for (let i = 0; i < data.length; i += 4) {
      data[i] = 200
      data[i + 1] = 200
      data[i + 2] = 200
      data[i + 3] = 255
    }
    const out = vignettePixels(data, size, size, 80)
    const at = (x: number, y: number) => out[(y * size + x) * 4]
    // 8px 图没有「正中心」像素，最近的四格仍有极轻微压暗
    expect(at(4, 4)).toBeGreaterThan(190)
    expect(at(0, 0)).toBeLessThan(at(4, 4)) // 左上角明显变暗
    expect(at(7, 7)).toBeLessThan(at(4, 4))
  })

  it('零强度或没有尺寸时原样返回（不拷贝）', () => {
    const data = new Uint8ClampedArray([200, 200, 200, 255])
    expect(vignettePixels(data, 1, 1, 0)).toBe(data)
    expect(vignettePixels(data, 0, 0, 100)).toBe(data)
  })

  it('不动 alpha', () => {
    const size = 4
    const data = new Uint8ClampedArray(size * size * 4)
    for (let i = 0; i < data.length; i += 4) {
      data[i] = 180
      data[i + 1] = 180
      data[i + 2] = 180
      data[i + 3] = i % 8 === 0 ? 0 : 255
    }
    const out = vignettePixels(data, size, size, 100)
    for (let i = 3; i < data.length; i += 4) expect(out[i]).toBe(data[i])
  })
})

describe('sharpenPixels', () => {
  /** 3x3：中心亮、周围暗，锐化应把中心推得更亮 */
  function edge() {
    const size = 3
    const data = new Uint8ClampedArray(size * size * 4)
    for (let i = 0; i < data.length; i += 4) {
      const pixel = i / 4
      const center = pixel === 4
      const value = center ? 200 : 100
      data[i] = value
      data[i + 1] = value
      data[i + 2] = value
      data[i + 3] = 255
    }
    return data
  }

  it('中性参数原样返回', () => {
    const input = edge()
    expect(sharpenPixels(input, 3, 3, adj())).toBe(input)
  })

  it('锐化增强边缘对比，且不动 alpha', () => {
    const out = sharpenPixels(edge(), 3, 3, adj({ sharpness: 100 }))
    expect(out[4 * 4]).toBeGreaterThan(200) // 中心更亮
    expect(out[0]).toBeLessThan(100) // 角落更暗
    expect([out[3], out[7], out[11], out[15], out[19], out[23], out[27], out[31], out[35]])
      .toEqual([255, 255, 255, 255, 255, 255, 255, 255, 255])
  })

  it('清晰度同样生效（更大半径）', () => {
    const out = sharpenPixels(edge(), 3, 3, adj({ clarity: 100 }))
    expect(out[4 * 4]).toBeGreaterThan(200)
  })
})

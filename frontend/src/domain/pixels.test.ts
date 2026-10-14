/**
 * 调色像素运算的测试。
 *
 * 重点不是「数值算得对」，而是 **DoD ③：带透明通道的图调色不发黑**。
 * 这条在服务端 Pillow 那类实现里很容易坏（`convert('RGB')` 丢 alpha），
 * 而坏了之后的表现是「透明 PNG 一调色就糊上一层黑」，用户只会觉得产品很糙，
 * 绝不会想到是通道问题 —— 所以必须用测试钉住。
 */

import { describe, expect, it } from 'vitest'

import { adjustPixels, hasAdjustments, NEUTRAL_ADJUSTMENTS } from '@/domain/pixels'
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

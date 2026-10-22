/**
 * 图层文档领域层测试。
 *
 * 这份用例的价值不在覆盖率，而在**钉住三条约定的语义**：
 * 数组顺序、默认图层、切换当前图。这三条一旦漂了，
 * 表现是「画布显示的不是被改的那个图层」，而且要很久才能定位到这里。
 */

import { describe, expect, it } from 'vitest'

import {
  layerRect,
  layerSourceAssetId,
  referencedAssetIds,
  topDown,
  topmostVisibleImageLayer,
} from '@/domain/layerDoc'
import type { Layer, LayerDocument } from '@/domain/layerDoc'

let seq = 0

function imageLayer(name: string, visible = true, assetId = `asset-${(seq += 1)}`): Layer {
  return {
    id: `layer-${seq}`,
    name,
    type: 'image',
    visible,
    locked: false,
    opacity: 1,
    transform: { x: 0, y: 0, width: null, height: null, rotation: 0, flip_x: false, flip_y: false },
    source: { asset_id: assetId },
    adjustments: {
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
    },
    crop: null,
  }
}

function textLayer(name: string): Layer {
  return {
    ...imageLayer(name),
    type: 'text',
    source: undefined,
    text: { text: '促销价', font_size: 48, fill: '#171917' },
  }
}

function docOf(...layers: Layer[]): LayerDocument {
  return {
    version: 1,
    canvas: { width: 512, height: 512, background: '#ffffff' },
    layers,
    active_layer_id: null,
  }
}

describe('顺序语义', () => {
  it('数组从下到上，topDown 反转给面板用', () => {
    const doc = docOf(imageLayer('底'), imageLayer('顶'))

    expect(doc.layers[0].name).toBe('底')
    expect(topDown(doc).map((l) => l.name)).toEqual(['顶', '底'])
  })
})

describe('默认图层', () => {
  it('取最上层可见的 image 层', () => {
    const doc = docOf(imageLayer('隐藏', false), imageLayer('底下'), textLayer('文案'))
    expect(topmostVisibleImageLayer(doc)?.name).toBe('底下')
  })

  it('没有可见 image 层时为 undefined', () => {
    expect(topmostVisibleImageLayer(docOf(imageLayer('唯一', false)))).toBeUndefined()
    expect(topmostVisibleImageLayer(docOf(textLayer('只有文字')))).toBeUndefined()
  })
})

describe('渲染辅助', () => {
  it('缺宽高时回退到画布尺寸，而不是画成 0', () => {
    const doc = docOf(imageLayer('A'))
    const rect = layerRect(doc.layers[0], doc.canvas)

    expect(rect).toEqual({ x: 0, y: 0, width: 512, height: 512, rotation: 0 })
  })

  it('referencedAssetIds 去重并保持从底到顶的顺序', () => {
    const shared = imageLayer('重复引用', true, 'same-asset')
    const doc = docOf(shared, imageLayer('另一张', true, 'other'), { ...shared, id: 'layer-x' })

    expect(referencedAssetIds(doc)).toEqual(['same-asset', 'other'])
  })

  it('layerSourceAssetId 取得到引用', () => {
    expect(layerSourceAssetId(imageLayer('A', true, 'asset-1'))).toBe('asset-1')
    expect(layerSourceAssetId(textLayer('文案'))).toBeNull()
  })
})

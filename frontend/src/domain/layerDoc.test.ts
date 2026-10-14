/**
 * 图层文档领域层测试。
 *
 * 这份用例的价值不在覆盖率，而在**钉住三条约定的语义**：
 * 数组顺序、默认图层、切换当前图。这三条一旦漂了，
 * 表现是「画布显示的不是被改的那个图层」，而且要很久才能定位到这里。
 */

import { describe, expect, it } from 'vitest'

import {
  LayerNotFoundError,
  addLayer,
  layerRect,
  layerSourceAssetId,
  referencedAssetIds,
  removeLayer,
  resolveLayer,
  setActiveLayer,
  setLayerVisible,
  switchCurrentImage,
  topDown,
  topmostVisibleImageLayer,
  updateLayer,
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
    adjustments: { brightness: 0, contrast: 0, saturation: 0, temperature: 0 },
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

  it('addLayer 追加到最上层且不修改入参', () => {
    const doc = docOf(imageLayer('底'))
    const updated = addLayer(doc, imageLayer('新'))

    expect(updated.layers).toHaveLength(2)
    expect(updated.layers.at(-1)?.name).toBe('新')
    expect(doc.layers).toHaveLength(1)
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

describe('resolveLayer', () => {
  it('按 id 精确匹配', () => {
    const doc = docOf(imageLayer('A'), imageLayer('B'))
    const target = doc.layers[1]

    expect(resolveLayer(doc, target.id)).toBe(target)
    expect(resolveLayer(doc, { id: target.id })).toBe(target)
  })

  it('按名称匹配取最上层', () => {
    const doc = docOf(imageLayer('同名'), imageLayer('同名'))
    expect(resolveLayer(doc, '同名')).toBe(doc.layers[1])
  })

  it('不传 ref 时走默认图层', () => {
    const doc = docOf(imageLayer('隐藏', false), imageLayer('目标'))
    expect(resolveLayer(doc).name).toBe('目标')
  })

  it('找不到就抛错，不悄悄回退到第一个图层', () => {
    const doc = docOf(imageLayer('A'))
    expect(() => resolveLayer(doc, '不存在')).toThrow(LayerNotFoundError)
    expect(() => resolveLayer(docOf())).toThrow(LayerNotFoundError)
  })
})

describe('增删改', () => {
  it('removeLayer 顺带清空指向它的选中态', () => {
    const target = imageLayer('待删')
    const doc = setActiveLayer(docOf(target), target.id)

    const updated = removeLayer(doc, target.id)
    expect(updated.layers).toHaveLength(0)
    expect(updated.active_layer_id).toBeNull()
  })

  it('操作不存在的图层会抛错', () => {
    const doc = docOf(imageLayer('A'))
    expect(() => removeLayer(doc, 'nope')).toThrow(LayerNotFoundError)
    expect(() => updateLayer(doc, 'nope', { name: 'x' })).toThrow(LayerNotFoundError)
    expect(() => setActiveLayer(doc, 'nope')).toThrow(LayerNotFoundError)
  })

  it('setLayerVisible 只动目标图层', () => {
    const doc = docOf(imageLayer('A'), imageLayer('B'))
    const updated = setLayerVisible(doc, doc.layers[0].id, false)

    expect(updated.layers.map((l) => l.visible)).toEqual([false, true])
  })
})

describe('切换当前图', () => {
  it('目标可见、其余图像层隐藏，并把 active 指过去', () => {
    const doc = docOf(imageLayer('第一张'), imageLayer('第二张'))
    const updated = switchCurrentImage(doc, doc.layers[1].id)

    expect(updated.layers.map((l) => l.visible)).toEqual([false, true])
    expect(updated.active_layer_id).toBe(doc.layers[1].id)
  })

  it('不动文字层：切候选图不该顺手藏掉用户自己加的东西', () => {
    const target = imageLayer('第二张')
    const text = textLayer('文案')
    const doc = docOf(imageLayer('第一张'), target, text)

    const updated = switchCurrentImage(doc, target.id)

    expect(byName(updated, '文案').visible).toBe(true)
    expect(byName(updated, '第一张').visible).toBe(false)
  })

  it('目标不是图像层时报错', () => {
    const doc = docOf(textLayer('文案'))
    expect(() => switchCurrentImage(doc, doc.layers[0].id)).toThrow(/图像层/)
  })
})

function byName(doc: LayerDocument, name: string): Layer {
  const found = doc.layers.find((layer) => layer.name === name)
  if (!found) throw new Error(`测试夹具里没有 ${name}`)
  return found
}

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

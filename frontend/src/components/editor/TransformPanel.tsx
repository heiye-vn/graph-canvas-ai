/**
 * 变换面板 —— 图层的整体调整（对齐参考项目的图层检查器）。
 *
 * 透明度 / 图层缩放 / 旋转 / 层级四组。位置与尺寸也能在画布上直接拖，
 * 滑杆负责「想要一个准确值」的场景，两者写的是同一份文档字段。
 *
 * 缩放基准是**画布宽度**：100% = 图层铺满画布宽。用图层自身宽度做基准的话，
 * 每次改完基准就跟着变，滑杆会自己漂走。
 *
 * ⚠️ 滑杆必须用**本地 state**，不能直接 value={文档值}：
 * 拖动过程中文档不会变，受控值把 thumb 按回原位，松手后弹回去 → 用户看到的就是
 * 「这个滑杆拖不动」。松手提交，服务端回写后再同步本地值。
 */

import { useEffect, useState } from 'react'
import { Slider, Tooltip } from 'antd'

import type { Layer, LayerDocument } from '@/domain/layerDoc'
import { layerRect } from '@/domain/layerDoc'

export default function TransformPanel({
  doc,
  layer,
  onInvoke,
}: {
  doc: LayerDocument
  layer: Layer | null
  onInvoke: (name: string, params: Record<string, unknown>) => void
}) {
  if (!layer) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 bg-slate-50/50 p-3 text-center text-xs text-slate-400">
        点击画布上的图片或下方图层选中后可调整
      </div>
    )
  }

  // 拆成带 hooks 的子组件：上面的早退在 hooks 之前，不能直接在本体里挂 useState
  return <TransformControls doc={doc} layer={layer} onInvoke={onInvoke} />
}

function TransformControls({
  doc,
  layer,
  onInvoke,
}: {
  doc: LayerDocument
  layer: Layer
  onInvoke: (name: string, params: Record<string, unknown>) => void
}) {
  const depth = doc.layers.findIndex((item) => item.id === layer.id)
  const topmost = depth === doc.layers.length - 1
  const bottommost = depth === 0
  const rect = layerRect(layer, doc.canvas)
  const documentScale = Math.max(
    1,
    Math.round((rect.width / doc.canvas.width) * 100),
  )
  const documentOpacity = Math.round(layer.opacity * 100)
  const documentRotation = Math.round(layer.transform.rotation)
  const aspect = rect.height / Math.max(1, rect.width)

  const [opacity, setOpacity] = useState(documentOpacity)
  const [scale, setScale] = useState(documentScale)
  const [rotation, setRotation] = useState(documentRotation)

  // 文档变化（撤销 / 切换图层 / 服务端回写）时把滑杆拉回真实值
  useEffect(() => setOpacity(documentOpacity), [documentOpacity, layer.id])
  useEffect(() => setScale(documentScale), [documentScale, layer.id])
  useEffect(() => setRotation(documentRotation), [documentRotation, layer.id])

  /**
   * 按比例缩放图层，**以中心为原点**。
   *
   * 只改 width/height 的话左上角是固定点，缩到 50% 图会朝左上角缩（用户看到的就是
   * 「以左上角为中心缩放」）。这里把位置按新旧尺寸差的一半平移，中心才不动。
   * 一次提交 x/y/width/height，撤销栈里仍然只有一条。
   */
  function commitScale(value: number) {
    const width = Math.max(1, Math.round((doc.canvas.width * value) / 100))
    const height = Math.max(1, Math.round(width * aspect))
    onInvoke('transform_layer', {
      layer: layer.id,
      x: Math.round(rect.x + (rect.width - width) / 2),
      y: Math.round(rect.y + (rect.height - height) / 2),
      width,
      height,
    })
  }

  return (
    <div className="space-y-3.5 select-none text-xs">
      <p className="m-0 text-[11px] leading-snug text-slate-400">
        画布上可直接拖动移动、拖角缩放、拖顶部手柄旋转；滑杆用于精确调整，松手写入。
        右侧数值可直接点开输入。
      </p>

      <div>
        <div className="mb-1 flex items-center justify-between text-slate-600">
          <span className="text-xs font-medium">透明度</span>
          <NumberField
            value={opacity}
            min={0}
            max={100}
            onCommit={(value) => {
              setOpacity(value)
              onInvoke('set_opacity', {
                layer: layer.id,
                opacity: value / 100,
              })
            }}
          />
        </div>
        <Slider
          min={0}
          max={100}
          value={opacity}
          className="m-0! py-1!"
          tooltip={{ open: false }}
          onChange={(value) => setOpacity(value as number)}
          onChangeComplete={(value) =>
            onInvoke('set_opacity', {
              layer: layer.id,
              opacity: (value as number) / 100,
            })
          }
        />
      </div>

      {layer.type === 'image' && (
        <div>
          <div className="mb-1 flex items-center justify-between text-slate-600">
            <span className="text-xs font-medium">图层缩放</span>
            <NumberField
              value={scale}
              min={10}
              max={200}
              onCommit={(value) => {
                setScale(value)
                commitScale(value)
              }}
            />
          </div>
          <Slider
            min={10}
            max={200}
            value={Math.min(200, scale)}
            className="m-0! py-1!"
            tooltip={{ open: false }}
            onChange={(value) => setScale(value as number)}
            onChangeComplete={(value) => commitScale(value as number)}
          />
        </div>
      )}

      {layer.type === 'image' && (
        <div>
          <div className="mb-1 flex items-center justify-between text-slate-600">
            <span className="flex items-center gap-1.5 text-xs font-medium">
              旋转
              <NumberField
                value={rotation}
                min={-180}
                max={180}
                unit="°"
                onCommit={(value) => {
                  setRotation(value)
                  onInvoke('transform_layer', {
                    layer: layer.id,
                    rotation: value,
                  })
                }}
              />
            </span>
            <button
              type="button"
              disabled={rotation === 0}
              onClick={() => {
                setRotation(0)
                onInvoke('transform_layer', { layer: layer.id, rotation: 0 })
              }}
              className="cursor-pointer rounded px-1.5 py-0.5 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              归零
            </button>
          </div>
          <Slider
            min={-180}
            max={180}
            value={rotation}
            className="m-0! py-1!"
            tooltip={{ open: false }}
            onChange={(value) => setRotation(value as number)}
            onChangeComplete={(value) =>
              onInvoke('transform_layer', {
                layer: layer.id,
                rotation: value as number,
              })
            }
          />
        </div>
      )}

      {/* 位置重置：拖歪了不用靠撤销，两个语义分开给 */}
      <div className="grid grid-cols-2 gap-1">
        <Tooltip title="回到画布左上角（未拖动时的位置）">
          <button
            type="button"
            onClick={() =>
              onInvoke('transform_layer', { layer: layer.id, x: 0, y: 0 })
            }
            className="cursor-pointer rounded border border-slate-200 py-1 text-xs font-medium text-slate-600 transition-all hover:bg-slate-50 hover:text-slate-900"
          >
            位置归零
          </button>
        </Tooltip>
        <Tooltip title="保持当前尺寸与角度，摆回画布中心">
          <button
            type="button"
            onClick={() =>
              onInvoke('transform_layer', {
                layer: layer.id,
                x: Math.round((doc.canvas.width - rect.width) / 2),
                y: Math.round((doc.canvas.height - rect.height) / 2),
              })
            }
            className="cursor-pointer rounded border border-slate-200 py-1 text-xs font-medium text-slate-600 transition-all hover:bg-slate-50 hover:text-slate-900"
          >
            居中
          </button>
        </Tooltip>
      </div>

      <div className="grid grid-cols-4 gap-1 rounded-md bg-slate-100 p-0.5">
        <Tooltip title="移到最顶层">
          <button
            type="button"
            disabled={topmost}
            onClick={() =>
              onInvoke('reorder_layer', {
                layer: layer.id,
                index: doc.layers.length - 1,
              })
            }
            className="cursor-pointer rounded bg-white py-1 text-xs font-medium text-slate-600 shadow-2xs transition-all hover:bg-slate-50 hover:text-slate-900 disabled:opacity-40 disabled:hover:bg-white"
          >
            置顶
          </button>
        </Tooltip>
        <Tooltip title="上移一层">
          <button
            type="button"
            disabled={topmost}
            onClick={() =>
              onInvoke('reorder_layer', { layer: layer.id, index: depth + 1 })
            }
            className="cursor-pointer rounded bg-white py-1 text-xs font-medium text-slate-600 shadow-2xs transition-all hover:bg-slate-50 hover:text-slate-900 disabled:opacity-40 disabled:hover:bg-white"
          >
            上移
          </button>
        </Tooltip>
        <Tooltip title="下移一层">
          <button
            type="button"
            disabled={bottommost}
            onClick={() =>
              onInvoke('reorder_layer', { layer: layer.id, index: depth - 1 })
            }
            className="cursor-pointer rounded bg-white py-1 text-xs font-medium text-slate-600 shadow-2xs transition-all hover:bg-slate-50 hover:text-slate-900 disabled:opacity-40 disabled:hover:bg-white"
          >
            下移
          </button>
        </Tooltip>
        <Tooltip title="移到最底层">
          <button
            type="button"
            disabled={bottommost}
            onClick={() =>
              onInvoke('reorder_layer', { layer: layer.id, index: 0 })
            }
            className="cursor-pointer rounded bg-white py-1 text-xs font-medium text-slate-600 shadow-2xs transition-all hover:bg-slate-50 hover:text-slate-900 disabled:opacity-40 disabled:hover:bg-white"
          >
            置底
          </button>
        </Tooltip>
      </div>

      {layer.crop && (
        <button
          type="button"
          onClick={() => onInvoke('reset_crop', { layer: layer.id })}
          className="w-full cursor-pointer rounded border border-slate-200 py-1 text-xs text-slate-600 transition-all hover:bg-slate-50"
        >
          还原裁剪
        </button>
      )}
    </div>
  )
}

/**
 * 可手输的数值框。
 *
 * 滑杆拖不准（100% 想改成 95% 时尤其明显），所以数值本身必须能点开输入：
 * 回车 / 失焦提交，Esc 放弃，值按 min/max 夹取并取整。
 */
function NumberField({
  value,
  min,
  max,
  unit = '%',
  onCommit,
}: {
  value: number
  min: number
  max: number
  unit?: string
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))

  useEffect(() => setDraft(String(value)), [value])

  function commit() {
    const parsed = Number.parseFloat(draft)
    if (!Number.isFinite(parsed)) {
      setDraft(String(value))
      return
    }
    const next = Math.min(max, Math.max(min, Math.round(parsed)))
    setDraft(String(next))
    if (next !== value) onCommit(next)
  }

  return (
    <span className="flex items-center">
      <input
        value={draft}
        inputMode="numeric"
        aria-label="数值"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
          if (event.key === 'Escape') {
            setDraft(String(value))
            event.currentTarget.blur()
          }
        }}
        className="w-11 rounded border border-transparent bg-transparent px-0.5 text-right font-mono text-[11px] tabular-nums text-slate-500 transition-colors hover:border-slate-200 focus:border-blue-400 focus:bg-white focus:text-slate-800 focus:outline-none"
      />
      <span className="w-3 font-mono text-[11px] font-normal text-slate-400">
        {unit}
      </span>
    </span>
  )
}

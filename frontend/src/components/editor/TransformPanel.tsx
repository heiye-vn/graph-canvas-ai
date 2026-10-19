/**
 * 变换面板 —— 选中图层的不透明度 / 旋转 / 层级控制（对齐参考图1标准）。
 *
 * 紧凑微调滑杆 + 置顶/上移/下移/置底四合一操作胶囊。
 */

import { Slider, Tooltip } from 'antd'

import type { Layer, LayerDocument } from '@/domain/layerDoc'


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
        点击选中一个图层后可调整变换
      </div>
    )
  }

  const depth = doc.layers.findIndex((item) => item.id === layer.id)
  const topmost = depth === doc.layers.length - 1
  const bottommost = depth === 0

  return (
    <div className="space-y-3.5 select-none text-xs">
      {/* 提示文案（对齐参考图1） */}
      <p className="text-[11px] text-slate-400 leading-snug m-0">
        选中图层后拖角缩放、拖动画布移动。滑杆改动松手写入，支持撤销。
      </p>

      {/* 不透明度滑杆 */}
      <div>
        <div className="mb-1 flex items-center justify-between text-slate-600">
          <span className="font-medium text-xs">透明度</span>
          <span className="font-mono text-slate-400 text-[11px] tabular-nums">
            {Math.round(layer.opacity * 100)}%
          </span>
        </div>
        <Slider
          min={0}
          max={100}
          value={Math.round(layer.opacity * 100)}
          className="m-0! py-1!"
          onChangeComplete={(value) =>
            onInvoke('set_opacity', { layer: layer.id, opacity: (value as number) / 100 })
          }
        />
      </div>

      {/* 旋转滑杆 */}
      <div>
        <div className="mb-1 flex items-center justify-between text-slate-600">
          <span className="font-medium text-xs">旋转</span>
          <span className="font-mono text-slate-400 text-[11px] tabular-nums">
            {Math.round(layer.transform.rotation)}°
          </span>
        </div>
        <Slider
          min={-180}
          max={180}
          value={Math.round(layer.transform.rotation)}
          className="m-0! py-1!"
          onChangeComplete={(value) =>
            onInvoke('rotate_layer', { layer: layer.id, degrees: value as number })
          }
        />
      </div>

      {/* 四合一层级按钮组（置顶 / 上移 / 下移 / 置底） */}
      <div className="pt-1">
        <div className="grid grid-cols-4 gap-1 bg-slate-100 p-0.5 rounded-md">
          <Tooltip title="移到最顶层">
            <button
              type="button"
              disabled={topmost}
              onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: doc.layers.length - 1 })}
              className="py-1 text-xs text-slate-600 hover:text-slate-900 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-white rounded shadow-2xs font-medium cursor-pointer transition-all"
            >
              置顶
            </button>
          </Tooltip>
          <Tooltip title="上移一层">
            <button
              type="button"
              disabled={topmost}
              onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: depth + 1 })}
              className="py-1 text-xs text-slate-600 hover:text-slate-900 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-white rounded shadow-2xs font-medium cursor-pointer transition-all"
            >
              上移
            </button>
          </Tooltip>
          <Tooltip title="下移一层">
            <button
              type="button"
              disabled={bottommost}
              onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: depth - 1 })}
              className="py-1 text-xs text-slate-600 hover:text-slate-900 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-white rounded shadow-2xs font-medium cursor-pointer transition-all"
            >
              下移
            </button>
          </Tooltip>
          <Tooltip title="移到最底层">
            <button
              type="button"
              disabled={bottommost}
              onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: 0 })}
              className="py-1 text-xs text-slate-600 hover:text-slate-900 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-white rounded shadow-2xs font-medium cursor-pointer transition-all"
            >
              置底
            </button>
          </Tooltip>
        </div>

        {layer.crop && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => onInvoke('reset_crop', { layer: layer.id })}
              className="w-full py-1 text-xs text-slate-600 border border-slate-200 rounded hover:bg-slate-50 cursor-pointer transition-all"
            >
              还原裁剪
            </button>
          </div>
        )}
      </div>
    </div>
  )
}


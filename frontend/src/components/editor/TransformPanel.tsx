/**
 * 变换面板 —— 选中图层的透明度 / 旋转 / 层级，滑杆与按钮直达。
 *
 * 这里出现**具体的工具名**（set_opacity / rotate_layer / reorder_layer / reset_crop）
 * 是刻意的例外：「工具表单不硬编码」那条规矩管的是通用表单（ToolPanel），
 * 而滑杆是**面板级操作** —— 用户拖的是「透明度」这个概念，
 * 不是「调用某个名字的工具」。概念到工具的映射集中在这一处，不散落。
 *
 * 滑杆拖动过程**不发请求**，松手（onChangeComplete）才提交：
 * 拖一次滑杆从 0 到 100 会触发几十次中间值，每次都落一条历史等于把撤销栈灌满废水。
 */

import { Button, Slider, Tooltip } from 'antd'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  VerticalAlignTopOutlined,
} from '@ant-design/icons'

import type { Layer, LayerDocument } from '@/domain/layerDoc'

export default function TransformPanel({
  doc,
  layer,
  onInvoke,
}: {
  doc: LayerDocument
  layer: Layer | null
  /** (工具名, 参数) —— 落到 EditorPage 统一的工具调用上 */
  onInvoke: (name: string, params: Record<string, unknown>) => void
}) {
  if (!layer) {
    return <p className="text-faint m-0 text-xs">选中一个图层后可调整变换</p>
  }

  const depth = doc.layers.findIndex((item) => item.id === layer.id)
  const topmost = depth === doc.layers.length - 1

  return (
    <div className="space-y-4">
      <div>
        <div className="text-muted mb-1 flex items-center justify-between text-xs">
          <span>不透明度</span>
          <span className="text-faint">{Math.round(layer.opacity * 100)}%</span>
        </div>
        <Slider
          min={0}
          max={100}
          value={Math.round(layer.opacity * 100)}
          onChangeComplete={(value) =>
            onInvoke('set_opacity', { layer: layer.id, opacity: (value as number) / 100 })
          }
        />
      </div>

      <div>
        <div className="text-muted mb-1 flex items-center justify-between text-xs">
          <span>旋转</span>
          <span className="text-faint">{Math.round(layer.transform.rotation)}°</span>
        </div>
        <Slider
          min={-180}
          max={180}
          value={Math.round(layer.transform.rotation)}
          onChangeComplete={(value) =>
            onInvoke('rotate_layer', { layer: layer.id, degrees: value as number })
          }
        />
      </div>

      <div className="flex items-center gap-1.5">
        <Tooltip title="移到最上层">
          <Button
            size="small"
            icon={<VerticalAlignTopOutlined />}
            disabled={topmost}
            onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: doc.layers.length - 1 })}
          >
            置顶
          </Button>
        </Tooltip>
        <Tooltip title="上移一层">
          <Button
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={topmost}
            onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: depth + 1 })}
          />
        </Tooltip>
        <Tooltip title="下移一层">
          <Button
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={depth === 0}
            onClick={() => onInvoke('reorder_layer', { layer: layer.id, index: depth - 1 })}
          />
        </Tooltip>
        {layer.crop && (
          <Tooltip title="取消裁剪，露出完整画面">
            <Button size="small" onClick={() => onInvoke('reset_crop', { layer: layer.id })}>
              还原裁剪
            </Button>
          </Tooltip>
        )}
      </div>
    </div>
  )
}

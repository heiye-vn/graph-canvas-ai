/**
 * 图层面板 —— 紧凑单行行（M5.6 重写）。
 *
 * 顺序注意：`topDown()` —— 面板从上到下是「视觉上的从上到下」，
 * 文档数组是反的（从下到上）。这条转换只允许在这一处发生。
 *
 * 为什么不用 antd 的 List：List.Item 的 actions 布局为「内容 + 右侧操作区」设计，
 * 在 288px 的侧栏里 actions 会把内容挤到逐字换行，行高塌陷 ——
 * 那正是上一版截图里最刺眼的问题。密集面板要**自己控制行盒模型**：
 * 一行 = 图标 + 弹性名字 + 辅助信息 + 固定图标按钮，任何一段都不换行。
 */

import { Button, Tooltip } from 'antd'
import {
  BorderOutlined,
  EditOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  FileImageOutlined,
  FontSizeOutlined,
  StarOutlined,
} from '@ant-design/icons'

import type { Layer, LayerDocument } from '@/domain/layerDoc'
import { topDown } from '@/domain/layerDoc'

const TYPE_ICON: Record<Layer['type'], React.ReactNode> = {
  image: <FileImageOutlined />,
  text: <FontSizeOutlined />,
  shape: <BorderOutlined />,
}

export default function LayerPanel({
  doc,
  selectedId,
  onSelect,
  onToggleVisible,
  onSwitchCurrent,
  onEditText,
  busy = false,
}: {
  doc: LayerDocument
  /** 变换面板作用对象的 id；null 表示跟随「当前图」 */
  selectedId?: string | null
  onSelect?: (layerId: string) => void
  onToggleVisible: (layerId: string, visible: boolean) => void
  onSwitchCurrent: (layerId: string) => void
  /** 文字层的「改文案」入口：切到 set_layer_text 工具（M7） */
  onEditText?: (layerId: string) => void
  /** 有请求在飞：禁用按钮，避免同一步连点两次而多出一条历史 */
  busy?: boolean
}) {
  const layers = topDown(doc)

  if (layers.length === 0) {
    return <p className="text-faint m-0 text-xs">这个会话还没有图层</p>
  }

  return (
    <div className="space-y-0.5">
      {layers.map((layer) => {
        const active = layer.id === doc.active_layer_id
        const selected = layer.id === selectedId
        return (
          <div
            key={layer.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelect?.(layer.id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelect?.(layer.id)
              }
            }}
            aria-pressed={selected}
            className={`flex h-9 cursor-pointer items-center gap-2 rounded-control border px-2 transition-colors duration-150 ${
              selected
                ? 'border-brand bg-brand-soft'
                : active
                  ? 'border-transparent bg-brand-soft/70'
                  : 'border-transparent hover:bg-soft'
            }`}
          >
            <span className="text-brand w-4 shrink-0 text-center text-sm">{TYPE_ICON[layer.type]}</span>
            <span
              className={`flex-1 truncate text-xs ${layer.visible ? '' : 'text-faint'}`}
              title={layer.name}
            >
              {layer.name}
            </span>
            {layer.crop && (
              <span className="text-faint shrink-0 text-[10px]" title="该图层已裁剪">
                已裁剪
              </span>
            )}
            <span className="text-faint w-8 shrink-0 text-right text-[10px] tabular-nums">
              {Math.round(layer.opacity * 100)}%
            </span>

            {layer.type === 'text' && onEditText && (
              <Tooltip title="改文案">
                <Button
                  size="small"
                  type="text"
                  icon={<EditOutlined />}
                  disabled={busy}
                  aria-label={`改文案：${layer.name}`}
                  className="h-6! w-6! shrink-0"
                  onClick={(event) => {
                    event.stopPropagation()
                    onEditText(layer.id)
                  }}
                />
              </Tooltip>
            )}

            {layer.type === 'image' && !layer.visible && (
              <Tooltip title="设为当前图（其余候选图隐藏）">
                <Button
                  size="small"
                  type="text"
                  icon={<StarOutlined />}
                  disabled={busy}
                  aria-label={`设为当前图：${layer.name}`}
                  className="h-6! w-6! shrink-0"
                  onClick={(event) => {
                    event.stopPropagation()
                    onSwitchCurrent(layer.id)
                  }}
                />
              </Tooltip>
            )}

            <Tooltip title={layer.visible ? '隐藏' : '显示'}>
              <Button
                size="small"
                type="text"
                icon={layer.visible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                disabled={busy}
                aria-label={layer.visible ? `隐藏图层：${layer.name}` : `显示图层：${layer.name}`}
                className="h-6! w-6! shrink-0"
                onClick={(event) => {
                  event.stopPropagation()
                  onToggleVisible(layer.id, !layer.visible)
                }}
              />
            </Tooltip>
          </div>
        )
      })}
    </div>
  )
}

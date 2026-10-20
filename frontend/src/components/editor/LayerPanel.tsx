/**
 * 图层面板 —— 图层堆栈 + 拆层选项。
 *
 * 这里只保留**真的会生效**的选项：拆层在顶栏，勾上「同时拆出文字」后
 * 顶栏那一下就会带上 include_text。成层（合并图层）后端还没有对应工具，
 * 所以不摆那个按钮 —— 点了没反应的开关比没有更糟。
 */

import { Button, Checkbox, Tooltip } from 'antd'
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
  splitIncludeText = false,
  onSplitIncludeTextChange,
}: {
  doc: LayerDocument
  selectedId?: string | null
  onSelect?: (layerId: string) => void
  onToggleVisible: (layerId: string, visible: boolean) => void
  onSwitchCurrent: (layerId: string) => void
  onEditText?: (layerId: string) => void
  busy?: boolean
  /** 顶栏「拆层」是否同时拆出文字层 */
  splitIncludeText?: boolean
  onSplitIncludeTextChange?: (next: boolean) => void
}) {
  const layers = topDown(doc)

  return (
    <div className="space-y-2.5 select-none">
      {/* 拆层选项：勾选后顶栏那一下会带上 include_text */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-1.5">
        <span className="text-[11px] text-slate-400">拆层选项</span>
        <Checkbox
          checked={splitIncludeText}
          onChange={(event) => onSplitIncludeTextChange?.(event.target.checked)}
          className="text-[11px] text-slate-600"
        >
          同时拆出文字
        </Checkbox>
      </div>

      {/* 图层列表卡片 */}
      {layers.length === 0 ? (
        <p className="text-slate-400 m-0 text-xs py-2 text-center">暂无图层</p>
      ) : (
        <div className="space-y-1">
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
                className={`flex h-11 cursor-pointer items-center gap-2 rounded-lg border px-2.5 transition-all duration-150 ${
                  selected
                    ? 'border-blue-400 bg-blue-50/70 shadow-2xs'
                    : active
                      ? 'border-blue-200 bg-blue-50/30'
                      : 'border-slate-200/80 bg-white hover:border-slate-300 hover:bg-slate-50/80'
                }`}
              >
                {/* 图层微缩图/图标占位 */}
                <div className="h-7 w-7 rounded bg-slate-900 border border-slate-800 flex items-center justify-center shrink-0 text-slate-300 text-xs">
                  {TYPE_ICON[layer.type]}
                </div>

                <div className="flex min-w-0 flex-1 flex-col justify-center">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`truncate text-xs font-medium ${layer.visible ? 'text-slate-800' : 'text-slate-400 line-through'}`}
                      title={layer.name}
                    >
                      {layer.name}
                    </span>
                    {layer.locked && (
                      <span className="font-mono text-[9px] text-slate-400">已锁定</span>
                    )}
                  </div>
                  {layer.crop && (
                    <span className="text-slate-400 text-[10px] leading-tight">已裁剪</span>
                  )}
                </div>

                <span className="text-slate-400 w-8 shrink-0 text-right text-[10px] tabular-nums font-mono">
                  {Math.round(layer.opacity * 100)}%
                </span>

                {layer.type === 'text' && onEditText && (
                  <Tooltip title="改文案">
                    <Button
                      size="small"
                      type="text"
                      icon={<EditOutlined />}
                      disabled={busy}
                      className="h-6! w-6! shrink-0 text-slate-500 hover:text-slate-800"
                      onClick={(event) => {
                        event.stopPropagation()
                        onEditText(layer.id)
                      }}
                    />
                  </Tooltip>
                )}

                {layer.type === 'image' && !layer.visible && (
                  <Tooltip title="设为当前图">
                    <Button
                      size="small"
                      type="text"
                      icon={<StarOutlined />}
                      disabled={busy}
                      className="h-6! w-6! shrink-0 text-amber-500"
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
                    icon={layer.visible ? <EyeOutlined className="text-slate-500" /> : <EyeInvisibleOutlined className="text-slate-300" />}
                    disabled={busy}
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
      )}
    </div>
  )
}


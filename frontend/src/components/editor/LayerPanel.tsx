/**
 * 图层面板 —— 专业级卡片式图层堆栈（对齐参考图1标准）。
 *
 * 1. 顶部提供拆层/成层与文字关联快捷开关
 * 2. 图层卡片化：包含类型预览、名称、锁定/激活徽章、不透明度、眼睛开关
 */

import { useState } from 'react'
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
}: {
  doc: LayerDocument
  selectedId?: string | null
  onSelect?: (layerId: string) => void
  onToggleVisible: (layerId: string, visible: boolean) => void
  onSwitchCurrent: (layerId: string) => void
  onEditText?: (layerId: string) => void
  busy?: boolean
}) {
  const [splitMode, setSplitMode] = useState<string>('split')
  const [extractText, setExtractText] = useState(false)
  const layers = topDown(doc)

  return (
    <div className="space-y-2.5 select-none">
      {/* 顶部操作区（对齐参考图1） */}
      <div className="space-y-1.5 pb-1 border-b border-slate-100">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <Checkbox
            checked={extractText}
            onChange={(e) => setExtractText(e.target.checked)}
            className="text-[11px] text-slate-600"
          >
            同时拆出文字
          </Checkbox>
        </div>

        <div className="grid grid-cols-2 gap-1 bg-slate-100 p-0.5 rounded-md">
          <button
            type="button"
            onClick={() => setSplitMode('split')}
            className={`py-1 text-xs font-medium rounded transition-all cursor-pointer ${
              splitMode === 'split' ? 'bg-white text-slate-800 shadow-2xs' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            拆层
          </button>
          <button
            type="button"
            onClick={() => setSplitMode('merge')}
            className={`py-1 text-xs font-medium rounded transition-all cursor-pointer ${
              splitMode === 'merge' ? 'bg-white text-slate-800 shadow-2xs' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            成层
          </button>
        </div>
      </div>

      {/* 图层列表卡片 */}
      {layers.length === 0 ? (
        <p className="text-slate-400 m-0 text-xs py-2 text-center">暂无图层</p>
      ) : (
        <div className="space-y-1">
          {layers.map((layer, index) => {
            const active = layer.id === doc.active_layer_id
            const selected = layer.id === selectedId
            const isBase = index === layers.length - 1

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
                    {isBase && (
                      <span className="text-[9px] text-slate-400 font-mono">已锁定</span>
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


/**
 * 编辑器顶栏 —— 对齐参考项目的工具集与秩序（图1）。
 *
 * 这里刻意**不做「工具注册表倒进顶栏」**：
 * 后端有 20 个工具，其中一多半是 move/resize/rename/reorder 这种底层原子操作，
 * 它们是 Agent 和画布手势的落点，不是用户要点的按钮。顶栏只保留**编辑一张图
 * 真正会用到的那一排**，其余藏进右栏与对话。
 *
 * 另一个秩序：按钮**只在能力真实存在时渲染**（available 来自 /api/tools）。
 * 摆一个点下去只会弹「工具不存在」的假按钮，比少一个按钮恶劣得多。
 */

import { Dropdown, Tooltip } from 'antd'
import {
  AppstoreOutlined,
  ColumnWidthOutlined,
  DownOutlined,
  ExportOutlined,
  MinusOutlined,
  PlusOutlined,
  RedoOutlined,
  UndoOutlined,
} from '@ant-design/icons'

import type { SelectionMode } from './CanvasStage'

export type ToolbarAction =
  | 'crop'
  | 'flip_h'
  | 'flip_v'
  | 'remove_background'
  | 'replace_background'
  | 'expand_canvas'
  | 'upscale_image'
  | 'adjust_color'
  | 'split_layers'

export type CropRatio = 'free' | '1:1' | '4:5' | '9:16' | '16:9'

const CROP_RATIOS: { value: CropRatio; label: string }[] = [
  { value: 'free', label: '自由' },
  { value: '1:1', label: '1:1' },
  { value: '4:5', label: '4:5' },
  { value: '9:16', label: '9:16' },
  { value: '16:9', label: '16:9' },
]

/** 主工具条：顺序与参考项目一致，工具名用于查 /api/tools 判断是否真的可用。 */
const PRIMARY_ACTIONS: {
  action: ToolbarAction
  label: string
  tool: string
  title: string
  needsLayer?: boolean
}[] = [
  { action: 'crop', label: '裁剪', tool: 'crop_canvas', title: '在画布上拉框裁剪画布' },
  { action: 'flip_h', label: '水平翻转', tool: 'flip_layer', title: '左右翻转当前图层', needsLayer: true },
  { action: 'flip_v', label: '垂直翻转', tool: 'flip_layer', title: '上下翻转当前图层', needsLayer: true },
  { action: 'remove_background', label: '去背景', tool: 'remove_background', title: '抠出主体，背景变透明', needsLayer: true },
  { action: 'replace_background', label: '换背景', tool: 'replace_background', title: '按描述替换背景' },
  { action: 'expand_canvas', label: '扩图', tool: 'expand_canvas', title: '按比例扩展画面' },
  { action: 'upscale_image', label: '超分', tool: 'upscale_image', title: '把画面放大到两倍' },
  { action: 'adjust_color', label: '调色', tool: 'adjust_color', title: '调整亮度、对比度、饱和度、色温', needsLayer: true },
  { action: 'split_layers', label: '拆层', tool: 'split_layers', title: '拆成背景与主体，可单独编辑' },
]

function TB({
  children,
  active = false,
  disabled = false,
  title,
  onClick,
}: {
  children: React.ReactNode
  active?: boolean
  disabled?: boolean
  title?: string
  onClick?: () => void
}) {
  return (
    <Tooltip title={title} mouseEnterDelay={0.5}>
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={`h-7 shrink-0 cursor-pointer rounded px-2 text-xs font-normal transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-40 ${
          active
            ? 'bg-blue-50 text-blue-700'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
        }`}
      >
        {children}
      </button>
    </Tooltip>
  )
}

export default function EditorToolbar({
  title,
  width,
  height,
  available,
  busy = false,
  hasLayer = false,
  selectionMode,
  onSelectionMode,
  compare,
  canCompare,
  onToggleCompare,
  zoom,
  currentScale,
  onZoomStep,
  onFit,
  onExport,
  onExportMaterials,
  onAction,
  canUndo,
  canRedo,
  undoBusy,
  redoBusy,
  onUndo,
  onRedo,
  layersOpen,
  onToggleLayers,
  cropping,
  cropRatio,
  onCropRatio,
  onConfirmCrop,
  onCancelCrop,
}: {
  title: string
  width: number
  height: number
  available: Set<string>
  busy?: boolean
  hasLayer?: boolean
  selectionMode: SelectionMode
  onSelectionMode: (mode: SelectionMode) => void
  compare: boolean
  canCompare: boolean
  onToggleCompare: () => void
  zoom: number | null
  currentScale: number
  onZoomStep: (direction: 1 | -1) => void
  onFit: () => void
  onExport: () => void
  /** 打开导出物料页（投放尺寸 / 打包 ZIP） */
  onExportMaterials: () => void
  onAction: (action: ToolbarAction) => void
  canUndo: boolean
  canRedo: boolean
  undoBusy?: boolean
  redoBusy?: boolean
  onUndo: () => void
  onRedo: () => void
  layersOpen: boolean
  onToggleLayers: () => void
  cropping: boolean
  cropRatio: CropRatio
  onCropRatio: (ratio: CropRatio) => void
  onConfirmCrop: () => void
  onCancelCrop: () => void
}) {
  const visible = PRIMARY_ACTIONS.filter((item) => available.has(item.tool))

  return (
    <header className="z-20 flex h-11 shrink-0 items-center gap-1.5 border-b border-slate-200 bg-white px-3">
      {/* 左：标题 + 分辨率。刻意不做分隔线：参考项目里这一串是连贯的一条信息 */}
      <div className="flex max-w-52 shrink-0 items-center gap-2">
        <span className="truncate text-xs font-semibold text-slate-800" title={title}>
          {title}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-slate-400 tabular-nums">
          {width} × {height}
        </span>
      </div>

      {/* 中：主工具条 / 裁剪比例。只按内容取宽（不 flex-1），紧跟标题 */}
      <div className="flex min-w-0 items-center gap-0.5 overflow-x-auto scrollbar-none">
        {cropping ? (
          <>
            {/* 比例组按参考项目的胶囊样式：选中的那个才是白底 */}
            <div className="flex h-7 shrink-0 items-center gap-0.5 rounded-md border border-slate-200 bg-slate-50 p-0.5">
              {CROP_RATIOS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => onCropRatio(item.value)}
                  title={item.value === 'free' ? '自由裁剪' : `按 ${item.label} 比例裁剪`}
                  className={`h-6 cursor-pointer rounded px-2 text-[11px] transition-colors ${
                    cropRatio === item.value
                      ? 'bg-white font-medium text-slate-900 shadow-2xs'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="mx-1 h-4 w-px bg-slate-200" />
            <TB title="按当前框裁剪画布（Enter，可撤销）" onClick={onConfirmCrop}>
              确定
            </TB>
            <TB title="退出裁剪（Esc）" onClick={onCancelCrop}>
              取消
            </TB>
          </>
        ) : (
          <>
            {visible.map((item) => (
              <TB
                key={item.action}
                disabled={busy || (item.needsLayer && !hasLayer)}
                title={item.title}
                onClick={() => onAction(item.action)}
              >
                {item.label}
              </TB>
            ))}
            {visible.length > 0 && <div className="mx-1 h-4 w-px bg-slate-200" />}
            <TB
              active={selectionMode === 'point'}
              title="在画面上点击物体建立选区"
              onClick={() => onSelectionMode(selectionMode === 'point' ? 'off' : 'point')}
            >
              点选
            </TB>
            <TB
              active={selectionMode === 'brush'}
              title="在画面上涂抹建立选区"
              onClick={() => onSelectionMode(selectionMode === 'brush' ? 'off' : 'brush')}
            >
              笔刷
            </TB>
          </>
        )}
      </div>

      {/* 弹簧：把剩余宽度全部吃掉，右区因此永远贴在右边、且不被压缩 */}
      <div className="min-w-0 flex-1" />

      {/* 右：历史 / 对比 / 缩放 / 导出 / 图层 */}
      <div className="flex shrink-0 items-center gap-0.5">
        <Tooltip title={canUndo ? '撤销 (Ctrl+Z)' : '没有可撤销的操作'}>
          <button
            type="button"
            disabled={!canUndo || undoBusy}
            onClick={onUndo}
            className="flex h-7 cursor-pointer items-center gap-1 rounded px-2 text-xs font-normal text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-35"
          >
            <UndoOutlined className="text-[11px]" />
            撤销
          </button>
        </Tooltip>
        <Tooltip title={canRedo ? '重做 (Ctrl+Y)' : '没有可重做的操作'}>
          <button
            type="button"
            disabled={!canRedo || redoBusy}
            onClick={onRedo}
            className="flex h-7 cursor-pointer items-center gap-1 rounded px-2 text-xs font-normal text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-35"
          >
            <RedoOutlined className="text-[11px]" />
            重做
          </button>
        </Tooltip>

        <Tooltip
          title={
            canCompare
              ? '对比编辑前后的效果'
              : '需要两层以上可见图像才能对比'
          }
        >
          <button
            type="button"
            disabled={!canCompare}
            onClick={onToggleCompare}
            className={`flex h-7 cursor-pointer items-center rounded px-2 text-xs font-normal transition-colors disabled:cursor-not-allowed disabled:opacity-35 ${
              compare ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`}
          >
            对比
          </button>
        </Tooltip>

        {/* 缩放控制器 */}
        <div className="mx-1 flex h-7 items-center rounded-md border border-slate-200 bg-slate-50/80 px-1">
          <button
            type="button"
            onClick={() => onZoomStep(-1)}
            className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-slate-500 transition-colors hover:bg-white hover:text-slate-800"
            aria-label="缩小"
          >
            <MinusOutlined className="text-[10px]" />
          </button>
          <span className="w-11 select-none text-center font-mono text-[11px] font-medium tabular-nums text-slate-600">
            {zoom === null ? `${Math.round(currentScale * 100)}%` : `${Math.round(zoom * 100)}%`}
          </span>
          <button
            type="button"
            onClick={() => onZoomStep(1)}
            className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-slate-500 transition-colors hover:bg-white hover:text-slate-800"
            aria-label="放大"
          >
            <PlusOutlined className="text-[10px]" />
          </button>
          <div className="mx-0.5 h-3 w-px bg-slate-200" />
          <button
            type="button"
            disabled={zoom === null}
            onClick={onFit}
            className="flex h-5 w-5 cursor-pointer items-center justify-center rounded text-slate-500 transition-colors hover:bg-white hover:text-slate-800 disabled:opacity-30"
            aria-label="适应窗口"
            title="适应窗口"
          >
            <ColumnWidthOutlined className="text-[11px]" />
          </button>
        </div>

        <Dropdown
          trigger={['click']}
          placement="bottomRight"
          menu={{
            items: [
              { key: 'png', label: '下载当前画布 PNG', icon: <ExportOutlined /> },
              {
                key: 'materials',
                label: '导出物料（投放尺寸 / 打包）',
                icon: <AppstoreOutlined />,
              },
            ],
            onClick: ({ key }) => {
              if (key === 'png') onExport()
              else onExportMaterials()
            },
          }}
        >
          <button
            type="button"
            className="flex h-7 cursor-pointer items-center gap-1 rounded-md bg-blue-600 px-3 text-xs font-medium text-white transition-colors hover:bg-blue-700"
          >
            <ExportOutlined className="text-[11px]" />
            导出
            <DownOutlined className="text-[9px] opacity-80" />
          </button>
        </Dropdown>

        <TB active={layersOpen} title="显示/隐藏图层与属性面板" onClick={onToggleLayers}>
          图层
        </TB>
      </div>
    </header>
  )
}

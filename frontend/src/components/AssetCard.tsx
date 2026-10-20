/**
 * 素材卡 —— 创作页历史素材 / 素材库 / 候选页共用一份。
 *
 * 现代化视觉重构：悬停浮层操作、深邃装裱边框、精致尺寸标签。
 */

import { Popconfirm, Tag, Tooltip } from 'antd'
import { DeleteOutlined, EditOutlined, ExportOutlined } from '@ant-design/icons'

export interface AssetCardAsset {
  id: string
  url: string
  /** 缩略图（可选）：有就用它，避免卡片直接拉原图 */
  thumb_url?: string | null
  width: number | null
  height: number | null
  /** image / export / mask —— 决定右上角的来源徽标 */
  kind?: string
}

export default function AssetCard({
  asset,
  onDelete,
  onEdit,
  pending = false,
}: {
  asset: AssetCardAsset
  onDelete?: () => void
  onEdit?: () => void
  pending?: boolean
}) {
  const dimension =
    asset.width && asset.height ? `${asset.width} × ${asset.height}` : '未知尺寸'

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md hover:border-slate-300">
      {/* 图像展示区 */}
      <div className="relative h-40 w-full overflow-hidden bg-slate-900/90">
        <img
          src={asset.thumb_url ?? asset.url}
          alt=""
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
          decoding="async"
        />

        {/* 来源徽标：投放尺寸与遮罩是中间产物，不该和作品长得一模一样 */}
        {asset.kind === 'export' && (
          <span className="absolute right-2 top-2 rounded-full bg-white/90 px-2 py-0.5 text-[10px] font-medium text-slate-700 shadow-sm">
            投放尺寸
          </span>
        )}
        {asset.kind === 'mask' && (
          <span className="absolute right-2 top-2 rounded-full bg-amber-100/95 px-2 py-0.5 text-[10px] font-medium text-amber-800 shadow-sm">
            选区遮罩
          </span>
        )}

        {/* 悬停浮层快捷操作 */}
        <div className="absolute inset-0 bg-black/40 opacity-0 backdrop-blur-[2px] transition-opacity duration-200 group-hover:opacity-100 flex items-center justify-center gap-2">
          {onEdit && (
            <Tooltip title="进入工作台精修">
              <button
                type="button"
                onClick={onEdit}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white text-xs font-medium shadow-md hover:bg-blue-700 cursor-pointer transition-all"
              >
                <EditOutlined />
                <span>编辑</span>
              </button>
            </Tooltip>
          )}
          <Tooltip title="在新标签页看大图">
            <a
              href={asset.url}
              target="_blank"
              rel="noreferrer"
              className="p-1.5 rounded-md bg-white/90 text-slate-700 hover:text-black hover:bg-white text-xs shadow-md transition-all"
            >
              <ExportOutlined />
            </a>
          </Tooltip>
        </div>

        {pending && (
          <div className="absolute top-2 left-2">
            <Tag bordered={false} color="processing" className="m-0 text-[10px]">
              刚刚生成
            </Tag>
          </div>
        )}
      </div>

      {/* 底部信息栏 */}
      <div className="flex items-center justify-between px-3 py-2 bg-white">
        <span className="font-mono text-[11px] text-slate-500 tabular-nums">{dimension}</span>

        <div className="flex items-center gap-1">
          {onDelete && (
            <Popconfirm
              title="删除这张素材？"
              description="删除后将无法恢复。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={onDelete}
            >
              <button
                type="button"
                className="p-1 text-slate-400 hover:text-red-500 rounded hover:bg-red-50 transition-colors cursor-pointer"
                aria-label="删除素材"
              >
                <DeleteOutlined className="text-xs" />
              </button>
            </Popconfirm>
          )}
        </div>
      </div>
    </div>
  )
}


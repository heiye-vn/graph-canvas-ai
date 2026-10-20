/**
 * 底部版本/候选图胶卷条 —— 贯穿会话的全量版本与图像图层缩略图。
 *
 * 废除单图隐藏限制：即便是初始底图也常驻底栏，确立生产力工具的核心视觉锚点。
 * 胶卷抽屉采用专业级沉浸暗色，每个卡片附带操作标签与高亮激活态。
 */

import { Tooltip } from 'antd'
import { EyeInvisibleOutlined, PictureOutlined } from '@ant-design/icons'

import type { LayerDocument } from '@/domain/layerDoc'
import { layerSourceAssetId } from '@/domain/layerDoc'

export default function CandidateStrip({
  doc,
  urls,
  busy = false,
  onSwitch,
}: {
  doc: LayerDocument
  /** asset_id -> 预签名 URL */
  urls: Record<string, string>
  busy?: boolean
  onSwitch: (layerId: string) => void
}) {
  const candidates = doc.layers.filter((layer) => layer.type === 'image' && layer.source)

  return (
    <div className="bg-stage border-t border-stage-border px-4 py-2.5 flex items-center gap-3 shrink-0 select-none">
      <div className="flex items-center gap-1.5 text-zinc-400 shrink-0 text-xs font-medium">
        <PictureOutlined className="text-blue-400" />
        <span className="tracking-wide">版本流水</span>
        <span className="text-[10px] bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded-full font-mono">
          {candidates.length || 1}
        </span>
      </div>

      <div className="h-4 w-px bg-zinc-800 shrink-0" />

      <div className="flex items-center gap-2.5 overflow-x-auto py-0.5 min-w-0 scrollbar-none">
        {candidates.length === 0 ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-zinc-500 text-xs">
            <span>当前画布暂无图像层</span>
          </div>
        ) : (
          candidates.map((layer, index) => {
            const assetId = layerSourceAssetId(layer)
            const url = assetId ? urls[assetId] : undefined
            const isBase = index === 0
            const active = layer.visible

            return (
              <Tooltip
                key={layer.id}
                title={
                  <div className="text-xs">
                    <p className="font-medium text-white">{layer.name}</p>
                    <p className="text-zinc-400">{isBase ? '初始底图' : '编辑版本'} · 点击切换</p>
                  </div>
                }
              >
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onSwitch(layer.id)}
                  className={`group relative flex flex-col items-center justify-between rounded-md overflow-hidden transition-all duration-150 cursor-pointer ${
                    active
                      ? 'ring-2 ring-blue-500 shadow-md shadow-blue-500/20 bg-zinc-800'
                      : 'border border-zinc-800 hover:border-zinc-600 bg-zinc-900 opacity-70 hover:opacity-100'
                  }`}
                  aria-label={active ? `当前图：${layer.name}` : `切换到 ${layer.name}`}
                  style={{ width: '64px', height: '64px' }}
                >
                  <div className="relative w-full h-full flex items-center justify-center bg-black/40 overflow-hidden">
                    {url ? (
                      <img
                        src={url}
                        alt={layer.name}
                        className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
                      />
                    ) : (
                      <span className="block h-full w-full bg-zinc-800" />
                    )}

                    {!layer.visible && (
                      <div className="absolute inset-0 bg-black/50 backdrop-blur-[1px] flex items-center justify-center">
                        <EyeInvisibleOutlined className="text-zinc-400 text-xs" />
                      </div>
                    )}

                    {/* 底部小标签药丸 */}
                    <div className="absolute bottom-0 inset-x-0 bg-black/75 backdrop-blur-sm px-1 py-0.5 text-center">
                      <p className="text-[10px] text-zinc-300 font-mono truncate leading-none">
                        {isBase ? '底图' : layer.name.slice(0, 4)}
                      </p>
                    </div>
                  </div>
                </button>
              </Tooltip>
            )
          })
        )}
      </div>
    </div>
  )
}


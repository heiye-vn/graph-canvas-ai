/**
 * 底部候选图条 —— 会话里所有图像层的缩略图。
 *
 * 点击 = `switch_current_image`（目标可见、其余候选隐藏）。只列 image 层：
 * 文字层 / 形状层不是「候选图」，混进来只会让人误以为点它能切主图。
 *
 * 当前图的判定用 `visible` 而不是 active_layer_id：前者是 switch_current_image
 * 真正改的东西，后者在用户手动点了别的图层时会跟着变，两者会分叉。
 */

import { Tooltip } from 'antd'
import { EyeInvisibleOutlined } from '@ant-design/icons'

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
  if (candidates.length <= 1) return null // 单张候选没有「切换」可言

  return (
    <div className="border-line flex items-center gap-2 overflow-x-auto border-t px-3 py-2">
      <span className="text-faint shrink-0 text-[11px]">候选图</span>
      {candidates.map((layer) => {
        const assetId = layerSourceAssetId(layer)
        const url = assetId ? urls[assetId] : undefined
        return (
          <Tooltip key={layer.id} title={layer.name}>
            <button
              type="button"
              disabled={busy}
              onClick={() => onSwitch(layer.id)}
              className={`rounded-control relative h-12 w-12 shrink-0 overflow-hidden border transition-all ${
                layer.visible
                  ? 'border-brand ring-brand ring-1'
                  : 'border-line hover:border-muted opacity-70 hover:opacity-100'
              }`}
              aria-label={layer.visible ? `当前图：${layer.name}` : `切换到 ${layer.name}`}
            >
              {url ? (
                <img src={url} alt={layer.name} className="h-full w-full object-cover" />
              ) : (
                <span className="bg-soft block h-full w-full" />
              )}
              {!layer.visible && (
                <EyeInvisibleOutlined className="absolute right-0.5 bottom-0.5 text-[10px] text-white drop-shadow" />
              )}
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}

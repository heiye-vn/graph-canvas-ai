/**
 * 调色面板 —— 右侧实时预览的滑杆组。
 *
 * 交互契约：
 *   1. 拖动只改**本地预览**（CanvasStage 的 previewAdjustments），不写文档
 *   2. 「应用」才走 adjust_color 工具落文档 + 落撤销栈
 *   3. 「重置」把滑杆归零（仍是预览态，想撤销这次调色按顶栏撤销）
 *
 * 锐化 / 清晰度是邻域运算（unsharp），大图上每帧重算会拖慢滑杆，
 * 所以这两项**松手才预览**；其余参数拖动即见。
 */

import { useEffect, useState } from 'react'
import { Button, Slider } from 'antd'

import type { Adjustments, Layer } from '@/domain/layerDoc'

const ZERO: Adjustments = {
  brightness: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  temperature: 0,
  tint: 0,
  saturation: 0,
  vibrance: 0,
  sharpness: 0,
  clarity: 0,
  vignette: 0,
}

interface Control {
  key: keyof Adjustments
  label: string
  hint?: string
  min?: number
  max?: number
  /** false = 松手才预览（邻域运算） */
  live?: boolean
}

const BASIC: Control[] = [
  { key: 'brightness', label: '明度', hint: '整体提亮或压暗' },
  { key: 'contrast', label: '对比度', hint: '黑白反差' },
  { key: 'highlights', label: '高光', hint: '只影响亮部' },
  { key: 'shadows', label: '阴影', hint: '只影响暗部' },
  { key: 'temperature', label: '色温', hint: '冷调 / 暖调' },
  { key: 'tint', label: '色调', hint: '品红 / 绿' },
  { key: 'saturation', label: '饱和度', hint: '色彩浓度' },
  { key: 'vibrance', label: '自然饱和度', hint: '灰的像素多改一点' },
]

const DETAIL: Control[] = [
  { key: 'sharpness', label: '锐化', hint: '边缘清晰度，松手预览', live: false },
  { key: 'clarity', label: '清晰度', hint: '局部对比，松手预览', live: false },
  { key: 'vignette', label: '晕影', hint: '四角压暗', min: 0 },
]

export default function AdjustPanel({
  layer,
  onPreview,
  onApply,
  applying = false,
}: {
  layer: Layer
  /** 预览随滑杆实时回调（null = 结束预览，回到文档值） */
  onPreview: (adjustments: Adjustments | null) => void
  onApply: (adjustments: Adjustments) => void
  applying?: boolean
}) {
  const [values, setValues] = useState<Adjustments>(layer.adjustments ?? ZERO)

  // 切换图层时跟随该图层的文档值（否则会把上一层的调色带过来）
  useEffect(() => {
    setValues(layer.adjustments ?? ZERO)
    onPreview(null)
  }, [layer.id]) // eslint-disable-line react-hooks/exhaustive-deps

  function update(key: keyof Adjustments, value: number) {
    const next = { ...values, [key]: Math.round(value) }
    setValues(next)
    return next
  }

  function commit(key: keyof Adjustments, value: number) {
    const next = update(key, value)
    onPreview(next)
  }

  const dirty = (Object.keys(ZERO) as (keyof Adjustments)[]).some(
    (key) => values[key] !== 0,
  )

  function renderControl(control: Control) {
    return (
      <div key={control.key}>
        <div className="mb-0.5 flex items-center justify-between">
          <span
            className="text-xs font-medium text-slate-600"
            title={control.hint}
          >
            {control.label}
          </span>
          <span className="font-mono text-[11px] tabular-nums text-slate-400">
            {values[control.key] > 0 ? '+' : ''}
            {values[control.key]}
          </span>
        </div>
        <Slider
          min={control.min ?? -100}
          max={control.max ?? 100}
          step={1}
          value={values[control.key]}
          className="m-0! py-1!"
          tooltip={{ open: false }}
          onChange={(value) => {
            const next = update(control.key, value as number)
            // 实时项：拖动即预览；邻域项：等松手
            if (control.live !== false) onPreview(next)
          }}
          onChangeComplete={(value) => {
            if (control.live === false) commit(control.key, value as number)
          }}
        />
      </div>
    )
  }

  return (
    <div className="select-none space-y-3 text-xs">
      <p className="m-0 text-[11px] leading-snug text-slate-400">
        拖动即可在画布上实时预览，点「应用」写入文档（可撤销）。锐化与清晰度松手后可见。
      </p>

      <div className="space-y-2.5">{BASIC.map(renderControl)}</div>

      <div className="pt-1">
        <p className="m-0 mb-2 text-[10px] font-medium tracking-wide text-slate-400">
          细节
        </p>
        <div className="space-y-2.5">{DETAIL.map(renderControl)}</div>
      </div>

      <div className="flex items-center gap-2 pt-0.5">
        <Button
          size="small"
          className="h-7! flex-1 text-xs!"
          onClick={() => {
            setValues(ZERO)
            onPreview(ZERO)
          }}
        >
          重置
        </Button>
        <Button
          size="small"
          type="primary"
          className="h-7! flex-1 text-xs!"
          loading={applying}
          disabled={!dirty}
          onClick={() => onApply(values)}
        >
          应用
        </Button>
      </div>
    </div>
  )
}

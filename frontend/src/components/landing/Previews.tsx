/**
 * 落地页用的**示意图**（纯 SVG，无图片资源）。
 *
 * 刻意画成抽象的界面示意而不是假的效果图：用占位图冒充真实产出，
 * 演示时被追问一句「这是模型出的吗」就露馅了。
 */

import type { Capability } from '@/lib/marketing'

const STROKE = { strokeWidth: 1.4 } as const

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 160 110" className="h-full w-full" aria-hidden>
      <rect x="0.6" y="0.6" width="158.8" height="108.8" rx="8" fill="#ffffff" stroke="#e5e8e4" {...STROKE} />
      <g>{children}</g>
    </svg>
  )
}

function GeneratePreview() {
  const tiles = [
    { x: 12, y: 14, hue: '#e8f2f5' },
    { x: 84, y: 14, hue: '#f6f7f5' },
    { x: 12, y: 60, hue: '#f6f7f5' },
    { x: 84, y: 60, hue: '#e8f2f5' },
  ]
  return (
    <Frame>
      {tiles.map((tile) => (
        <g key={`${tile.x}-${tile.y}`}>
          <rect x={tile.x} y={tile.y} width="64" height="40" rx="5" fill={tile.hue} />
          <circle cx={tile.x + 32} cy={tile.y + 20} r="9" fill="#ffffff" stroke="#5f98ad" {...STROKE} />
        </g>
      ))}
      <rect x="84" y="60" width="64" height="40" rx="5" fill="none" stroke="#5f98ad" strokeWidth="2" />
    </Frame>
  )
}

function EditPreview() {
  return (
    <Frame>
      <rect x="12" y="18" width="62" height="74" rx="6" fill="#f6f7f5" />
      <rect x="86" y="18" width="62" height="74" rx="6" fill="#e8f2f5" />
      <circle cx="43" cy="55" r="14" fill="#ffffff" stroke="#9aa09a" {...STROKE} />
      <circle cx="117" cy="55" r="14" fill="#d9ff6e" stroke="#5f98ad" {...STROKE} />
      <path d="M80 40v30" stroke="#5f98ad" strokeWidth="1.4" strokeDasharray="3 3" />
      <circle cx="80" cy="55" r="7" fill="#ffffff" stroke="#5f98ad" {...STROKE} />
    </Frame>
  )
}

function LocalPreview() {
  return (
    <Frame>
      <rect x="12" y="18" width="136" height="74" rx="6" fill="#f6f7f5" />
      <rect x="30" y="34" width="42" height="34" rx="4" fill="#e8f2f5" />
      <rect x="86" y="34" width="42" height="34" rx="4" fill="#e8f2f5" />
      <ellipse
        cx="105"
        cy="52"
        rx="30"
        ry="24"
        fill="none"
        stroke="#5f98ad"
        strokeWidth="1.6"
        strokeDasharray="4 3"
      />
      <circle cx="105" cy="52" r="9" fill="#d9ff6e" opacity="0.7" />
    </Frame>
  )
}

function BatchPreview() {
  return (
    <Frame>
      <rect x="14" y="24" width="38" height="62" rx="4" fill="#e8f2f5" />
      <rect x="60" y="14" width="38" height="82" rx="4" fill="#f6f7f5" />
      <rect x="106" y="34" width="40" height="52" rx="4" fill="#e8f2f5" />
      <path d="M23 88l10-12 8 9" stroke="#5f98ad" strokeWidth="1.4" fill="none" />
      <path d="M69 90l12-16 9 12" stroke="#9aa09a" strokeWidth="1.4" fill="none" />
      <path d="M116 80l12-16 8 10" stroke="#5f98ad" strokeWidth="1.4" fill="none" />
    </Frame>
  )
}

const PREVIEWS = {
  generate: GeneratePreview,
  edit: EditPreview,
  local: LocalPreview,
  batch: BatchPreview,
}

export default function CapabilityPreview({ kind }: { kind: Capability['preview'] }) {
  const Component = PREVIEWS[kind]
  return <Component />
}
